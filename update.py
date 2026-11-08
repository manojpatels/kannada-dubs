"""Weekly check for new films dubbed into Kannada. Run by GitHub Actions (or by hand).

    python3 update.py

1. Wikipedia: only articles edited since the last run, found with the same search
   phrases as the full scraper, sorted newest-edit first. New matches are added to
   kannada_dubs.csv automatically (same rules, so announced dubs stay flagged).
2. Streaming news: Google News RSS for Kannada-version headlines. These are NOT added
   automatically; headlines don't reliably name the film, so they go to review_new.md
   for a person to check and copy into press_dubs.csv.

Writes review_new.md (empty when nothing new) and remembers what it has seen in
update_state.json, so each item is reported once.
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import kannada_dubs as kd

STATE = "update_state.json"
REVIEW = "review_new.md"
CSV_PATH = "kannada_dubs.csv"
FIELDS = ["original_language", "title", "year", "director", "starring",
          "all_original_languages", "evidence_type", "evidence", "source"]
NEWS_QUERIES = [
    '"Kannada dubbed"', '"in Kannada" streaming OTT', '"Kannada version" OTT',
    'Kannada audio Netflix OR "Prime Video" OR JioHotstar OR ZEE5 OR SonyLIV',
]
NEWS_MUST = re.compile(r"\bKannada\b", re.I)
NEWS_ANY = re.compile(r"\b(stream\w*|OTT|dubbed|dub|Netflix|Prime Video|JioHotstar|Hotstar|ZEE5|SonyLIV|Sun NXT|aha)\b", re.I)


def load_state():
    if os.path.exists(STATE):
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    # first run: look back two weeks
    return {"last_wiki": (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "seen_news": []}


def recently_edited(since):
    """Titles matching any search phrase whose last edit is newer than `since`."""
    titles = set()
    for phrase in kd.SEARCH_PHRASES + kd.MENTION_QUERIES:
        offset = 0
        while True:
            data = kd.api_get({"action": "query", "list": "search", "srsearch": phrase, "srnamespace": 0,
                               "srlimit": 100, "sroffset": offset, "srprop": "timestamp",
                               "srsort": "last_edit_desc", "format": "json"})
            hits = data["query"]["search"]
            fresh = [h["title"] for h in hits if h["timestamp"] > since]
            titles.update(fresh)
            if len(fresh) < len(hits) or "continue" not in data:
                break                                        # reached pages older than the last run
            offset = data["continue"]["sroffset"]
        time.sleep(0.2)
    return sorted(titles)


def wikipedia(state):
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(CSV_PATH, encoding="utf-8") as fh:
        films = {r["title"]: r for r in csv.DictReader(fh)}
    titles = recently_edited(state["last_wiki"])
    added, changed = [], []
    for _, pages in kd.fetch_batches(titles):
        for title, text in pages:
            rec = kd.check_page(title, text)
            if not rec:
                continue
            if title not in films:
                added.append(rec)
            elif films[title].get("evidence") != rec["evidence"]:
                changed.append(rec)
            films[title] = rec
    rows = sorted(films.values(), key=lambda f: (f["original_language"], f["year"], f["title"]))
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    state["last_wiki"] = started
    print(f"Wikipedia: {len(titles)} edited pages checked, {len(added)} new films, {len(changed)} updated")
    return added, changed


def news(state):
    seen = set(state["seen_news"])
    found = []
    for q in NEWS_QUERIES:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:7d")
               + "&hl=en-IN&gl=IN&ceid=IN:en")
        try:
            r = kd.session.get(url, timeout=30)
            r.raise_for_status()
            items = ET.fromstring(r.content).iter("item")
        except Exception as e:                               # news is a bonus; never fail the run on it
            print(f"  news query failed ({q}): {e}", file=sys.stderr)
            continue
        for it in items:
            title, link = it.findtext("title", ""), it.findtext("link", "")
            if link in seen or not NEWS_MUST.search(title) or not NEWS_ANY.search(title):
                continue
            seen.add(link)
            found.append({"title": title, "link": link, "date": it.findtext("pubDate", "")[:16]})
        time.sleep(1)
    state["seen_news"] = list(seen)[-3000:]
    print(f"News: {len(found)} new headlines to review")
    return found


def write_review(added, changed, headlines):
    lines = []
    if added:
        lines.append("## Added automatically from Wikipedia\n")
        lines.append("Please glance at these. In verification.csv, mark a wrong one `exclude`, or `unconfirmed` if the Kannada version was only announced.\n")
        lines += [f"- [{f['title']}]({f['source']}) ({f['year']}, {f['original_language']}): {f['evidence'][:200]}" for f in added]
        lines.append("")
    if changed:
        lines.append("## Wikipedia wording changed\n")
        lines += [f"- [{f['title']}]({f['source']}): {f['evidence'][:200]}" for f in changed]
        lines.append("")
    if headlines:
        lines.append("## Streaming news to check by hand\n")
        lines.append("If a headline confirms a Kannada version, add a row to press_dubs.csv.\n")
        lines += [f"- [{h['title']}]({h['link']}) ({h['date']})" for h in headlines]
        lines.append("")
    with open(REVIEW, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    return bool(lines)


def main():
    state = load_state()
    added, changed = wikipedia(state)
    headlines = news(state)
    has_news = write_review(added, changed, headlines)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)
    print("Review file written" if has_news else "Nothing new this week")


if __name__ == "__main__":
    main()
