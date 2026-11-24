"""Business logic for the SIFL competition system.

Matching, points, FencingTime results import, registrations, seeding, exports, resets.
"""
import csv
import difflib
import io
import re
from pathlib import Path

import pandas as pd

import sifl_db as db
from sifl_db import GENDERS, WEAPONS

# AFF points scale: (lowest placing, highest placing, points)
PLACE_BANDS = [
    (1, 1, 32), (2, 2, 26), (3, 3, 20), (5, 8, 14),
    (9, 16, 8), (17, 32, 4), (33, 64, 2), (65, 10 ** 6, 1),
]
WEAPON_WORDS = [("epee", "Epee"), ("épée", "Epee"), ("foil", "Foil"),
                ("sabre", "Saber"), ("saber", "Saber")]
GENDER_NAME = {"M": "Men's", "F": "Women's", "X": "Mixed"}
GENDER_FILE = {"M": "Mens", "F": "Womens", "X": "Mixed"}
SEEDING_COLUMNS = ["ID", "First name", "Last name", "Weapon", "Gender", "Ranking", "Points", "Club"]
COMPETITOR_COLUMNS = ["ID", "First name", "Last name", "Club", "Gender"]
FENCER_COLUMNS = ["ID", "First name", "Last name", "Club", "Gender",
                  "Epee Points", "Foil Points", "Saber Points"]


# ---------- points and names ----------

def parse_placing(text):
    """'3T' -> 3. A tied placing uses the band of its number."""
    s = str(text).strip().upper()
    if s.endswith("T"):
        s = s[:-1]
    if not s.isdigit():
        raise ValueError(f"Cannot read placing '{text}'")
    return int(s)


def points_for_placing(text):
    n = parse_placing(text)
    for low, high, pts in PLACE_BANDS:
        if low <= n <= high:
            return pts
    raise ValueError(f"No points band for placing '{text}'")


def split_ft_name(name):
    """FencingTime writes 'LASTNAME Firstname'. Split at the first space."""
    s = db.clean(name)
    if " " not in s:
        return s, ""
    last, first = s.split(" ", 1)
    return last, first


def parse_weapons(text):
    """'Epee and Foil' -> ['Epee', 'Foil']."""
    found = []
    for part in re.split(r"\band\b|,|/|&|\+", str(text).lower()):
        part = part.strip()
        if not part:
            continue
        match = next((w for word, w in WEAPON_WORDS if word in part), None)
        if match is None:
            raise ValueError(f"Cannot read weapon from '{text}'")
        if match not in found:
            found.append(match)
    if not found:
        raise ValueError("No weapon given")
    return found


def parse_gender(text):
    t = str(text).lower()
    if "women" in t or "female" in t:
        return "F"
    if "men" in t or "male" in t:
        return "M"
    raise ValueError(f"Cannot read gender from '{text}'")


def slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", str(text)).strip("_") or "export"


def _candidate(conn, fid):
    f = db.get_fencer(conn, fid)
    return {"id": fid, "name": f"{f['first_name']} {f['last_name']}",
            "club": f["club"], "gender": f["gender"]}


def suggest(conn, last, first, limit=3, threshold=0.6):
    """Fencers with a similar name (fuzzy). Suggestions only, never assigned automatically."""
    key = db.name_key(last, first)
    best = {}
    for row in conn.execute("SELECT name_key, fencer_id FROM fencer_names"):
        score = difflib.SequenceMatcher(None, key, row["name_key"]).ratio()
        if score >= threshold and score > best.get(row["fencer_id"], 0):
            best[row["fencer_id"]] = score
    ranked = sorted(best.items(), key=lambda kv: -kv[1])[:limit]
    return [dict(_candidate(conn, fid), score=round(score, 2)) for fid, score in ranked]


