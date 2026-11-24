"""SIFL competition system: local web app.

Run:  python sifl_app.py            (opens http://127.0.0.1:8765 in your browser)
Options:  --db PATH  --exports DIR  --backups DIR  --port N  --no-browser

Standard library only (http.server). Binds to 127.0.0.1, so only this computer can reach it.
Every write takes a backup of sifl.db first.
"""
import argparse
import base64
import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote

import sifl_db as db
import sifl_logic as lg

HERE = Path(__file__).resolve().parent
CONFIG = {
    "db": HERE / "sifl.db",
    "exports": HERE / "exports",
    "backups": HERE / "backups",
    "ui": HERE / "sifl_ui.html",
}
WRITE_LOCK = threading.Lock()


class HTTPError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def _rows(rows):
    return [dict(r) for r in rows]


def _file_info(paths):
    out = []
    for p in paths:
        p = Path(p)
        try:
            rel = p.resolve().relative_to(CONFIG["exports"].resolve())
            out.append({"name": p.name, "url": "/files/" + rel.as_posix()})
        except ValueError:
            out.append({"name": p.name, "url": None})
    return out


def _decode_file(body):
    f = body.get("file") or {}
    if not f.get("data_base64"):
        raise ValueError("No file was uploaded")
    try:
        return base64.b64decode(f["data_base64"])
    except Exception:
        raise ValueError("The uploaded file could not be read")


def _int_keys(d):
    return {int(k): v for k, v in (d or {}).items()}


def _backup():
    return db.backup_db(CONFIG["db"], CONFIG["backups"])


def _open():
    conn = db.connect(CONFIG["db"])
    db.init_db(conn)
    return conn


# ---------- read handlers: (conn, query, body) -> data ----------

def get_state(conn, q, body):
    counts = {
        "fencers": conn.execute("SELECT COUNT(*) FROM fencers").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM competitions WHERE kind='event'").fetchone()[0],
        "results": conn.execute("SELECT COUNT(*) FROM results").fetchone()[0],
    }
    reset = db.latest_reset_date(conn)
    return {"counts": counts, "latest_reset": reset, "weapons": list(db.WEAPONS),
            "genders": list(db.GENDERS), "db_path": str(CONFIG["db"]),
            "backup_dir": str(CONFIG["backups"])}


def get_rankings(conn, q, body):
    weapon = q.get("weapon", ["Epee"])[0]
    gender = q.get("gender", [""])[0] or None
    if weapon not in db.WEAPONS:
        raise ValueError("Unknown weapon")
    if gender and gender not in db.GENDERS:
        raise ValueError("Unknown gender")
    return {"weapon": weapon, "gender": gender,
            "latest_reset": db.latest_reset_date(conn),
            "rows": lg.ranking_table(conn, weapon, gender)}


def get_events(conn, q, body):
    return {"events": lg.list_events(conn)}


def get_competition_results(conn, q, body):
    cid = int(q.get("id", ["0"])[0])
    c = db.get_competition(conn, cid)
    if c is None:
        raise ValueError("Competition not found")
    results = _rows(conn.execute(
        "SELECT r.*, f.first_name, f.last_name, f.club FROM results r "
        "JOIN fencers f ON f.id = r.fencer_id WHERE r.competition_id = ? "
        "ORDER BY r.points DESC, f.last_name, f.first_name", (cid,)))
    regs = _rows(conn.execute(
        "SELECT r.fencer_id, r.weapon, f.first_name, f.last_name, f.club, f.gender "
        "FROM registrations r JOIN fencers f ON f.id = r.fencer_id "
        "WHERE r.competition_id = ? ORDER BY f.last_name, f.first_name", (cid,)))
    return {"competition": dict(c), "results": results, "registrations": regs}


def get_fencers(conn, q, body):
    return {"fencers": lg.fencer_search(conn, q.get("q", [""])[0])}


def get_fencer(conn, q, body):
    return lg.fencer_detail(conn, q.get("id", [""])[0])


def get_resets(conn, q, body):
    return {"resets": _rows(db.list_resets(conn))}


def get_export_rankings(conn, q, body):
    weapon = q.get("weapon", ["Epee"])[0]
    gender = q.get("gender", [""])[0] or None
    if weapon not in db.WEAPONS:
        raise ValueError("Unknown weapon")
    name = f"rankings_{weapon}" + (f"_{lg.GENDER_FILE[gender]}" if gender else "_All") + ".csv"
    text = lg.csv_text(lg.SEEDING_COLUMNS, lg.ranking_table(conn, weapon, gender))
    return {"__csv__": True, "name": name, "text": text}


# ---------- write handlers: (conn, body) -> data; these run under the lock with a backup ----------

def post_backup(conn, body):
    return {"backup": str(_backup())}


def post_event_export(conn, body):
    cid = int(body.get("id", 0))
    return {"files": _file_info(lg.event_export(conn, cid, CONFIG["exports"]))}


def post_event_delete(conn, body):
    lg.delete_event(conn, int(body.get("id", 0)))
    return {"deleted": True}


def post_event_clear(conn, body):
    n = lg.clear_event_results(conn, int(body.get("id", 0)))
    return {"cleared": n}


def post_results_preview(conn, body):
    rows = lg.read_results_file(_decode_file(body))
    spec = lg.resolve_event(conn, body.get("event") or {})
    items = lg.preview_results(conn, rows, spec["event_gender"])
    return {"event": {k: spec[k] for k in ("weapon", "event_gender", "competition_id")},
            "rows": items}


def post_results_commit(conn, body):
    rows = lg.read_results_file(_decode_file(body))
    spec = lg.resolve_event(conn, body.get("event") or {})
    decisions = _int_keys(body.get("decisions"))
    backup = _backup()
    out = lg.commit_results(conn, rows, decisions, spec["weapon"], spec["event_gender"],
                            competition_id=spec["competition_id"], event=spec["event"])
    out["backup"] = str(backup)
    return out


