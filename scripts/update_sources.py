#!/usr/bin/env python3
"""Fetch source data: Rialto parent-kid courses and Basel-Stadt school holidays.

Writes data/courses.json and data/school_holidays.json. Courses already in
courses.json are kept even if they disappear from the website (finished
courses are no longer listed), so the calendar history stays intact.
"""
import html
import json
import re
import sys
import urllib.request
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BASE = "https://www.schwimmschulebeiderbasel.ch"
# Course categories to scan. Add e.g. "/de/kurs-angebote/kinderschwimmen" here
# if other course types at Rialto should also block the kids pool.
CATEGORIES = ["/de/kurs-angebote/eltern-kind-schwimmen"]
POOL_MATCH = "Rialto"
HOLIDAYS_ICS = "https://data-bs.ch/stata/ed/schulferien/SchulferienBS.ics"


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "rialto-calendar/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", errors="replace")


class RowParser(HTMLParser):
    """Collects <tr class="tag-list-row"> rows as lists of cell texts + links."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.in_row = [], None, None, False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "tag-list-row" in (a.get("class") or ""):
            self.row = {"cells": [], "links": []}
        elif self.row is not None and tag == "td":
            self.cell = []
        elif self.row is not None and tag == "a" and a.get("href", "").startswith("/de/kurs-details/"):
            self.row["links"].append((a["href"], a.get("title", "").strip()))

    def handle_endtag(self, tag):
        if self.row is None:
            return
        if tag == "td" and self.cell is not None:
            self.row["cells"].append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr":
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)


def text_of(page):
    page = re.sub(r"(?s)<(script|style).*?</\1>", "", page)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [l.strip() for l in t.splitlines() if l.strip()]


def parse_details(url):
    lines = text_of(fetch(url))
    fields = {}
    keys = ["KursCode", "Kursstufe", "Schwimmbad", "Zeitraum", "Wochentag", "Kurszeiten",
            "Anzahl Lektionen", "Schwimmlehrer/in", "Bemerkungen"]
    for i, l in enumerate(lines[:-1]):
        if l in keys and l not in fields:
            fields[l] = lines[i + 1]
    return fields


def ddmmyyyy(s):
    return datetime.strptime(s.strip(), "%d.%m.%Y").date().isoformat()


def scrape_courses():
    found = {}
    for cat in CATEGORIES:
        page = fetch(BASE + cat)
        subs = sorted(set(re.findall(re.escape(cat) + r"/\?k=[A-Z0-9]+", page))) or [cat]
        for sub in subs:
            p = RowParser()
            p.feed(fetch(BASE + sub))
            for row in p.rows:
                if not any(POOL_MATCH in c for c in row["cells"]) or not row["links"]:
                    continue
                href, _ = row["links"][0]
                d = parse_details(BASE + href)
                code = d.get("KursCode")
                if not code or POOL_MATCH not in d.get("Schwimmbad", ""):
                    continue
                start, end = [ddmmyyyy(x) for x in d["Zeitraum"].split(" - ")]
                t0, t1 = [x.strip() for x in d["Kurszeiten"].split("-")]
                found[code] = {
                    "code": code,
                    "category": cat.rsplit("/", 1)[-1],
                    "level": d.get("Kursstufe", ""),
                    "pool": d.get("Schwimmbad", ""),
                    "weekday": d.get("Wochentag", ""),
                    "start": start,
                    "end": end,
                    "time": [t0, t1],
                    "lessons": int(re.sub(r"\D", "", d.get("Anzahl Lektionen", "0")) or 0),
                    "teacher": d.get("Schwimmlehrer/in", ""),
                    "remarks": d.get("Bemerkungen", ""),
                    "url": BASE + href,
                }
    return found


def scrape_holidays():
    ics = fetch(HOLIDAYS_ICS).replace("\r\n ", "").replace("\r", "")
    out = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics, re.S):
        g = lambda k: (re.search(rf"^{k}[^:\n]*:(.*)$", ev, re.M) or [None, ""])[1].strip()
        s, e, summary = g("DTSTART"), g("DTEND"), g("SUMMARY")
        if not s:
            continue
        sd = datetime.strptime(s[:8], "%Y%m%d").date()
        ed = datetime.strptime(e[:8], "%Y%m%d").date() - timedelta(days=1) if e else sd  # DTEND exclusive
        out.append({"start": sd.isoformat(), "end": ed.isoformat(), "name": summary})
    out.sort(key=lambda x: x["start"])
    return out


def main():
    ok = True
    try:
        hol = scrape_holidays()
        if hol:
            (DATA / "school_holidays.json").write_text(json.dumps(hol, indent=2, ensure_ascii=False) + "\n")
    except Exception as e:  # keep old data on failure
        print(f"holidays fetch failed: {e}", file=sys.stderr)
        ok = False

    path = DATA / "courses.json"
    existing = json.loads(path.read_text()) if path.exists() else {"courses": []}
    by_code = {c["code"]: c for c in existing["courses"]}
    try:
        new = scrape_courses()
        by_code.update(new)
        print(f"scraped {len(new)} Rialto courses")
    except Exception as e:
        print(f"course scrape failed: {e}", file=sys.stderr)
        ok = False
    courses = sorted(by_code.values(), key=lambda c: (c["start"], c["time"][0], c["code"]))
    path.write_text(json.dumps({"courses": courses}, indent=2, ensure_ascii=False) + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
