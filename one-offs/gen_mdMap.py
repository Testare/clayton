import json

# Including leap day
days_in_month = [0, 31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]

master = [[] for _ in range(256)]

for month in range(1, 13):
    for day in range(1, days_in_month[month] + 1):
        index = (month * day) % 0x100
        master[index].append([month, day])

with open('mdMap.json', 'w') as f:
    json.dump(master, f)

print("mdMap.json created.")
