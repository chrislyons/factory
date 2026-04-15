#!/usr/bin/env python3
import urllib.request, json

url = 'https://gamma-api.polymarket.com/events?limit=5&active=true&closed=false'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
with urllib.request.urlopen(req, timeout=30) as response:
    data = json.loads(response.read().decode())
    # Print first event structure
    print(json.dumps(data[0], indent=2))