def classify(conn, last, first, wanted_gender=None):
    """Return (status, fencer_id, candidates, message).

    matched: exactly one fencer has this name and the gender fits.
    review:  several matches, a gender mismatch, or only similar names.
    new:     no match and no similar names.
    """
    ids = db.find_fencers_by_name(conn, last, first)
    if len(ids) == 1:
        f = db.get_fencer(conn, ids[0])
        if wanted_gender in GENDERS and f["gender"] != wanted_gender:
            return ("review", ids[0], [_candidate(conn, ids[0])],
                    f"Exact name match, but gender on file is {f['gender']}")
        return "matched", ids[0], [_candidate(conn, ids[0])], ""
    if len(ids) > 1:
        return ("review", None, [_candidate(conn, i) for i in ids],
                "More than one fencer has this name")
    cands = suggest(conn, last, first)
    if cands:
        return "review", None, cands, "No exact match. Check the suggestions"
    return "new", None, [], "New fencer"


# ---------- FencingTime results ----------

def read_results_file(data):
    df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False)
    lower = {c.strip().lower(): c for c in df.columns}
    if "place" not in lower or "name" not in lower:
        raise ValueError("This is not a FencingTime results file (needs Place and Name columns)")
    club_col = next((c for c in df.columns if c.strip().lower().startswith("club")), None)
    rows = []
    for _, r in df.iterrows():
        name = db.clean(r[lower["name"]])
        if not name:
            continue
        rows.append({
            "place": db.clean(r[lower["place"]]),
            "name": name,
            "club": db.clean(r[club_col]) if club_col else "",
        })
    if not rows:
        raise ValueError("The results file has no rows")
    return rows


def preview_results(conn, rows, event_gender=None):
    items = []
    for i, r in enumerate(rows):
        item = {"index": i, "place": r["place"], "name": r["name"], "club": r["club"],
                "points": None, "status": "", "message": "", "fencer_id": None, "candidates": []}
        try:
            item["points"] = points_for_placing(r["place"])
        except ValueError as e:
            item.update(status="error", message=str(e))
            items.append(item)
            continue
        last, first = split_ft_name(r["name"])
        status, fid, cands, msg = classify(conn, last, first, event_gender)
        item.update(status=status, fencer_id=fid, candidates=cands, message=msg)
        items.append(item)
    return items


def resolve_event(conn, spec):
    """spec is {"competition_id": n} for an existing event, or {"new": {...}} to create one."""
    if spec.get("competition_id"):
        c = db.get_competition(conn, int(spec["competition_id"]))
        if c is None or c["kind"] != "event":
            raise ValueError("Event not found")
        return {"weapon": c["weapon"], "event_gender": c["event_gender"],
                "competition_id": c["id"], "event": None}
    n = spec.get("new") or {}
    if n.get("weapon") not in WEAPONS:
        raise ValueError("Choose a weapon")
    if n.get("event_gender") not in ("M", "F", "X"):
        raise ValueError("Choose Men, Women or Mixed")
    if not n.get("name") or not n.get("event_date"):
        raise ValueError("Enter a name and a date for the new event")
    return {"weapon": n["weapon"], "event_gender": n["event_gender"],
            "competition_id": None,
            "event": {"name": db.clean(n["name"]), "event_date": n["event_date"]}}


