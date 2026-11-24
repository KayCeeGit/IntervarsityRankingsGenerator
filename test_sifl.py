"""Tests for the SIFL system. Run:  python test_sifl.py

Builds a fresh database in a temporary folder from the real seeding files and
registration/result files, then checks every stage. Prints PASS/FAIL per check.
Nothing in the real database or exports folder is touched.
"""
import base64
import json
import shutil
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sifl_db as db
import sifl_logic as lg
import sifl_app
import stage1_opening_balance as s1

UPLOADS = Path("/mnt/user-data/uploads")
REG_FILE = Path("/mnt/user-data/attachments/e239244a-e860-5896-b014-5b924e4a92ff/"
                "0622d9b2-SIFL_2026_5_Responses_1.xlsx")
RESULTS_FILE = UPLOADS / "eventResults.csv"
SEED_SAMPLE = UPLOADS / "2026_09_15_DatabaseMEUpdated.csv"

RESULTS = []


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond)))
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail and not cond else ""))


def fid_by_name(conn, last, first):
    ids = db.find_fencers_by_name(conn, last, first)
    return ids[0] if len(ids) == 1 else None


def pts(conn, fid, weapon):
    return db.points_map(conn, weapon).get(fid, 0)


def b64(path):
    return base64.b64encode(Path(path).read_bytes()).decode()


def test_stage1(work, conn):
    records = s1.load_records(UPLOADS)
    s1.load_opening_balance(conn, records)
    problems = s1.check_totals(conn, records)
    check("opening balance totals match the three seeding files", not problems, str(problems))
    n = conn.execute("SELECT COUNT(*) FROM fencers").fetchone()[0]
    check("opening balance has 81 fencers", n == 81, str(n))
    renouf = fid_by_name(conn, "Renouf", "Zachary")
    check("Renouf merged: Epee 22 points", renouf and pts(conn, renouf, "Epee") == 22,
          str(renouf and pts(conn, renouf, "Epee")))


def test_results(conn, work):
    ilin_ids = [r["id"] for r in conn.execute("SELECT id FROM fencers WHERE last_name = 'Ilin'")]
    ilin = ilin_ids[0] if ilin_ids else None
    ilin_epee_before = pts(conn, ilin, "Epee") if ilin else None

    rows = lg.read_results_file(RESULTS_FILE.read_bytes())
    preview = lg.preview_results(conn, rows, "M")
    check("results preview: every row has points or an error",
          all(p["points"] is not None or p["status"] == "error" for p in preview))
    errs = [p for p in preview if p["status"] == "error"]
    check("results preview: no errors in eventResults.csv", not errs, str([e["message"] for e in errs]))

    decisions = {}
    for p in preview:
        if p["status"] == "matched":
            continue
        if p["status"] == "new":
            decisions[p["index"]] = {"action": "new"}
        else:
            # review rows: take the first suggestion if there is one, otherwise create
            decisions[p["index"]] = ({"action": "match", "fencer_id": p["candidates"][0]["id"]}
                                     if p["candidates"] else {"action": "new"})
    review = [p["name"] for p in preview if p["status"] == "review"]
    print(f"      review rows in test file: {review or 'none'}")

    spec = lg.resolve_event(conn, {"new": {"name": "Test Foil Men", "event_date": "2026-11-01",
                                           "weapon": "Foil", "event_gender": "M"}})
    out = lg.commit_results(conn, rows, decisions, spec["weapon"], spec["event_gender"],
                            event=spec["event"])
    check("results commit saves every row", out["saved"] == len(rows), str(out))
    cid = out["competition_id"]

    mautner = fid_by_name(conn, "Mautner", "Daniel")
    check("Mautner (1st, not in seeding files) is created as a new fencer", mautner is not None)
    if mautner:
        check("Mautner Foil 32 after 1st place", pts(conn, mautner, "Foil") == 32,
              str(pts(conn, mautner, "Foil")))
        check("Mautner Epee untouched by Foil results", pts(conn, mautner, "Epee") == 0)
    check("Ilin found in database", ilin is not None)
    if ilin:
        check("Ilin Foil 20 (placed 3T)", pts(conn, ilin, "Foil") == 20, str(pts(conn, ilin, "Foil")))
        check("Ilin Epee unchanged by Foil results", pts(conn, ilin, "Epee") == ilin_epee_before)

    try:
        lg.commit_results(conn, rows, decisions, spec["weapon"], spec["event_gender"],
                          competition_id=cid)
        check("second import into the same event is blocked", False)
    except ValueError as e:
        check("second import into the same event is blocked", "already has results" in str(e), str(e))
    return cid


