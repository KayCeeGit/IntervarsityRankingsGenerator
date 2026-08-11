import csv
import pandas as pd

RESULTS = 'sifl3\siflWSSifl4.csv' #The csv downloaded straight from Fencing Time. No modifications needed
RANKINGS = 'WomensSabreRankings.csv' #The csv that contains the current rankings
BACKUP = 'WomensSabreRankingsBackup.csv'#Just make a backup since the rankings will get overwritten, advise having them locally or on a drive.

pointsDict = { #Based off the AFF points distribution
    "1": 32,
    "2": 26,
    "3": 20,
    "5-8": 14,
    "9-16": 8,
    "17-32": 4,
    "33-64": 2,
    "65+": 1,
}

def getPoints(placement, currentPoints = 0):
    if placement == "3T":
        placement = "3"
    elif placement == "26T":
            placement = "26"
    elif placement == "27T":
            placement = "27"
    elif placement == "28T":
            placement = "28"
    elif placement == "29T":
            placement = "29"
    placement = int(placement)
    if placement >=5 and placement <= 8:
        placement = "5-8"
    elif placement >= 9 and placement <= 16:
        placement = "9-16"
    elif placement >= 17 and placement <= 32:
        placement = "17-32"
    elif placement >= 33 and placement <= 64:
        placement = "33-64"
    elif placement >= 65:
        placement = "65+"
    placement = str(placement)

    return currentPoints + pointsDict[placement]
    
with open(RESULTS, newline='', encoding='utf-8') as resultsF:
    results = list(csv.reader(resultsF, delimiter=','))

with open(RANKINGS, newline='', encoding='utf-8', mode='r+') as rankingsF:
    rankings = list(csv.reader(rankingsF, delimiter=','))

output = list()  
found = False #prevents double entries

#this is the badboy that does the work, basically we loop through the results and check if the fencer is already in the rankings, if they are we add the points to their current points, if not we just add the points from this tournament.
for(resultsIndex, resultRow) in enumerate(results[1:]):
    for(rankingIndex, rankingRow) in enumerate(rankings[:-1]):
        if(resultRow[0] != "Place"):
            if(resultRow[1] == rankingRow[1]):
                found = True
                points = getPoints(placement=resultRow[0], currentPoints=int(rankingRow[3]))
                output.append((resultRow[1], resultRow[2], points))
    if not found:
        points = getPoints(placement=resultRow[0])
        output.append((resultRow[1], resultRow[2], points))
    found = False
        
df = pd.DataFrame(output)
df.sort_values(by=[2],inplace=True, ascending=False)
df.rename(columns={0: "Name", 1 : "Club", 2: "Points"}, inplace=True)

oldRankings = pd.read_csv(RANKINGS, names=["Ranking", "Name", "Club", "Points"])



newRankings = pd.concat([oldRankings, df])

#Here is a series of grotesque and frankenstienian code from the depths of the internet and my brain to get the rankings in order on the dataframe.
finalRankings = newRankings.sort_values(by=["Points"], ascending=False)
finalRankings = finalRankings.drop_duplicates(subset=["Name"], keep="first").reset_index(drop=True)
finalRankings["Ranking"] = finalRankings["Points"].apply(lambda score: finalRankings.index[finalRankings["Points"] == score].tolist())
finalRankings["Ranking"] = finalRankings["Ranking"].apply(lambda x: [str(i+1) for i in x])
finalRankings["Ranking"]= finalRankings["Ranking"].apply(lambda x: x[0:1] if x else x)
finalRankings["Ranking"] = finalRankings["Ranking"].astype(str).str.replace("[","").str.replace("]","").str.replace("'","")

print(finalRankings) 

with open(RANKINGS, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(finalRankings.values.tolist())
        
with open(BACKUP, 'w', newline='') as f:
    writer = csv.writer(f)
    writer.writerows(oldRankings.values.tolist())