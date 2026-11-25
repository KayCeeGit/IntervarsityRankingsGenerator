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

## Full build (current)
- `sifl_db.py`: schema for fencers, names/aliases, competitions (kind, round, weapon, event gender), results, registrations, resets; backup via SQLite backup API; points from results since latest reset; merge, update, alias helpers.
- `sifl_logic.py`: name matching with suggestions; FencingTime results import with AFF points and ties; Google Form registrations (weapon x gender events, Mixed option, duplicate handling, review); seeding with standard ranking; competitor, seeding and fencer export files; delete, clear, reset, fencer detail/search.
- `sifl_app.py`: local web app (stdlib http.server, 127.0.0.1:8765). Backup before every write. Downloads for CSV files.
- `sifl_ui.html`: single-page UI with Rankings, Results, Registrations, Events, Fencers, Reset & history, Backup tabs.
- `test_sifl.py`: 44 checks on a fresh database built from the real files. All pass.
- `run_sifl.bat`, `ASSUMPTIONS.md`, `USER_GUIDE.md`.
- Stage 1 (`stage1_opening_balance.py`) unchanged: opening balance and totals check still pass.

## Revision: no manual event fields; all-weapons export
- Registrations: round name taken from the file name; event date is today. No manual round or date fields.
- Results: choose an existing event (created by the registration import). Manual new-event fields removed.
- Reset & history: *Export all rankings* gives a ZIP of six files (Epee, Foil, Saber; Men and Women).
- Tests: 47 checks, all pass.

## Bulk results import
- Results tab takes many FencingTime CSVs at once. Each file is matched to an event by name (weapon and Men/Women/Mixed words). The event can be changed per file.
- Nothing is saved unless every file is ready. Saving runs in one transaction, so a failure part-way saves nothing.
- Logic: `guess_event`, `bulk_preview`, `bulk_commit` in `sifl_logic.py`; `commit_results` gained `commit=False`.
- Routes: `/api/results/bulk_preview`, `/api/results/bulk_commit`.
- Tests: 58 checks, all pass.

## Workflow changes from the first test run
- Registrations: only review cases are shown. Matched and new fencers are handled automatically. The result page lists the files, with an expandable list of new fencers added.
- Registrations: weapon checkboxes removed from the UI (event type is inferred from the form).
- Results: files are matched to events by the fencers they contain (`match_by_entrants`), with the file name as a fallback. The match is shown on each file.
- Tests: 61 checks, all pass.
