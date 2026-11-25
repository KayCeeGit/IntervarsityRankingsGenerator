"""Stage 2: add Women's Epee opening points from 2026_09_15_DatabaseWEUpdated.csv.

Usage:  python stage2_womens_epee.py <path_to_WE_csv> <path_to_sifl.db>
A backup of the database is taken first. Gender "W" is read as "F".
Matching rule is the same as stage 1: same name and same gender = same fencer.
"""
import sys
from pathlib import Path

import pandas as pd

import sifl_db as db

OPENING_DATE = "2026-09-15"


def main():
    csv_path, db_path = Path(sys.argv[1]), Path(sys.argv[2])
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    records = []
    for _, r in df.iterrows():
        gender = r["Gender"].strip()
        gender = {"W": "F"}.get(gender, gender)
        if r["Weapon"].strip() != "Epee" or gender != "F":
            raise SystemExit(f"Unexpected row {r['ID']}: {r['Weapon']}/{r['Gender']}")
        records.append({"legacy_id": r["ID"].strip(), "first": db.clean(r["First name"]),
                        "last": db.clean(r["Last name"]), "gender": gender,
                        "club": db.clean(r["Club"]), "points": int(r["Points"]),
                        "raw_gender": r["Gender"].strip()})
    print("backup:", db.backup_db(db_path, db_path.parent / "backups"))
    conn = db.connect(db_path)
    db.init_db(conn)
    comp = db.add_competition(conn, name="Opening balance (Women's Epee 2026-09-15)", kind="opening",
                              event_date=OPENING_DATE, source_file=csv_path.name)
    notes = []
    for r in records:
        if r["raw_gender"] != r["gender"]:
            notes.append(f"gender '{r['raw_gender']}' read as F: {r['legacy_id']} {r['first']} {r['last']}")
        matches = db.find_fencers_by_name(conn, r["last"], r["first"])
        fid = None
        if matches:
            existing = db.get_fencer(conn, matches[0])
            if existing["gender"] == r["gender"]:
                fid = matches[0]
                conn.execute("UPDATE fencers SET legacy_id = legacy_id || ';' || ? WHERE id = ?",
                             (r["legacy_id"], fid))
                notes.append(f"MERGED {r['legacy_id']} into {fid} (same name and gender)")
            else:
                notes.append(f"NOT MERGED, different gender: {r['legacy_id']} {r['first']} {r['last']}")
        if fid is None:
            fid = db.add_fencer(conn, r["first"], r["last"], r["gender"], r["club"], r["legacy_id"])
        db.add_result(conn, comp, fid, "Epee", r["gender"], placing=None, points=r["points"],
                      note=f"opening {r['legacy_id']}")
    conn.commit()
    total_src = sum(r["points"] for r in records)
    total_db = conn.execute("SELECT COALESCE(SUM(points),0) FROM results WHERE weapon='Epee' AND gender='F' "
                            "AND competition_id=?", (comp,)).fetchone()[0]
    print(f"rows: {len(records)}  points in file: {total_src}  points in database: {total_db}  "
          f"[{'OK' if total_src == total_db else 'MISMATCH'}]")
    print("notes:")
    for n in notes or ["none"]:
        print("  " + n)
    conn.close()


if __name__ == "__main__":
    main()
