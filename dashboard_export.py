#!/usr/bin/env python3
"""
dashboard_export.py - feed dashboard.html with the scraper's latest results.

Reads sweep_progress.json (written by kannada_dubs.py every 1,000 pages) and,
once the sweep has finished, kannada_dubs.csv. Writes dubs_data.js, which
dashboard.html reloads every 60 seconds.

Usage:
  python3 dashboard_export.py           # export once
  python3 dashboard_export.py --watch   # re-export every 60 s until Ctrl+C
"""
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
PROGRESS = os.path.join(HERE, "sweep_progress.json")
FINAL_CSV = os.path.join(HERE, "kannada_dubs.csv")
OUT = os.path.join(HERE, "dubs_data.js")
SACNILK_CSV = os.path.join(HERE, "sacnilk_dubs.csv")     # optional second source
PRESS_CSV = os.path.join(HERE, "press_dubs.csv")         # hand-verified news reports
DETAILS = os.path.join(HERE, "details_cache.json")        # infobox details from fill_details.py
VERIFY = os.path.join(HERE, "verification.csv")           # hand-checked decisions (confirm / unconfirm / details)

# Only these original languages are shown, in this order (dashboard uses the same order).
LANGUAGES = ["English", "Hindi", "Telugu", "Tamil", "Malayalam"]

# Wording that means the dub was announced, not confirmed as released.
UNCONFIRMED = re.compile(r"\b(plan(?:s|ned)?|planning|will (?:also )?(?:be|begin|start|stream|release|premiere|arrive|have)|"
                         r"to be dubbed|expected|reportedly|proposed|announced|scheduled|set for|set to|is being|"
                         r"slated|upcoming|awaiting)\b", re.I)


def load():
    films, checked, total, finished = {}, 0, 0, False
    if os.path.exists(PROGRESS):
        try:
            with open(PROGRESS, encoding="utf-8") as fh:
                state = json.load(fh)
            films = state.get("films", {})
            total = len(state.get("titles") or [])
            checked = min(state.get("next", 0), total)
        except (json.JSONDecodeError, OSError):
            return None                      # scraper mid-write; try next round
    if os.path.exists(FINAL_CSV) and os.path.getmtime(FINAL_CSV) >= os.path.getmtime(PROGRESS if os.path.exists(PROGRESS) else FINAL_CSV):
        with open(FINAL_CSV, encoding="utf-8") as fh:
            films = {r["title"]: r for r in csv.DictReader(fh)}
        finished = True
        checked = total or checked
    return films, checked, total, finished


# ---------------------------------------------------------------- de-duplication
# The same film can arrive from Wikipedia ("Avatar: The Way of Water"),
# Wikidata (label) and Sacnilk (its own spelling). Rows are merged when their
# normalised titles match and their years are within one year of each other
# (Indian release dates often fall in the next calendar year), or a year is missing.
RANK = {"dub": 0, "release": 1, "press": 2, "sacnilk": 3, "wikidata": 4}


def strip_accents(t):
    t = unicodedata.normalize("NFKD", t or "")                  # "Brahmāstra" -> "Brahmastra"
    return "".join(c for c in t if not unicodedata.combining(c))


def norm_title(t):
    t = re.sub(r"\s*\((?:\d{4} )?(?:[\w-]+ )*film\)$", "", strip_accents(t), flags=re.I)  # "X (2015 film)" -> "X"
    t = t.lower().replace("&", " and ")
    t = re.sub(r"^(the|a|an) ", "", t)
    return re.sub(r"[^0-9a-z\u0c80-\u0cff]+", "", t)


def words(t):
    """Title words ignoring order and filler: "Pushpa: The Rule - Part 2" == "Pushpa 2: The Rule"."""
    t = re.sub(r"\s*\([^)]*film\)$", "", strip_accents(t), flags=re.I).lower().replace("&", " and ")
    return frozenset(re.findall(r"[0-9a-z]+", t)) - {"the", "a", "an", "part"}


def main_title(t):
    return norm_title(re.split(r"[:–—]", t or "", maxsplit=1)[0])


def year_ok(a, b):
    return not a or not b or abs(int(a) - int(b)) <= 1


def same_film(a, b):
    if a["key"] == b["key"] or a["words"] == b["words"]:
        return year_ok(a["year"], b["year"])
    # "Akhanda 2" vs "Akhanda 2: Thaandavam": same main title, same year, same language.
    # Exact year only, so "Dhurandhar" (2025) and "Dhurandhar: The Revenge" (2026) stay apart.
    return (a["main"] == b["main"] and a["year"] and a["year"] == b["year"]
            and a["lang"].lower() == b["lang"].lower() and ":" in a["title"] + b["title"])


def dedupe(rows):
    merged = []                                   # list of (key, row)
    for r in sorted(rows, key=lambda r: RANK.get(r["kind"], 9)):   # best evidence first
        r["key"], r["words"], r["main"] = norm_title(r["title"]), words(r["title"]), main_title(r["title"])
        key = r["key"]
        for k, m in merged:
            if same_film(m, r):
                for field in ("year", "director", "starring", "langs"):
                    m[field] = m[field] or r[field]
                for src in r["sources"]:
                    if src["name"] not in [x["name"] for x in m["sources"]]:
                        m["sources"].append(src)
                break
        else:
            merged.append((key, r))
    # A Sacnilk-only row whose title matches a listed film from a different year
    # is often an Indian re-release (Sacnilk dates "Avatar" to its 2022 re-release).
    # It can also be a different film with the same name, so flag it, don't drop it.
    for key, r in merged:
        if r["kind"] == "sacnilk":
            twin = next((m for k, m in merged if k == key and m is not r), None)
            if twin:
                r["maybe_rerelease_of"] = twin["year"] or "an earlier"
    out = []
    for _, r in merged:
        for tmp in ("key", "words", "main"):
            r.pop(tmp, None)
        out.append(r)
    return out


