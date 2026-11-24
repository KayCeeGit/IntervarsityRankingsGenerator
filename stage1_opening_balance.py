"""Stage 1: create sifl.db and load opening points from the current seeding files.

Usage:
    python stage1_opening_balance.py <folder_with_csvs> <output_db_path>

Refuses to overwrite an existing database. Prints every merge so it can be checked.
"""
import sys
from pathlib import Path

import pandas as pd

import sifl_db as db

OPENING_DATE = "2026-09-15"

# Old ID -> old ID of the same person, confirmed by the organiser
KNOWN_SAME = {
    "ME_049": "ME_006",  # Zach Renouf = Zachary Renouf
}

# Source file -> (expected weapon, expected gender) as a check against the file contents
SOURCES = [
    ("2026_09_15_DatabaseMEUpdated.csv", "Epee", "M"),
    ("2026_09_15_DatabaseMSUpdated.csv", "Saber", "M"),
    ("2026_09_15_DatabaseWSUpdated.csv", "Saber", "F"),
]


def load_records(folder):
    records = []
    for fname, weapon, gender in SOURCES:
        df = pd.read_csv(Path(folder) / fname)
        for _, r in df.iterrows():
            row_weapon = str(r["Weapon"]).strip()
            row_gender = str(r["Gender"]).strip()
            if row_weapon != weapon or row_gender != gender:
                raise ValueError(
                    f"{fname}: row {r['ID']} has {row_weapon}/{row_gender}, "
                    f"expected {weapon}/{gender}"
                )
            records.append({
                "legacy_id": str(r["ID"]).strip(),
                "first": db.clean(r["First name"]),
                "last": db.clean(r["Last name"]),
                "gender": gender,
                "club": db.clean(r["Club"]),
                "weapon": weapon,
                "points": int(r["Points"]),
                "source": fname,
            })
    return records


def load_opening_balance(conn, records):
    comp_id = db.add_competition(
        conn,
        name="Opening balance (seeding files 2026-09-15)",
        kind="opening",
        event_date=OPENING_DATE,
        source_file=", ".join(s[0] for s in SOURCES),
    )
    log = []
    for r in records:
        # Confirmed same person under different names: attach to the existing record
        if r["legacy_id"] in KNOWN_SAME:
            target = KNOWN_SAME[r["legacy_id"]]
            row = conn.execute(
                "SELECT id FROM fencers WHERE legacy_id = ?", (target,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Known-same target {target} not loaded yet")
            fid = row["id"]
            conn.execute(
                "UPDATE fencers SET legacy_id = legacy_id || ';' || ? WHERE id = ?",
                (r["legacy_id"], fid),
            )
            db.add_alias(conn, fid, r["last"], r["first"])
            log.append(f"MERGED (confirmed) {r['legacy_id']} {r['first']} {r['last']} into {fid} ({target})")
            db.add_result(
                conn, comp_id, fid, r["weapon"], r["gender"],
                placing=None, points=r["points"], note=f"opening {r['legacy_id']}",
            )
            continue

        matches = db.find_fencers_by_name(conn, r["last"], r["first"])
        fid = None
        if matches:
            fid = matches[0]
            existing = conn.execute(
                "SELECT gender, club, legacy_id FROM fencers WHERE id = ?", (fid,)
            ).fetchone()
            if existing["gender"] != r["gender"]:
                log.append(f"NOT MERGED, different gender: {r['legacy_id']} {r['first']} {r['last']}")
                fid = None
            else:
                conn.execute(
                    "UPDATE fencers SET legacy_id = legacy_id || ';' || ? WHERE id = ?",
                    (r["legacy_id"], fid),
                )
                note = f"MERGED {r['legacy_id']} ({r['source']}) into {fid} [{r['first']} {r['last']}]"
                if existing["club"] and existing["club"] != r["club"]:
                    note += f"  club differs: '{existing['club']}' vs '{r['club']}'"
                log.append(note)
        if fid is None:
            fid = db.add_fencer(conn, r["first"], r["last"], r["gender"], r["club"], r["legacy_id"])
        db.add_result(
            conn, comp_id, fid, r["weapon"], r["gender"],
            placing=None, points=r["points"], note=f"opening {r['legacy_id']}",
        )
    conn.commit()
    return log


def check_totals(conn, records):
    """Points in the database must equal the sum of the source files, per weapon and gender."""
    problems = []
    for fname, weapon, gender in SOURCES:
        expected = sum(r["points"] for r in records if r["source"] == fname)
        actual = conn.execute(
            "SELECT COALESCE(SUM(points), 0) AS t FROM results WHERE weapon = ? AND gender = ?",
            (weapon, gender),
        ).fetchone()["t"]
        status = "OK" if expected == actual else "MISMATCH"
        print(f"  {fname}: source {expected}, database {actual}  [{status}]")
        if expected != actual:
            problems.append(fname)
    return problems


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    folder, db_path = Path(sys.argv[1]), Path(sys.argv[2])
    if db_path.exists():
        sys.exit(f"Refusing to overwrite existing database: {db_path}")

    records = load_records(folder)
    conn = db.connect(db_path)
    db.init_db(conn)
    log = load_opening_balance(conn, records)

    print(f"Fencers in database: {conn.execute('SELECT COUNT(*) FROM fencers').fetchone()[0]}")
    print(f"Result rows:         {conn.execute('SELECT COUNT(*) FROM results').fetchone()[0]}")
    print("\nMerges and conflicts to check:")
    for line in log or ["  none"]:
        print("  " + line)
    print("\nTotals check:")
    problems = check_totals(conn, records)
    conn.close()
    if problems:
        sys.exit("Totals do not match. Delete the database and investigate.")
    print("\nStage 1 complete.")


if __name__ == "__main__":
    main()
