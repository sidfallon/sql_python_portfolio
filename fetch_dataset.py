#!/usr/bin/env python3
# python fetch_dataset.py https://api.example.com/items -o items.csv
# python fetch_dataset.py https://api.example.com/items -o items.json --pages 5

"""Download a data set from an open JSON API endpoint.

Usage:
  python fetch_dataset.py URL -o data.csv            # or data.json
  python fetch_dataset.py URL -o data.csv --pages 5  # fetch ?page=1..5, stop early if empty
"""
import argparse
import csv
import json
import sys
import urllib.request


def get_json(url):
    req = urllib.request.Request(url, headers={
    "User-Agent": "fetch_dataset/1.0 (learning project)",
    "Accept": "application/json",
    })
        return json.load(resp)


def records_from(data):
    """Find the list of records in a response."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
        return [data]
    return [{"value": data}]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default="dataset.json")
    ap.add_argument("--pages", type=int, default=1, help="number of pages to fetch (uses ?page=N)")
    args = ap.parse_args()

    records = []
    for page in range(1, args.pages + 1):
        url = args.url
        if args.pages > 1:
            url += ("&" if "?" in url else "?") + f"page={page}"
        batch = records_from(get_json(url))
        if not batch:
            break
        records += batch

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        if args.output.endswith(".csv"):
            columns = list(dict.fromkeys(k for r in records for k in r))
            writer = csv.DictWriter(f, fieldnames=columns, restval="")
            writer.writeheader()
            writer.writerows({k: json.dumps(v) if isinstance(v, (dict, list)) else v
                              for k, v in r.items()} for r in records)
        else:
            json.dump(records, f, indent=2)

    print(f"Saved {len(records)} records to {args.output}")


if __name__ == "__main__":
    sys.exit(main())
