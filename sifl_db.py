"""Database layer for the SIFL competition system (SQLite)."""
import re
import sqlite3
from datetime import date, datetime
from pathlib import Path

WEAPONS = ("Epee", "Foil", "Saber")
GENDERS = ("M", "F")
EVENT_GENDERS = ("M", "F", "X")  # X = mixed

SCHEMA = """
CREATE TABLE IF NOT EXISTS fencers (
    id          TEXT PRIMARY KEY,
    first_name  TEXT NOT NULL,
    last_name   TEXT NOT NULL,
    gender      TEXT NOT NULL CHECK (gender IN ('M', 'F')),
    club        TEXT,
    legacy_id   TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fencer_names (
    name_key    TEXT NOT NULL,
    fencer_id   TEXT NOT NULL REFERENCES fencers(id),
    PRIMARY KEY (name_key, fencer_id)
);

CREATE TABLE IF NOT EXISTS competitions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('opening', 'event')),
    event_date   TEXT,
    source_file  TEXT,
    created_at   TEXT NOT NULL,
    round_name   TEXT,
    weapon       TEXT,
    event_gender TEXT
);

CREATE TABLE IF NOT EXISTS results (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    competition_id  INTEGER NOT NULL REFERENCES competitions(id),
    fencer_id       TEXT NOT NULL REFERENCES fencers(id),
    weapon          TEXT NOT NULL CHECK (weapon IN ('Epee', 'Foil', 'Saber')),
    gender          TEXT NOT NULL CHECK (gender IN ('M', 'F')),
    placing         TEXT,
    points          INTEGER NOT NULL,
    note            TEXT
);

CREATE TABLE IF NOT EXISTS registrations (
    competition_id  INTEGER NOT NULL REFERENCES competitions(id),
    fencer_id       TEXT NOT NULL REFERENCES fencers(id),
    weapon          TEXT NOT NULL,
    PRIMARY KEY (competition_id, fencer_id)
);

CREATE TABLE IF NOT EXISTS resets (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    reset_date  TEXT NOT NULL,
    note        TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_results_fencer ON results (fencer_id, weapon);
CREATE INDEX IF NOT EXISTS idx_names_key ON fencer_names (name_key);
"""

# Columns added after the first version of the database. Older files get them on open.
MIGRATIONS = [
    ("competitions", "round_name", "TEXT"),
    ("competitions", "weapon", "TEXT"),
    ("competitions", "event_gender", "TEXT"),
]


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Create missing tables and add missing columns. Safe to run on every start."""
    conn.executescript(SCHEMA)
    for table, column, kind in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
    conn.commit()


def backup_db(path, backup_dir):
    """Copy the database to a timestamped file using SQLite's backup API."""
    path = Path(path)
    if not path.exists():
        return None
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    dest = backup_dir / f"{path.stem}_{stamp}.db"
    src = sqlite3.connect(str(path))
    dst = sqlite3.connect(str(dest))
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return dest


def clean(text):
    """Trim and collapse internal whitespace."""
    return re.sub(r"\s+", " ", str(text)).strip()


def name_key(last, first):
    """Lookup key for a name: 'lastname firstname', lower case."""
    return f"{clean(last).lower()} {clean(first).lower()}"


# ---------- fencers ----------

def next_fencer_id(conn):
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(id, 4) AS INTEGER)) AS m FROM fencers"
    ).fetchone()
    return f"ID_{(row['m'] or 0) + 1:03d}"


def get_fencer(conn, fid):
    return conn.execute("SELECT * FROM fencers WHERE id = ?", (fid,)).fetchone()


def add_fencer(conn, first, last, gender, club, legacy_id=None):
    if gender not in GENDERS:
        raise ValueError(f"gender must be M or F, got {gender!r}")
    fid = next_fencer_id(conn)
    conn.execute(
        "INSERT INTO fencers (id, first_name, last_name, gender, club, legacy_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fid, clean(first), clean(last), gender, clean(club or ""), legacy_id, now()),
    )
    add_alias(conn, fid, last, first)
    return fid


def add_alias(conn, fencer_id, last, first):
    conn.execute(
        "INSERT OR IGNORE INTO fencer_names (name_key, fencer_id) VALUES (?, ?)",
        (name_key(last, first), fencer_id),
    )


def fencer_aliases(conn, fid):
    return [r["name_key"] for r in conn.execute(
        "SELECT name_key FROM fencer_names WHERE fencer_id = ? ORDER BY name_key", (fid,))]


def find_fencers_by_name(conn, last, first):
    rows = conn.execute(
        "SELECT DISTINCT fencer_id FROM fencer_names WHERE name_key = ?",
        (name_key(last, first),),
    ).fetchall()
    return [r["fencer_id"] for r in rows]


def update_fencer(conn, fid, first, last, club):
    f = get_fencer(conn, fid)
    if f is None:
        raise ValueError("Fencer not found")
    new_first, new_last = clean(first), clean(last)
    if (new_first, new_last) != (f["first_name"], f["last_name"]):
        add_alias(conn, fid, f["last_name"], f["first_name"])  # keep the old name as an alias
    conn.execute(
        "UPDATE fencers SET first_name = ?, last_name = ?, club = ? WHERE id = ?",
        (new_first, new_last, clean(club or ""), fid),
    )
    add_alias(conn, fid, new_last, new_first)