def commit_results(conn, rows, decisions, weapon, event_gender,
                   competition_id=None, event=None):
    """decisions: {row_index: {"action": "match"|"new"|"skip", "fencer_id"?, "gender"?}}.

    Every row that is not an automatic match needs a decision. Nothing is saved
    unless every row is valid.
    """
    items = preview_results(conn, rows, event_gender)
    plan = []
    for item in items:
        i = item["index"]
        if item["status"] == "error":
            raise ValueError(f"Row {i + 1} ({item['name']}): {item['message']}")
        d = decisions.get(i)
        if d is None and item["status"] == "matched":
            d = {"action": "match", "fencer_id": item["fencer_id"]}
        if d is None:
            raise ValueError(f"Row {i + 1} ({item['name']}) needs a decision")
        if d["action"] == "skip":
            continue
        if d["action"] == "match":
            fid = d.get("fencer_id")
            if not fid or db.get_fencer(conn, fid) is None:
                raise ValueError(f"Row {i + 1} ({item['name']}): choose a valid fencer")
        elif d["action"] == "new":
            fid = None
        else:
            raise ValueError(f"Row {i + 1}: unknown action {d['action']!r}")
        plan.append((item, d, fid))

    # the same person must not appear twice in one file
    seen = {}
    for item, _, fid in plan:
        key = fid or db.name_key(*split_ft_name(item["name"]))
        if key in seen:
            raise ValueError(f"'{item['name']}' appears in rows {seen[key] + 1} and {item['index'] + 1}")
        seen[key] = item["index"]

    try:
        if competition_id is None:
            competition_id = db.add_competition(
                conn, name=event["name"], kind="event", event_date=event["event_date"],
                weapon=weapon, event_gender=event_gender)
        else:
            c = db.get_competition(conn, competition_id)
            if c["weapon"] != weapon:
                raise ValueError("Event weapon does not match")
            if conn.execute("SELECT COUNT(*) FROM results WHERE competition_id = ?",
                            (competition_id,)).fetchone()[0]:
                raise ValueError("This event already has results. Clear them first if you need to re-import")
        registered = {r["fencer_id"] for r in conn.execute(
            "SELECT fencer_id FROM registrations WHERE competition_id = ?", (competition_id,))}
        created, warnings = [], []
        for item, d, fid in plan:
            if fid is None:
                last, first = split_ft_name(item["name"])
                gender = d.get("gender") or (event_gender if event_gender in GENDERS else None)
                if gender not in GENDERS:
                    raise ValueError(f"Row {item['index'] + 1} ({item['name']}): choose a gender for the new fencer")
                fid = db.add_fencer(conn, first, last, gender, item["club"])
                created.append(f"{first} {last} ({fid})")
            f = db.get_fencer(conn, fid)
            if registered and fid not in registered:
                warnings.append(f"{f['first_name']} {f['last_name']} was not registered for this event")
            db.add_result(conn, competition_id, fid, weapon, f["gender"],
                          item["place"], item["points"], note=f"FencingTime: {item['name']}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {"competition_id": competition_id, "saved": len(plan),
            "created": created, "warnings": warnings}


# ---------- registrations (Google Form export) ----------

def _txt(v):
    return "" if pd.isna(v) else db.clean(v)


def read_registration_file(data):
    """Return (entries, problems). One entry per weapon per form row."""
    df = pd.read_excel(io.BytesIO(data))

    def find(*words):
        for c in df.columns:
            if all(w in str(c).lower() for w in words):
                return c
        raise ValueError(f"Registration file has no column containing: {' '.join(words)}")

    cols = {
        "ts": find("timestamp"), "first": find("first", "name"), "last": find("last", "name"),
        "event": find("which event"), "gender": find("competitions"), "club": find("represent"),
    }
    entries, problems = [], []
    for idx, r in df.iterrows():
        row_no = idx + 2  # spreadsheet row (row 1 is the header)
        first, last = _txt(r[cols["first"]]), _txt(r[cols["last"]])
        if not first or not last:
            problems.append(f"Row {row_no}: missing first or last name")
            continue
        try:
            weapons = parse_weapons(_txt(r[cols["event"]]))
            gender = parse_gender(_txt(r[cols["gender"]]))
        except ValueError as e:
            problems.append(f"Row {row_no} ({first} {last}): {e}")
            continue
        ts = pd.to_datetime(r[cols["ts"]], errors="coerce")
        ts = ts if pd.notna(ts) else pd.Timestamp.min
        club = _txt(r[cols["club"]])
        for w in weapons:
            entries.append({"row": row_no, "ts": ts, "first": first, "last": last,
                            "key": db.name_key(last, first), "weapon": w,
                            "gender": gender, "club": club})
    return entries, problems


