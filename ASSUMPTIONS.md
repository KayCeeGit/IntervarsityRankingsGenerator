# SIFL: assumptions to revisit

Each item says what the system assumes, where it lives in the code, and what would change it.

## Points and results
1. **AFF bands:** 1st 32, 2nd 26, 3rd 20, 5-8 14, 9-16 8, 17-32 4, 33-64 2, 65+ 1. There is no 4th place in the scale. FencingTime records both semi-final losers as 3T, so a bare `4` is treated as an error and the import is blocked. Check `PLACE_BANDS` in `sifl_logic.py`.
2. **Ties:** any placing with a trailing T (3T, 5T, 26T) gets the points of its number. Ties are not reduced to a band of their own.
3. **Opening points:** Foil and Women's Epee start at 0 because no current file holds them.
4. **Renouf:** ME_049 (Zach) is merged into ME_006 (Zachary) by a fixed rule in `stage1_opening_balance.py` (`KNOWN_SAME`).
5. **Results import:** FencingTime's `Name` column is split at the first space into last name and first name (`LASTNAME Firstname`). Multi-word surnames will be wrong if FencingTime writes them differently.
6. **Results club column:** the club is shown in review but does not decide a match.
7. **Results already imported:** an event that already has results cannot be imported again. Clear the results first (Events tab) if a re-import is needed.

## Matching and fencers
8. **Exact name match** (same last and first name key) is matched automatically unless the gender on file conflicts with the event. Anything else goes to review.
9. **Name key:** lower-case "lastname firstname", spaces collapsed. "Zach" and "Zachary" are different keys until merged by hand.
10. **Fuzzy suggestions** use difflib with a 0.6 threshold and show the top 3. They are never applied automatically.
11. **New fencer IDs** are `ID_001`, `ID_002`, ... taken from the highest number in use. Old IDs are kept in `legacy_id`.
12. **Gender of a new fencer** comes from the registration form, or from the choice made in review. Results events that are Mixed need a gender chosen per new fencer.
13. **Merging** only allowed between fencers of the same gender. Points and names move to the kept ID.

## Registrations
14. **Events:** one event per weapon and gender from the form. "Epee and Foil" creates entries for both weapons. A weapon can be run as Mixed by ticking it on the Registrations tab.
15. **Duplicate entries:** the latest entry per person and weapon is kept (by timestamp, then row). If the two entries differ in gender or club, the person is flagged for review.
16. **Gender in the form** decides which Men's or Women's event a person enters. A person with a fencer record of a different gender is flagged.
17. **Round name:** one round can be imported once. The round name also names the export folder.
18. **Late changes on the day:** a round can only be imported once. A late entry needs a second round import with the extra entries. There is no screen yet to add or remove one registration in an existing event. This is a gap to close.

## Seeding and rankings
19. **Points for seeding and rankings** are the sum of results dated on or after the latest reset date, for the weapon in question.
20. **Ranking:** standard competition ranking. Tied points share a rank and the next rank is skipped (1, 1, 3).
21. **Seeding order** of tied fencers: alphabetical by last name, then first name, so re-running gives the same file.
22. **Seeding file format:** identical headers to `2026_09_15_DatabaseMEUpdated.csv`: ID, First name, Last name, Weapon, Gender, Ranking, Points, Club. Weapon names are `Epee`, `Foil`, `Saber`.
23. **Competitor file:** one per event, columns ID, First name, Last name, Club, Gender. Columns and order are an assumption about the FencingTime competitor wizard; check against the guide (page 76).
24. **Fencer import file (`FencingTime_fencers.csv`):** one row per fencer with separate Epee Points, Foil Points, Saber Points columns. This is an assumption about how FencingTime's ranking/fencer import reads points. It has not been tested in FencingTime. Check it against page 45 and page 84 of the guide before relying on it.
25. **Files are UTF-8 without BOM,** comma separated.

## Resets and history
26. **Reset** zeroes points for all weapons together. The reset date is today's date (the machine's clock). Results before the reset stay in history.
27. **Reset date vs event date:** an event counts towards points if its event date is on or after the latest reset date, so an event dated before a reset but entered after it does not count. Enter the real event date.

## Backups and safety
28. **Backup** is taken before every import, reset, delete, clear, edit, alias and merge, into the `backups` folder, using SQLite's backup API. Backups are never deleted by the app.
29. **Single user.** Writes are serialised with a lock inside one running app. Two copies of the app on the same database are not supported.

## Environment
30. **Local only:** the server binds to 127.0.0.1 port 8765. Nothing else on the network can reach it.
31. **Dependencies:** Python 3.10 or later, pandas and openpyxl. The web app uses only the standard library.
32. **Excel files** are read with pandas (openpyxl). The registration file must have the Google Form headers ("Timestamp", "First Name", "Last Name", "Which event...", "Will you be fencing...", "Who would you like to represent?").
33. **Windows packaging** (`.exe`) is not done yet. `run_sifl.bat` runs the app from source.