def merge_fencers(conn, keep_id, drop_id):
    """Move everything from drop_id onto keep_id, then delete drop_id."""
    if keep_id == drop_id:
        raise ValueError("Choose two different fencers to merge")
    keep, drop = get_fencer(conn, keep_id), get_fencer(conn, drop_id)
    if keep is None or drop is None:
        raise ValueError("Fencer not found")
    if keep["gender"] != drop["gender"]:
        raise ValueError("Cannot merge fencers with different genders")
    conn.execute(
        "DELETE FROM registrations WHERE fencer_id = ? AND competition_id IN "
        "(SELECT competition_id FROM registrations WHERE fencer_id = ?)", (drop_id, keep_id))
    conn.execute("UPDATE registrations SET fencer_id = ? WHERE fencer_id = ?", (keep_id, drop_id))
    conn.execute("UPDATE results SET fencer_id = ? WHERE fencer_id = ?", (keep_id, drop_id))
    conn.execute("UPDATE OR IGNORE fencer_names SET fencer_id = ? WHERE fencer_id = ?", (keep_id, drop_id))
    conn.execute("DELETE FROM fencer_names WHERE fencer_id = ?", (drop_id,))
    legacy = ";".join(x for x in [keep["legacy_id"], drop["legacy_id"]] if x)
    club = keep["club"] or drop["club"]
    conn.execute("UPDATE fencers SET legacy_id = ?, club = ? WHERE id = ?", (legacy, club, keep_id))
    conn.execute("DELETE FROM fencers WHERE id = ?", (drop_id,))


# ---------- competitions and results ----------

def add_competition(conn, name, kind, event_date, source_file=None,
                    weapon=None, event_gender=None, round_name=None):
    cur = conn.execute(
        "INSERT INTO competitions (name, kind, event_date, source_file, created_at, "
        "round_name, weapon, event_gender) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (name, kind, event_date, source_file, now(), round_name, weapon, event_gender),
    )
    return cur.lastrowid


def get_competition(conn, cid):
    return conn.execute("SELECT * FROM competitions WHERE id = ?", (cid,)).fetchone()


def list_competitions(conn):
    return conn.execute("""
        SELECT c.*,
               (SELECT COUNT(*) FROM registrations r WHERE r.competition_id = c.id) AS entrants,
               (SELECT COUNT(*) FROM results x WHERE x.competition_id = c.id) AS results_count
        FROM competitions c
        ORDER BY c.event_date, c.id
    """).fetchall()


def add_result(conn, competition_id, fencer_id, weapon, gender, placing, points, note=None):
    if weapon not in WEAPONS:
        raise ValueError(f"weapon must be one of {WEAPONS}, got {weapon!r}")
    conn.execute(
        "INSERT INTO results (competition_id, fencer_id, weapon, gender, placing, points, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (competition_id, fencer_id, weapon, gender, placing, points, note),
    )


def add_registration(conn, competition_id, fencer_id, weapon):
    conn.execute(
        "INSERT OR IGNORE INTO registrations (competition_id, fencer_id, weapon) VALUES (?, ?, ?)",
        (competition_id, fencer_id, weapon),
    )


def delete_competition(conn, cid):
    conn.execute("DELETE FROM results WHERE competition_id = ?", (cid,))
    conn.execute("DELETE FROM registrations WHERE competition_id = ?", (cid,))
    conn.execute("DELETE FROM competitions WHERE id = ?", (cid,))


def clear_results(conn, cid):
    return conn.execute("DELETE FROM results WHERE competition_id = ?", (cid,)).rowcount


# ---------- points, resets ----------

def latest_reset_date(conn):
    return conn.execute("SELECT MAX(reset_date) AS d FROM resets").fetchone()["d"]


def add_reset(conn, note=""):
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO resets (reset_date, note, created_at) VALUES (?, ?, ?)",
        (today, note, now()),
    )
    return today


def list_resets(conn):
    return conn.execute("SELECT * FROM resets ORDER BY reset_date DESC, id DESC").fetchall()


def current_points(conn, weapon, gender=None):
    """Points per fencer for one weapon, counting only events on or after the latest reset.

    Returns rows with id, first_name, last_name, gender, club, points (all fencers,
    zero if no points).
    """
    params = [weapon]
    gender_sql = ""
    if gender:
        gender_sql = "AND f.gender = ?"
        params.append(gender)
    sql = f"""
        SELECT f.id, f.first_name, f.last_name, f.gender, f.club,
               COALESCE(SUM(r.points), 0) AS points
        FROM fencers f
        LEFT JOIN results r
               ON r.fencer_id = f.id
              AND r.weapon = ?
              AND r.competition_id IN (
                    SELECT c.id FROM competitions c
                    WHERE c.event_date >= COALESCE(
                          (SELECT MAX(reset_date) FROM resets), '0000-00-00'))
        WHERE 1 = 1 {gender_sql}
        GROUP BY f.id
        ORDER BY points DESC, f.last_name, f.first_name
    """
    return conn.execute(sql, params).fetchall()


def points_map(conn, weapon, gender=None):
    return {r["id"]: r["points"] for r in current_points(conn, weapon, gender)}


def list_fencers(conn, q=""):
    """Fencers whose name, alias, club or ID contains q (all fencers if q is empty)."""
    q = clean(q).lower()
    rows = conn.execute("SELECT * FROM fencers ORDER BY last_name, first_name").fetchall()
    aliases = {}
    for r in conn.execute("SELECT fencer_id, name_key FROM fencer_names"):
        aliases.setdefault(r["fencer_id"], []).append(r["name_key"])
    out = []
    for f in rows:
        hay = " ".join([f["id"], f["first_name"], f["last_name"], f["club"] or ""]
                       + aliases.get(f["id"], [])).lower()
        if not q or q in hay:
            out.append(f)
    return out