def build_people(entries):
    """Keep the latest entry per person and weapon. Flag conflicting details."""
    entries = sorted(entries, key=lambda e: (e["ts"], e["row"]))
    latest, flags = {}, {}
    for e in entries:
        k = (e["key"], e["weapon"])
        if k in latest:
            old = latest[k]
            if (old["gender"], old["club"]) != (e["gender"], e["club"]):
                flags.setdefault(e["key"], []).append(
                    f"{e['weapon']} entered twice with different details "
                    f"(rows {old['row']} and {e['row']}). Latest used.")
        latest[k] = e
    people = {}
    for (key, weapon), e in latest.items():
        p = people.setdefault(key, {"key": key, "first": e["first"], "last": e["last"],
                                    "weapons": [], "entries": []})
        p["weapons"].append(weapon)
        p["entries"].append(e)
    for key, p in people.items():
        newest = max(p["entries"], key=lambda e: (e["ts"], e["row"]))
        p["gender"] = newest["gender"]
        p["club"] = newest["club"]
        p["flags"] = list(flags.get(key, []))
        if len({e["gender"] for e in p["entries"]}) > 1:
            p["flags"].append("Gender differs between the entries")
        if len({e["club"] for e in p["entries"]}) > 1:
            p["flags"].append("Club differs between the entries")
    return people


def classify_people(conn, people):
    for p in people.values():
        status, fid, cands, msg = classify(conn, p["last"], p["first"], p["gender"])
        p.update(status=status, fencer_id=fid, candidates=cands, message=msg)
        if p["flags"]:
            p["status"] = "review"
            p["message"] = "; ".join(p["flags"])
    return people


def resolve_people(conn, people, decisions):
    """Turn decisions into {person_key: {action, fencer_id, gender}}.

    action is None when a decision is still needed. Gender comes from the fencer
    record for matches, and from the form (or the decision) for new fencers.
    """
    plan = {}
    for key, p in people.items():
        d = decisions.get(key)
        if d is None and p["status"] == "matched":
            d = {"action": "match", "fencer_id": p["fencer_id"]}
        if d is None:
            plan[key] = {"action": None, "fencer_id": None, "gender": p["gender"]}
        elif d["action"] == "skip":
            plan[key] = {"action": "skip", "fencer_id": None, "gender": p["gender"]}
        elif d["action"] == "match":
            fid = d.get("fencer_id")
            f = db.get_fencer(conn, fid) if fid else None
            if f is None:
                raise ValueError(f"{p['first']} {p['last']}: choose a valid fencer")
            plan[key] = {"action": "match", "fencer_id": fid, "gender": f["gender"]}
        elif d["action"] == "new":
            gender = d.get("gender") or p["gender"]
            if gender not in GENDERS:
                raise ValueError(f"{p['first']} {p['last']}: choose a gender")
            plan[key] = {"action": "new", "fencer_id": None, "gender": gender}
        else:
            raise ValueError(f"Unknown action {d['action']!r}")
    return plan


def group_events(people, plan, mixed_weapons=()):
    """{(weapon, event_gender): [person_key, ...]}. Mixed weapons get one event with X."""
    groups = {}
    for key, p in people.items():
        v = plan.get(key, {})
        if v.get("action") == "skip":
            continue
        gender = v.get("gender") or p["gender"]
        for e in p["entries"]:
            eg = "X" if e["weapon"] in mixed_weapons else gender
            groups.setdefault((e["weapon"], eg), []).append(key)
    return groups


def _person_out(key, p):
    return {"key": key, "name": f"{p['first']} {p['last']}", "gender": p["gender"],
            "club": p["club"], "weapons": p["weapons"], "status": p["status"],
            "fencer_id": p["fencer_id"], "candidates": p["candidates"], "message": p["message"]}


def preview_registrations(conn, data, mixed_weapons=()):
    entries, problems = read_registration_file(data)
    people = classify_people(conn, build_people(entries))
    plan = resolve_people(conn, people, {})
    groups = group_events(people, plan, mixed_weapons)
    return {
        "problems": problems,
        "people": [_person_out(k, p) for k, p in people.items()],
        "events": [{"label": f"{w} - {GENDER_NAME[eg]}", "weapon": w, "event_gender": eg,
                    "entrants": len(keys)} for (w, eg), keys in sorted(groups.items())],
    }


# ---------- seeding and rankings ----------

