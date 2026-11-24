# SIFL Competition System: Specification

## 1. Purpose
One program that keeps every fencer's weapon-specific points in a single SQLite database, builds the FencingTime import files for each event, and updates points from FencingTime results after each competition.

## 2. Confirmed decisions
| Topic | Decision |
|---|---|
| Storage | SQLite file `sifl.db`. Excel and CSV are import/export only |
| Platform | Windows. Run in the browser (Streamlit), packaged later as `.exe` |
| Users | Single user for now |
| Fencer ID | `ID_001`, `ID_002` ... Never reused. Old IDs kept as `legacy_id` for reference |
| Points | Per fencer, per weapon. Calculated from stored results, never kept as a running total |
| Results | One row per fencer per event. Each row stores its placing and points |
| Points scale | AFF: 1st 32, 2nd 26, 3rd 20, 5-8 14, 9-16 8, 17-32 4, 33-64 2, 65+ 1. Tied placings get the same points |
| Matching results to fencers | By name (`LASTNAME Firstname`), then confirmed on a review screen. Club is shown but does not decide a match |
| Name aliases | One fencer can have several names (e.g. `RENOUF Zach` and `RENOUF Zachary`). Merged fencers share one ID |
| New fencers | Exact matches are automatic. New or uncertain names go to review before being added |
| Duplicate registrations | Keep the latest entry. Flag for review if the two entries differ |
| Mixed gender events | Chosen per weapon at event creation |
| Reset | Resets all weapons together. Results before the reset date stay in history |
| Seeding | Points after the latest reset. Ties in a fixed order (alphabetical by last name, then first name) so re-running gives the same file |
| Seeding file | Identical format to `2026_09_15_DatabaseMEUpdated.csv`: `ID, First name, Last name, Weapon, Gender, Ranking, Points, Club`. Ranking is standard competition ranking (tied share a rank, the next rank is skipped) |
| Weapon spelling in files | `Epee`, `Foil`, `Saber` (matches the existing seeding files) |
| Gender codes | `M`, `F` |
| Fencer import (FencingTime) | Only fencers in that competition, from its registrations. Columns: ID, First name, Last name, Club, Gender, Weapon, Ranking, Points (the wizard maps the columns) |
| Competitor import | One CSV per event, built from that event's registrations |
| Backups | Timestamped copy of `sifl.db` before every import and every reset |

## 3. Data model
- `fencers`: id, first name, last name, gender, club, legacy_id, created_at
- `fencer_names`: name key (`lastname firstname`, lower case), fencer id. Several keys can point to one fencer
- `competitions`: id, name, kind (`opening` or `event`), event date, source file
- `results`: id, competition id, fencer id, weapon, gender, placing, points, note
- `resets`: id, reset date, note
- `registrations` (stage 3): competition id, fencer id, weapon, gender

Points for a fencer and weapon = sum of `results.points` where the competition date is on or after the latest reset date.

## 4. Pipeline
1. **Setup (once):** create `sifl.db` and load opening points from the three current seeding files. Merge duplicates (Renouf, Zach/Zachary, and any others the report shows).
2. **Registration (before each competition):** read the form. Dedupe. Build the event list (weapon x gender, with mixed option). Match fencers. Review new fencers. Write registrations. Export the fencer CSV and each event's competitor CSV and seeding CSV.
3. **Results (after each competition):** read FencingTime `eventResults.csv`. Ask for weapon and gender. Match fencers (review uncertain names). Calculate points from placing, with ties. Save results. Back up first.
4. **Rankings:** view current points, export, reset, and view history.
5. **Fencer management:** edit names, add aliases, merge duplicates.

## 5. Stages
| Stage | Scope | Status |
|---|---|---|
| 1 | Database, backup, opening balance import | Building now |
| 2 | Results import: matching, points, review, save | Next |
| 3 | Registration import: events, matching, fencer CSV, competitor CSVs | |
| 4 | Seeding CSVs, rankings view, export, reset, history | |
| 5 | Browser UI (Streamlit), Windows `.exe` packaging | |

Each stage is tested on the real files before the next one starts.

## 6. Open items
- **Foil and Women's Epee opening points:** no current file holds these, so they start at 0. Confirm if you have a foil or women's epee ranking file.
- **Renouf merge:** ME_006 (Zachary) and ME_049 (Zach) become one fencer. Points are combined (14 + 8 = 22 Epee points). The merged fencer keeps the record of ME_006.
