#!/usr/bin/env python3

title = "Will Arsenal finish in the top 4 of the EPL 2025–26 standings?"
description = ""

title_lower = title.lower()
desc_lower = description.lower()
text = f"{title_lower} {desc_lower}"

print(f"Text: {text}")
print(f"'top 4' in text: {'top 4' in text}")

elite_teams = ['arsenal', 'manchester city', 'liverpool', 'real madrid', 'barcelona',
              'bayern', 'psg', 'juventus', 'inter', 'ac milan', 'napoli', 'atletico']

for team in elite_teams:
    if team in text:
        print(f"Found team: {team}")

if 'top 4' in text or 'top four' in text or 'champions league' in text:
    print("Matched top 4 condition")
    if any(team in text for team in elite_teams):
        print("Returning 0.80 (elite team)")
    else:
        print("Not elite team - returning 0.25")
else:
    print("Did not match top 4 condition")