def rank_rows(rows):
    """Sort by points, then name. Standard competition ranking: ties share a rank,
    the next rank is skipped (1, 1, 3)."""
    ordered = sorted(rows, key=lambda r: (-r["Points"], r["Last name"].lower(), r["First name"].lower()))
    all_points = [r["Points"] for r in ordered]
    return [{**r, "Ranking": 1 + sum(1 for p in all_points if p > r["Points"])} for r in ordered]


def seeding_for_event(conn, competition_id):
    c = db.get_competition(conn, competition_id)
    pm = db.points_map(conn, c["weapon"])
    regs = conn.execute(
        "SELECT f.* FROM registrations r JOIN fencers f ON f.id = r.fencer_id "
        "WHERE r.competition_id = ?", (competition_id,)).fetchall()
    rows = [{"ID": f["id"], "First name": f["first_name"], "Last name": f["last_name"],
             "Weapon": c["weapon"], "Gender": f["gender"], "Points": pm.get(f["id"], 0),
             "Club": f["club"]} for f in regs]
    return rank_rows(rows)


def ranking_table(conn, weapon, gender=None):
    """All fencers for one weapon (optionally one gender), in seeding format."""
    rows = [{"ID": r["id"], "First name": r["first_name"], "Last name": r["last_name"],
             "Weapon": weapon, "Gender": r["gender"], "Points": r["points"], "Club": r["club"]}
            for r in db.current_points(conn, weapon, gender)]
    return rank_rows(rows)


