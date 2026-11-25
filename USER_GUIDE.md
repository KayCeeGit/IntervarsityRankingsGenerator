# SIFL Competition System: user guide

## Starting the app
Double-click `run_sifl.bat`. Your browser opens at http://127.0.0.1:8765. Keep the black window open while you work. Close it to stop the app.

Files live in the same folder:
- `sifl.db`: the database. Do not edit it by hand.
- `backups/`: a copy of the database before every change.
- `exports/`: the files the app creates (fencer import, competitor and seeding files), in a folder per round or event.

## Before a competition
1. **Registrations tab.** Pick the Google Form `.xlsx` file and click *Check registrations*. The round is named after the file and the event date is today.
2. Only people who need a decision are listed. Matched and new fencers are handled automatically.
3. Choose the fencer, create a new one, or skip each listed person, then click *Create events and files*.
4. The page shows the files created. Click *New fencers added* to see who was added.
5. Import the fencer file into FencingTime, then each event's competitor and seeding files.

## After a competition
1. Export results from FencingTime Live. Each file is called `eventResults (n).csv`, so keep the files as they are.
2. **Results tab.** Select all the CSVs at once. Each file is matched to its event by the competitors in it, and by the file name if that fails. Check the event shown on each file and change it if needed.
3. Click *Check files*, fix any red rows, then *Save all results*. Nothing is saved until every file is ready.

## Rankings
The Rankings tab shows points for one weapon, with an All / Men / Women filter. *Export CSV* saves the same list in seeding format.

## Fencers
Search by name, club or ID. Click a fencer to see points for each weapon, the history of results, and to edit the name or club, add another name (for names the database should treat as the same person), or merge a duplicate into this fencer.

## Events
Lists every event. *View* shows results and registrations. *Export files* writes the competitor and seeding files again. *Clear results* removes the results so the event can be imported again. *Delete* removes the event.

## Reset
Reset & history: *Reset all points* starts a new season for every weapon. Past results stay in history.

*Export all rankings* downloads one ZIP with six seeding-format CSVs: Epee, Foil and Saber, each for Men and Women.

## Backup
A backup is taken automatically before any change. *Back up now* makes an extra one.

## If something looks wrong
Restore from `backups/` by closing the app, copying a backup over `sifl.db`, and starting the app again. Ask before doing this.

## Old files
`Master_Database.xlsx`, `fencing_competition_system.py`, `fencing_registration_processor.py`, `main.py`, and the earlier CSVs and guides are superseded. Do not use them.