def test_points_helpers():
    check("parse 1st", lg.points_for_placing("1") == 32)
    check("parse tie 3T", lg.points_for_placing("3T") == 20)
    check("parse 5T", lg.points_for_placing("5T") == 14)
    check("parse 65+ band", lg.points_for_placing("65") == 1)
    check("split FT name", lg.split_ft_name("RENOUF Zachary") == ("RENOUF", "Zachary"))
    check("parse weapons 'Epee and Foil'", lg.parse_weapons("Epee and Foil") == ["Epee", "Foil"])
    check("parse weapon 'Sabre'", lg.parse_weapons("Sabre") == ["Saber"])


def test_registrations(conn, work):
    data = REG_FILE.read_bytes()
    prev = lg.preview_registrations(conn, data)
    check("registration file reads with no row problems", not prev["problems"], str(prev["problems"]))
    events = sorted(e["label"] for e in prev["events"])
    expected = sorted(["Epee - Men's", "Epee - Women's", "Foil - Men's", "Foil - Women's",
                       "Saber - Men's", "Saber - Women's"])
    check("registration events are weapon x gender, no mixed", events == expected, str(events))
    names = [p["name"] for p in prev["people"]]
    check("Zihan Chi appears once", sum(1 for n in names if "Zihan Chi" in n) <= 1, str(names))
    check("registration people count is 83", len(prev["people"]) == 83, str(len(prev["people"])))

    keep = {p["key"]: p for p in prev["people"]}
    decisions = {}
    for key, p in keep.items():
        if p["status"] == "matched":
            decisions[key] = {"action": "match", "fencer_id": p["fencer_id"]}
        elif p["status"] == "new":
            decisions[key] = {"action": "new"}
        else:
            decisions[key] = {"action": "new"}  # test only: review cases created as new
    export = Path(work) / "exports"
    out = lg.commit_registrations(conn, data, "Test Round", "2026-11-01", (), decisions, export)
    check("registration commit creates 6 events", len(out["events"]) == 6, str(out["events"]))
    files = [Path(f) for f in out["files"]]
    check("fencer import file written", any(f.name == "FencingTime_fencers.csv" for f in files))
    comp = [f for f in files if f.name.endswith("_competitors.csv")]
    seed = [f for f in files if f.name.endswith("_seeding.csv")]
    check("6 competitor and 6 seeding files", len(comp) == 6 and len(seed) == 6,
          f"{len(comp)} {len(seed)}")
    sample_header = SEED_SAMPLE.read_text(encoding="utf-8-sig").splitlines()[0].strip()
    made_header = seed[0].read_text(encoding="utf-8").splitlines()[0].strip()
    check("seeding header matches sample file", sample_header == made_header,
          f"{sample_header!r} vs {made_header!r}")
    try:
        lg.commit_registrations(conn, data, "Test Round", "2026-11-01", (), decisions, export)
        check("repeat round name is refused", False)
    except ValueError as e:
        check("repeat round name is refused", "already exists" in str(e))

    # mixed saber event
    out2 = lg.commit_registrations(conn, data, "Mixed Test", "2026-11-02", ("Saber",),
                                   decisions, export)
    mixed = [e for e in out2["events"] if e["label"].startswith("Saber - Mixed")]
    check("mixed Saber event created", len(mixed) == 1, str(out2["events"]))
    return out


def test_ranking_ties(conn):
    rows = [{"ID": "A", "First name": "A", "Last name": "A", "Weapon": "Epee", "Gender": "M", "Points": 10, "Club": ""},
            {"ID": "B", "First name": "B", "Last name": "B", "Weapon": "Epee", "Gender": "M", "Points": 10, "Club": ""},
            {"ID": "C", "First name": "C", "Last name": "C", "Weapon": "Epee", "Gender": "M", "Points": 4, "Club": ""}]
    ranked = lg.rank_rows(rows)
    check("tied points share a rank and next rank skips", [r["Ranking"] for r in ranked] == [1, 1, 3],
          str([r["Ranking"] for r in ranked]))


def test_reset_and_history(conn):
    before_hist = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    lg.reset_points(conn, "test reset")
    any_pts = conn.execute("SELECT COUNT(*) FROM fencers f WHERE "
                           "(SELECT COALESCE(SUM(points),0) FROM results r JOIN competitions c "
                           "ON c.id=r.competition_id WHERE r.fencer_id=f.id AND c.event_date >= ?)>0",
                           (db.latest_reset_date(conn),)).fetchone()[0]
    check("reset zeroes current points", any_pts == 0, str(any_pts))
    after_hist = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    check("reset keeps results history", before_hist == after_hist)


