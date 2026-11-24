# Changelog

## Stage 1: database and opening balance

### New files
- `SPEC.md`: agreed specification, decisions, data model, stages and open items.
- `sifl_db.py`: database layer. Schema (fencers, fencer_names, competitions, results, resets), connection, timestamped backup using SQLite's backup API, name matching key, fencer and result helpers, and `current_points()` (points per weapon after the latest reset).
- `stage1_opening_balance.py`: creates `sifl.db` from the three current seeding files. Applies the confirmed Renouf merge (ME_049 into ME_006). Checks that database totals equal the source file totals. Refuses to overwrite an existing database.
- `sifl.db`: the database produced by stage 1 from your files (81 fencers, 82 result rows).

### Known gaps (to resolve later)
- Foil and Women's Epee have no opening points (no source file).
- Opening-balance name matching uses exact names. The confirmed merge is the only one applied.