def csv_text(columns, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def write_csv(path, columns, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        fh.write(csv_text(columns, rows))
    return path


# ---------- export files ----------

def event_files(conn, competition_id, folder):
    """Competitor list and seeding list for one event."""
    c = db.get_competition(conn, competition_id)
    stem = f"{c['weapon']}_{GENDER_FILE.get(c['event_gender'], 'Event')}"
    regs = conn.execute(
        "SELECT f.* FROM registrations r JOIN fencers f ON f.id = r.fencer_id "
        "WHERE r.competition_id = ? ORDER BY f.last_name, f.first_name",
        (competition_id,)).fetchall()
    competitors = [{"ID": f["id"], "First name": f["first_name"], "Last name": f["last_name"],
                    "Club": f["club"], "Gender": f["gender"]} for f in regs]
    return [
        write_csv(Path(folder) / f"{stem}_competitors.csv", COMPETITOR_COLUMNS, competitors),
        write_csv(Path(folder) / f"{stem}_seeding.csv", SEEDING_COLUMNS,
                  seeding_for_event(conn, competition_id)),
    ]


def event_export(conn, competition_id, export_dir):
    c = db.get_competition(conn, competition_id)
    if c is None or c["kind"] != "event":
        raise ValueError("Event not found")
    folder = Path(export_dir) / "events" / slug(c["name"])
    return event_files(conn, competition_id, folder)


def round_files(conn, round_name, export_dir):
    """Fencer import file plus competitor and seeding files for every event in a round."""
    folder = Path(export_dir) / slug(round_name)
    ids = [r["fencer_id"] for r in conn.execute(
        "SELECT DISTINCT r.fencer_id FROM registrations r "
        "JOIN competitions c ON c.id = r.competition_id WHERE c.round_name = ?", (round_name,))]
    pms = {w: db.points_map(conn, w) for w in WEAPONS}
    rows = []
    for fid in ids:
        f = db.get_fencer(conn, fid)
        rows.append({"ID": fid, "First name": f["first_name"], "Last name": f["last_name"],
                     "Club": f["club"], "Gender": f["gender"],
                     "Epee Points": pms["Epee"].get(fid, 0),
                     "Foil Points": pms["Foil"].get(fid, 0),
                     "Saber Points": pms["Saber"].get(fid, 0)})
    rows.sort(key=lambda r: (r["Last name"].lower(), r["First name"].lower()))
    files = [write_csv(folder / "FencingTime_fencers.csv", FENCER_COLUMNS, rows)]
    for c in conn.execute(
            "SELECT id FROM competitions WHERE round_name = ? AND kind = 'event' "
            "ORDER BY weapon, event_gender", (round_name,)).fetchall():
        files += event_files(conn, c["id"], folder)
    return folder, files


# ---------- registration commit ----------

def commit_registrations(conn, data, round_name, event_date, mixed_weapons, decisions, export_dir):
    round_name = db.clean(round_name)
    if not round_name:
        raise ValueError("Enter a round name")
    if not event_date:
        raise ValueError("Enter an event date")
    if conn.execute("SELECT 1 FROM competitions WHERE round_name = ?", (round_name,)).fetchone():
        raise ValueError(f"A round called '{round_name}' already exists")
    entries, problems = read_registration_file(data)
    if problems:
        raise ValueError("Fix these rows in the file first: " + "; ".join(problems))
    people = classify_people(conn, build_people(entries))
    plan = resolve_people(conn, people, decisions)
    missing = [people[k]["first"] + " " + people[k]["last"]
               for k, v in plan.items() if v["action"] is None]
    if missing:
        raise ValueError("These people need a decision: " + ", ".join(missing))
    matched = [v["fencer_id"] for v in plan.values() if v["action"] == "match"]
    dups = sorted({x for x in matched if matched.count(x) > 1})
    if dups:
        raise ValueError("Two registrations are matched to the same fencer: " + ", ".join(dups))
    groups = group_events(people, plan, mixed_weapons)
    if not groups:
        raise ValueError("Nobody to register")

    created = []
    try:
        ids = {}
        for key, v in plan.items():
            if v["action"] == "skip":
                continue
            p = people[key]
            if v["action"] == "new":
                fid = db.add_fencer(conn, p["first"], p["last"], v["gender"], p["club"])
                created.append(f"{p['first']} {p['last']} ({fid})")
            else:
                fid = v["fencer_id"]
            ids[key] = fid
        for (weapon, eg), keys in sorted(groups.items()):
            cid = db.add_competition(
                conn, name=f"{round_name} - {weapon} {GENDER_NAME[eg]}", kind="event",
                event_date=event_date, weapon=weapon, event_gender=eg, round_name=round_name)
            for key in keys:
                db.add_registration(conn, cid, ids[key], weapon)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    folder, files = round_files(conn, round_name, export_dir)
    return {"round": round_name, "created": created, "folder": str(folder),
            "files": [str(f) for f in files],
            "events": [{"label": f"{w} - {GENDER_NAME[eg]}", "entrants": len(keys)}
                       for (w, eg), keys in sorted(groups.items())]}


# ---------- events, fencers, resets ----------

def list_events(conn):
    return [dict(r) for r in db.list_competitions(conn) if r["kind"] == "event"]


def delete_event(conn, competition_id):
    try:
        db.delete_competition(conn, competition_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def clear_event_results(conn, competition_id):
    try:
        n = db.clear_results(conn, competition_id)
        conn.commit()
        return n
    except Exception:
        conn.rollback()
        raise


def fencer_search(conn, q):
    out = []
    for f in db.list_fencers(conn, q):
        pts = {w: db.points_map(conn, w).get(f["id"], 0) for w in WEAPONS}
        out.append({"ID": f["id"], "name": f"{f['first_name']} {f['last_name']}",
                    "Gender": f["gender"], "Club": f["club"],
                    "Epee": pts["Epee"], "Foil": pts["Foil"], "Saber": pts["Saber"]})
    return out


def fencer_detail(conn, fid):
    f = db.get_fencer(conn, fid)
    if f is None:
        raise ValueError("Fencer not found")
    pts = {w: db.points_map(conn, w).get(fid, 0) for w in WEAPONS}
    history = [dict(r) for r in conn.execute(
        "SELECT c.name AS event, c.event_date AS date, r.weapon, r.placing, r.points, r.note "
        "FROM results r JOIN competitions c ON c.id = r.competition_id "
        "WHERE r.fencer_id = ? ORDER BY c.event_date, c.id", (fid,))]
    return {"fencer": dict(f), "aliases": db.fencer_aliases(conn, fid),
            "points": pts, "history": history}


def reset_points(conn, note=""):
    try:
        d = db.add_reset(conn, note)
        conn.commit()
        return d
    except Exception:
        conn.rollback()
        raise