def test_merge_and_edit(conn):
    a = db.add_fencer(conn, "Test", "Person", "M", "Club A")
    b = db.add_fencer(conn, "Tester", "Person", "M", "Club A")
    try:
        db.merge_fencers(conn, a, b)
        conn.commit()
        check("merge removes the dropped fencer", db.get_fencer(conn, b) is None)
    except Exception as e:
        check("merge removes the dropped fencer", False, str(e))
    c = db.add_fencer(conn, "Other", "Gender", "F", "")
    try:
        db.merge_fencers(conn, a, c)
        check("merge refuses different genders", False)
    except ValueError:
        check("merge refuses different genders", True)
    conn.rollback()


def test_delete_event(conn):
    cid = conn.execute("SELECT id FROM competitions WHERE kind='event' AND name LIKE 'Test Foil%'").fetchone()
    if cid is None:
        check("delete event (skipped: no test event)", False)
        return
    lg.delete_event(conn, cid["id"])
    gone = conn.execute("SELECT COUNT(*) FROM registrations WHERE competition_id=?", (cid["id"],)).fetchone()[0]
    check("delete event removes its registrations", gone == 0)


def test_backup(work):
    dbp = Path(work) / "sifl.db"
    dest = db.backup_db(dbp, Path(work) / "backups")
    check("backup file created", dest is not None and dest.exists())


def test_http(work):
    cfg = sifl_app.CONFIG
    cfg.update(db=Path(work) / "sifl.db", exports=Path(work) / "exports",
               backups=Path(work) / "backups", ui=HERE / "sifl_ui.html")
    server = sifl_app.make_server(8799)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    base = "http://127.0.0.1:8799"
    try:
        page = urllib.request.urlopen(base + "/").read().decode()
        check("HTTP: page served", "SIFL Competition System" in page)
        st = json.loads(urllib.request.urlopen(base + "/api/state").read())
        check("HTTP: state reports fencers", st["counts"]["fencers"] > 0, str(st["counts"]))
        rk = json.loads(urllib.request.urlopen(base + "/api/rankings?weapon=Foil&gender=M").read())
        check("HTTP: Foil men rankings", rk["rows"] and rk["rows"][0]["Points"] >= 0)
        req = urllib.request.Request(base + "/api/backup", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        bk = json.loads(urllib.request.urlopen(req).read())
        check("HTTP: backup endpoint", Path(bk["backup"]).exists())
        body = json.dumps({"file": {"filename": "r.csv", "data_base64": b64(RESULTS_FILE)},
                           "event": {"new": {"name": "HTTP test", "event_date": "2026-11-03",
                                             "weapon": "Foil", "event_gender": "M"}}}).encode()
        req = urllib.request.Request(base + "/api/results/preview", data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        pv = json.loads(urllib.request.urlopen(req).read())
        check("HTTP: results preview returns rows", len(pv["rows"]) > 0)
        bad = urllib.request.Request(base + "/api/results/preview", data=b"{}", method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(bad)
            check("HTTP: missing file gives 400", False)
        except urllib.error.HTTPError as e:
            check("HTTP: missing file gives 400", e.code == 400)
        try:
            urllib.request.urlopen(base + "/files/../../etc/passwd")
            check("HTTP: path traversal blocked", False)
        except urllib.error.HTTPError as e:
            check("HTTP: path traversal blocked", e.code in (404, 400))
    finally:
        server.shutdown()
        server.server_close()


def main():
    work = tempfile.mkdtemp(prefix="sifl_test_")
    print(f"Working folder: {work}\n")
    try:
        dbp = Path(work) / "sifl.db"
        conn = db.connect(dbp)
        db.init_db(conn)
        print("Stage 1: opening balance")
        test_stage1(work, conn)
        conn.commit()
        print("\nPoints helpers")
        test_points_helpers()
        print("\nResults import (FencingTime)")
        test_results(conn, work)
        conn.commit()
        print("\nRegistrations (Google Form)")
        test_registrations(conn, work)
        conn.commit()
        print("\nRanking ties")
        test_ranking_ties(conn)
        print("\nReset and history")
        test_reset_and_history(conn)
        conn.commit()
        print("\nMerge, delete, backup")
        test_merge_and_edit(conn)
        test_delete_event(conn)
        conn.commit()
        test_backup(work)
        conn.close()
        print("\nHTTP server")
        test_http(work)
    finally:
        failed = [n for n, ok in RESULTS if not ok]
        print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed")
        for n in failed:
            print("  FAILED:", n)
        shutil.rmtree(work, ignore_errors=True)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
