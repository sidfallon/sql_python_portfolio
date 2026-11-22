#!/usr/bin/env python3
# python fetch_dataset.py https://api.example.com/items -o items.csv
# python fetch_dataset.py https://api.example.com/items -o items.json --pages 5
# python fetch_dataset.py 'https://pokeapi.co/api/v2/pokemon?limit=100' -o pokemon.csv --follow-next --enrich

"""Download a data set from an open JSON API endpoint.

Usage:
  python fetch_dataset.py URL -o data.csv            # or data.json
  python fetch_dataset.py URL -o data.csv --pages 5  # fetch ?page=1..5, stop early if empty
  python fetch_dataset.py URL -o data.csv --follow-next
                                                     # follow the response's "next" link until it is null
  python fetch_dataset.py URL -o data.csv --enrich   # fetch each record's "url" and replace the
                                                     # record with the flattened detail
  python fetch_dataset.py URL -o data.csv --enrich --max 20   # enrich only the first 20 (for testing)
"""
import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request


def get_json(url, retries=3):
    req = urllib.request.Request(url, headers={
        "User-Agent": "fetch_dataset/1.0 (learning project)",
        "Accept": "application/json",
    })
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            # 4xx (except 429) will not get better by retrying
            if e.code < 500 and e.code != 429:
                raise
            err = e
        except (urllib.error.URLError, TimeoutError) as e:
            err = e
        if attempt == retries:
            raise err
        wait = 2 ** attempt
        print(f"  retry {attempt}/{retries - 1} in {wait}s ({err})", file=sys.stderr)
        time.sleep(wait)


def records_from(data):
    """Find the list of records in a response."""
    # Column-oriented payload (Open-Meteo): {"hourly": {"time": [...], "temperature_2m": [...]}}
    if isinstance(data, dict) and isinstance(data.get("hourly"), dict):
        cols = data["hourly"]
        keys = list(cols)
        return [dict(zip(keys, vals)) for vals in zip(*cols.values())]
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                return value
        return [data]
    return [{"value": data}]


# ---------------------------------------------------------------- enrichment

def flatten_generic(obj, prefix="", depth=3):
    """Flatten nested dicts into prefix_key columns. Lists of scalars are joined with '|';
    anything deeper than `depth` or any list of dicts is left as-is (the CSV writer JSON-encodes it)."""
    row = {}
    for key, value in obj.items():
        name = f"{prefix}{key}"
        if isinstance(value, dict) and depth > 0:
            row.update(flatten_generic(value, f"{name}_", depth - 1))
        elif isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
            row[name] = "|".join(str(v) for v in value)
        else:
            row[name] = value
    return row


def flatten_pokemon(p):
    row = {
        "id": p["id"],
        "name": p["name"],
        "height": p["height"],
        "weight": p["weight"],
        "base_experience": p["base_experience"],
        "types": "|".join(t["type"]["name"] for t in p["types"]),
        "abilities": "|".join(a["ability"]["name"] for a in p["abilities"]),
    }
    for s in p["stats"]:  # hp, attack, defense, special_attack, special_defense, speed
        row[s["stat"]["name"].replace("-", "_")] = s["base_stat"]
    return row


# (substring of the detail URL, flattener); first match wins, otherwise flatten_generic
FLATTENERS = [
    ("pokeapi.co/api/v2/pokemon/", flatten_pokemon),
]


def pick_flattener(url):
    for needle, fn in FLATTENERS:
        if needle in url:
            return fn
    return flatten_generic


def enrich(records, delay, maximum):
    """Replace each record that has a 'url' with the flattened JSON found at that url."""
    targets = records[:maximum] if maximum else records
    out = []
    for i, rec in enumerate(targets, 1):
        link = rec.get("url") if isinstance(rec, dict) else None
        if not isinstance(link, str) or not link.startswith("http"):
            print(f"  skipping record {i}: no 'url' field to enrich from", file=sys.stderr)
            out.append(rec)
            continue
        try:
            out.append(pick_flattener(link)(get_json(link)))
        except Exception as e:  # keep going; one bad record should not lose the rest
            print(f"  failed {link}: {e}", file=sys.stderr)
            out.append(rec)
        if i % 100 == 0:
            print(f"  enriched {i}/{len(targets)}", file=sys.stderr)
        time.sleep(delay)
    return out


# ---------------------------------------------------------------- fetching

def fetch_records(args):
    records = []
    if args.follow_next:
        url = args.url
        while url:
            data = get_json(url)
            records += records_from(data)
            url = data.get("next") if isinstance(data, dict) else None
            print(f"  fetched {len(records)} records so far", file=sys.stderr)
            if url:
                time.sleep(args.delay)
        if isinstance(data, dict) and isinstance(data.get("count"), int):
            print(f"  API reports {data['count']} total; fetched {len(records)}", file=sys.stderr)
        return records

    for page in range(1, args.pages + 1):
        url = args.url
        if args.pages > 1:
            url += ("&" if "?" in url else "?") + f"page={page}"
        batch = records_from(get_json(url))
        if not batch:
            break
        records += batch
    return records


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default="dataset.json")
    ap.add_argument("--pages", type=int, default=1, help="number of pages to fetch (uses ?page=N)")
    ap.add_argument("--follow-next", action="store_true",
                    help='follow the response\'s "next" URL until it is null (PokeAPI style)')
    ap.add_argument("--enrich", action="store_true",
                    help="fetch each record's 'url' and flatten the detail into the row")
    ap.add_argument("--max", type=int, default=0, metavar="N",
                    help="with --enrich, only enrich the first N records (0 = all)")
    ap.add_argument("--delay", type=float, default=0.1,
                    help="seconds to pause between requests (default 0.1)")
    args = ap.parse_args()

    records = fetch_records(args)
    if args.enrich:
        records = enrich(records, args.delay, args.max)

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