def fill_details(rows):
    """Fill only empty fields, from infobox data that fill_details.py confirmed."""
    if not os.path.exists(DETAILS):
        return
    with open(DETAILS, encoding="utf-8") as fh:
        cache = json.load(fh)
    by_key = {}
    for k, v in cache.items():
        t, _, y = k.rpartition("|")
        by_key.setdefault(t, []).append((y, v))
    for r in rows:
        for y, v in by_key.get(norm_title(r["title"]), []):
            if year_ok(y, r["year"]):
                for field in ("year", "director", "starring", "langs"):
                    r[field] = r[field] or v.get(field, "")
                if "Wikipedia" not in [x["name"] for x in r["sources"]]:
                    r["sources"].append({"name": "Wikipedia", "url": v["url"]})
                break


def apply_verification(rows):
    """verification.csv: confirmed -> sourced evidence, unconfirmed -> flagged, exclude -> removed, details fill gaps."""
    if not os.path.exists(VERIFY):
        return
    with open(VERIFY, encoding="utf-8") as fh:
        checks = list(csv.DictReader(fh))
    for v in checks:
        key = norm_title(v["title"])
        for r in rows:
            if norm_title(r["title"]) != key or not year_ok(v["year"], r["year"]):
                continue
            if v["status"] == "confirmed":
                r["unconfirmed"] = False
                r["evidence"] = v["evidence"] or r["evidence"]
                if v["outlet"] not in [x["name"] for x in r["sources"]]:
                    r["sources"].insert(0, {"name": v["outlet"], "url": v["source"]})
            elif v["status"] == "unconfirmed":
                r["unconfirmed"] = True
            elif v["status"] == "exclude":            # listed by mistake: drop it everywhere
                r["exclude"] = True
            for field in ("director", "starring"):
                r[field] = r[field] or v[field]


def sacnilk_rows():
    if not os.path.exists(SACNILK_CSV):
        return []
    with open(SACNILK_CSV, encoding="utf-8") as fh:
        return [{
            "title": f.get("title", ""), "year": f.get("year", ""),
            "lang": f.get("original_language", "") or "Unknown", "langs": "",
            "director": f.get("director", ""), "starring": f.get("starring", ""),
            "evidence": f.get("evidence", ""), "source": f.get("source", ""),
            "unconfirmed": False, "kind": "sacnilk",
            "sources": [{"name": "Sacnilk", "url": f.get("source", "")}],
        } for f in csv.DictReader(fh)]


def press_rows():
    if not os.path.exists(PRESS_CSV):
        return []
    with open(PRESS_CSV, encoding="utf-8") as fh:
        return [{
            "title": f["title"], "year": f["year"], "lang": f["original_language"], "langs": "",
            "director": "", "starring": "", "evidence": f["evidence"], "source": f["source"],
            "unconfirmed": False, "kind": "press", "release_type": f.get("release_type", ""),
            "sources": [{"name": f["outlet"], "url": f["source"]}],
        } for f in csv.DictReader(fh)]


def normalise_lang(name):
    """'tamil' / 'Tamil language' -> 'Tamil'; anything outside LANGUAGES -> None."""
    n = re.sub(r"\s*language$", "", (name or "").strip(), flags=re.I).title()
    return n if n in LANGUAGES else None


def build_rows():
    data = load()
    if data is None:
        return None
    films, checked, total, finished = data
    rows = []
    for f in films.values():
        kind = f.get("evidence_type") or "dub"
        rows.append({
            "title": f.get("title", ""),
            "year": f.get("year", ""),
            "lang": f.get("original_language", "") or "Unknown",
            "langs": f.get("all_original_languages", ""),
            "director": f.get("director", ""),
            "starring": f.get("starring", ""),
            "evidence": f.get("evidence", ""),
            "source": f.get("source", ""),
            "unconfirmed": bool(UNCONFIRMED.search(f.get("evidence", ""))),
            "kind": kind,
            "sources": [{"name": "Wikidata" if kind == "wikidata" else "Wikipedia",
                         "url": f.get("source", "")}],
        })
    rows = dedupe(rows + sacnilk_rows() + press_rows())
    fill_details(rows)
    apply_verification(rows)
    kept = []
    for r in rows:
        if r.pop("exclude", False):
            continue
        lang = normalise_lang(r["lang"])
        if lang:                                   # drop Odia, Punjabi, Bengali, mixed values, etc.
            r["lang"] = lang
            kept.append(r)
    rows = kept
    return rows, checked, total, finished


def export():
    built = build_rows()
    if built is None:
        return
    rows, checked, total, finished = built
    payload = {
        "updated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "checked": checked, "total": total, "finished": finished, "films": rows,
    }
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("window.DUBS_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    os.replace(tmp, OUT)
    print(f"{payload['updated']}  {len(rows)} films, {checked:,}/{total:,} pages checked", flush=True)


if __name__ == "__main__":
    export()
    if "--watch" in sys.argv:
        try:
            while True:
                time.sleep(60)
                export()
        except KeyboardInterrupt:
            pass