def post_registrations_preview(conn, body):
    return lg.preview_registrations(conn, _decode_file(body), tuple(body.get("mixed_weapons") or []))


def post_registrations_commit(conn, body):
    backup = _backup()
    out = lg.commit_registrations(
        conn, _decode_file(body), body.get("round_name", ""), body.get("event_date", ""),
        tuple(body.get("mixed_weapons") or []), body.get("decisions") or {}, CONFIG["exports"])
    out["files"] = _file_info(out.pop("files"))
    out["backup"] = str(backup)
    return out


def post_fencer_update(conn, body):
    _backup()
    fid = body.get("id")
    if not db.get_fencer(conn, fid):
        raise ValueError("Fencer not found")
    db.update_fencer(conn, fid, db.clean(body.get("first", "")),
                     db.clean(body.get("last", "")), db.clean(body.get("club", "")))
    conn.commit()
    return {"updated": fid}


def post_fencer_alias(conn, body):
    _backup()
    if not db.get_fencer(conn, body.get("id")):
        raise ValueError("Fencer not found")
    db.add_alias(conn, body["id"], db.clean(body.get("last", "")), db.clean(body.get("first", "")))
    conn.commit()
    return {"added": True}


def post_fencer_merge(conn, body):
    _backup()
    db.merge_fencers(conn, body.get("keep"), body.get("drop"))
    conn.commit()
    return {"merged_into": body.get("keep")}


def post_reset(conn, body):
    _backup()
    return {"reset_date": lg.reset_points(conn, db.clean(body.get("note", "")))}


POST_ROUTES = {
    "/api/backup": post_backup,
    "/api/event/export": post_event_export,
    "/api/event/delete": post_event_delete,
    "/api/event/clear": post_event_clear,
    "/api/results/preview": post_results_preview,
    "/api/results/commit": post_results_commit,
    "/api/registrations/preview": post_registrations_preview,
    "/api/registrations/commit": post_registrations_commit,
    "/api/fencer/update": post_fencer_update,
    "/api/fencer/alias": post_fencer_alias,
    "/api/fencer/merge": post_fencer_merge,
    "/api/reset": post_reset,
}
WRITE_ROUTES = {"/api/backup", "/api/event/export", "/api/event/delete", "/api/event/clear",
                "/api/results/commit", "/api/registrations/commit", "/api/fencer/update",
                "/api/fencer/alias", "/api/fencer/merge", "/api/reset"}
GET_ROUTES = {
    "/api/state": get_state,
    "/api/rankings": get_rankings,
    "/api/events": get_events,
    "/api/competition_results": get_competition_results,
    "/api/fencers": get_fencers,
    "/api/fencer": get_fencer,
    "/api/resets": get_resets,
    "/api/export/rankings": get_export_rankings,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "SIFL/1.0"

    def log_message(self, fmt, *args):
        pass  # keep the console quiet; errors are printed by _send_error

    def _send(self, status, payload, ctype="application/json; charset=utf-8", headers=None):
        data = payload if isinstance(payload, bytes) else (
            payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload, default=str).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _error(self, status, message):
        self._send(status, {"error": message})

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "Request body is not valid JSON")

    def _run(self, fn, *args):
        conn = _open()
        try:
            return fn(conn, *args)
        finally:
            conn.close()

    def do_GET(self):
        url = urlparse(self.path)
        path, q = url.path, parse_qs(url.query)
        try:
            if path in ("/", "/index.html"):
                return self._send(200, CONFIG["ui"].read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/files/"):
                return self._serve_file(unquote(path[len("/files/"):]))
            if path not in GET_ROUTES:
                return self._error(404, "Not found")
            data = self._run(GET_ROUTES[path], q, {})
            if isinstance(data, dict) and data.get("__csv__"):
                return self._send(200, data["text"].encode("utf-8"), "text/csv; charset=utf-8",
                                  {"Content-Disposition": f'attachment; filename="{data["name"]}"'})
            self._send(200, data)
        except HTTPError as e:
            self._error(e.status, str(e))
        except ValueError as e:
            self._error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self._error(500, f"Unexpected error: {e}")

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path not in POST_ROUTES:
                return self._error(404, "Not found")
            body = self._read_body()
            fn = POST_ROUTES[path]
            if path in WRITE_ROUTES:
                with WRITE_LOCK:
                    data = self._run(fn, body)
            else:
                data = self._run(fn, body)
            self._send(200, data)
        except HTTPError as e:
            self._error(e.status, str(e))
        except ValueError as e:
            self._error(400, str(e))
        except Exception as e:
            traceback.print_exc()
            self._error(500, f"Unexpected error: {e}")

    def _serve_file(self, rel):
        root = CONFIG["exports"].resolve()
        target = (root / rel).resolve()
        if root not in target.parents or not target.is_file():
            return self._error(404, "File not found")
        data = target.read_bytes()
        ctype = "text/csv; charset=utf-8" if target.suffix == ".csv" else "application/octet-stream"
        self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{target.name}"'})


def make_server(port=8765):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    ap = argparse.ArgumentParser(description="SIFL competition system")
    ap.add_argument("--db", default=str(CONFIG["db"]))
    ap.add_argument("--exports", default=str(CONFIG["exports"]))
    ap.add_argument("--backups", default=str(CONFIG["backups"]))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    CONFIG.update(db=Path(args.db), exports=Path(args.exports), backups=Path(args.backups))
    _open().close()  # create the database on first run
    server = make_server(args.port)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"SIFL running at {url}  (Ctrl+C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
