#!/usr/bin/env python3
"""
count_films.py - count films by ORIGINAL language on Wikidata.

Languages: English, Hindi, Tamil, Telugu, Malayalam, Kannada.
Counts are "films catalogued on Wikidata", not every film ever made.
A film with two original languages (e.g. a Tamil-Telugu bilingual) is counted
in both language rows, but only once in the totals.

Usage: python3 count_films.py      (needs: pip3 install requests)
Writes film_counts.json next to this script.
"""
import json
import os
import time

import requests

SPARQL = "https://query.wikidata.org/sparql"
HEADERS = {"User-Agent": "KannadaDubScraper/1.0 (personal research script; python-requests)"}
LANGS = {  # Wikidata item IDs for each language
    "English": "Q1860", "Hindi": "Q1568", "Tamil": "Q5885",
    "Telugu": "Q8097", "Malayalam": "Q36236", "Kannada": "Q33673",
}


def count(values_clause):
    q = f"""SELECT (COUNT(DISTINCT ?film) AS ?n) WHERE {{
      VALUES ?lang {{ {values_clause} }}
      ?film wdt:P31 wd:Q11424 ; wdt:P364 ?lang .
    }}"""
    for attempt in range(4):
        r = requests.get(SPARQL, params={"query": q, "format": "json"}, headers=HEADERS, timeout=300)
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(10 * (attempt + 1))
            continue
        r.raise_for_status()
        return int(r.json()["results"]["bindings"][0]["n"]["value"])
    raise RuntimeError("Wikidata kept failing; try again in a few minutes")


def ids(names):
    return " ".join("wd:" + LANGS[n] for n in names)


results = {}
for name in LANGS:
    results[name] = count(ids([name]))
    print(f"{name:10} {results[name]:>8,}")
    time.sleep(2)

all_six = count(ids(LANGS))
without_kannada = count(ids([n for n in LANGS if n != "Kannada"]))
results["TOTAL (all six, each film once)"] = all_six
results["TOTAL excluding Kannada (each film once)"] = without_kannada
print(f"\nTotal, all six (distinct films):  {all_six:,}")
print(f"Total excluding Kannada:          {without_kannada:,}")

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "film_counts.json")
with open(out, "w") as fh:
    json.dump(results, fh, indent=2)
print(f"\nSaved {out}")
