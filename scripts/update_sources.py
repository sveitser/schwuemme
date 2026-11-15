#!/usr/bin/env python3
"""Fetch source data: courses at Hallenbad Rialto from several swim schools,
and Basel-Stadt school holidays.

Writes data/courses.json and data/school_holidays.json. Courses already in
courses.json are kept when they disappear from a source (finished courses are
no longer listed), so the calendar history stays intact. A provider that fails
to fetch keeps its previous data.

Providers:
  ssbb      Schwimmschule beider Basel: PDF course programmes (needs pdftotext).
            Lesson dates aren't published; build.py infers them.
  knechtli  Schwimmschule Knechtli: course-type pages incl. every lesson date.
  swimly    swimly.ch marketplace (e.g. Schwimmschule Delfin): every lesson date.
"""
import html
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = {"User-Agent": "rialto-calendar/1.0 (+https://github.com/sveitser/schwuemme)"}
HOLIDAYS_ICS = "https://data-bs.ch/stata/ed/schulferien/SchulferienBS.ics"
WEEKDAYS = ["montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonntag"]
MONTHS_DE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August",
             "September", "Oktober", "November", "Dezember"]


def fetch(url, data=None, headers=None, binary=False):
    last = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            return body if binary else body.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise
            last = e
        except Exception as e:  # connection resets etc.
            last = e
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def text_lines(page):
    page = re.sub(r"(?s)<(script|style).*?</\1>", "", page)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", page))
    return [l.strip() for l in t.splitlines() if l.strip()]


def ddmmyyyy(s):
    return datetime.strptime(s.strip(), "%d.%m.%Y").date().isoformat()


def weekday_index(s):
    s = s.strip().lower()
    for i, w in enumerate(WEEKDAYS):
        if s.startswith(w):
            return i
    raise ValueError(f"unknown weekday {s!r}")


def classify(name, hint=""):
    """Rough course type: parent-kid, kids, adult or aqua."""
    s = f"{hint} {name}".lower()
    if re.search(r"eltern|elki|baby|monate|wasserfloh|kleinkind", s) or re.search(r"\d\s*[–-]\s*\d\s*jahre\b", s) and "kinder" not in s:
        return "parent-kid"
    if re.search(r"aqua|floatfit|gym|schwanger|fitness|rückbildung", s):
        return "aqua"
    if re.search(r"erwachsene|crawl|triathlon", s) or (re.search(r"anfänger", s) and "kinder" not in s):
        return "adult"
    return "kids"


# --- Schwimmschule beider Basel ------------------------------------------

SSBB = "https://www.schwimmschulebeiderbasel.ch"


def ssbb_pdf_urls():
    """Current programme link from the website, plus guessed names of recent ones."""
    urls = []
    try:
        page = fetch(SSBB + "/de/informationen/kursprogramm/")
        urls += [SSBB + u for u in re.findall(r'href="(/de/assets/File/[^"]+\.pdf)"', page)]
    except Exception as e:
        print(f"ssbb: programme page failed: {e}", file=sys.stderr)
    today = date.today()
    for back in range(-2, 12):  # a couple of months ahead, a year back
        y, m = today.year, today.month - back
        while m < 1:
            m, y = m + 12, y - 1
        while m > 12:
            m, y = m - 12, y + 1
        for suffix in (" klein", " web", ""):
            name = f"Kursprogramm {MONTHS_DE[m - 1]} {y}{suffix}.pdf"
            urls.append(f"{SSBB}/de/assets/File/{urllib.parse.quote(name)}")
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def parse_ssbb_pdf(text, source):
    courses = []
    heading, in_rialto, period = "", False, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if re.fullmatch(r"[A-ZÄÖÜ][A-ZÄÖÜ \-–()/]+", line) and len(line) > 6:
            heading, in_rialto = line, False
            continue
        if line.startswith(("HB ", "SHB ", "Hallenbad ", "aquabasilea", "Schwimmhalle", "Gartenbad", "Traglufthalle")) and ":" in line:
            in_rialto, period = "rialto" in line.split(":")[0].lower(), None
            continue
        if not in_rialto:
            continue
        m = re.match(r"^(\w+):\s*(\d\d\.\d\d\.\d{4})\s*[–-]\s*(\d\d\.\d\d\.\d{4})\s*/\s*(\d+)\s*Lektion", line)
        if m:
            period = (weekday_index(m[1]), ddmmyyyy(m[2]), ddmmyyyy(m[3]), int(m[4]))
            continue
        m = re.match(r"^([0-9][A-Z0-9]{4,6})\s+(.+?)\s+(\d\d:\d\d)\s*[–-]\s*(\d\d:\d\d)\s*(.*)$", line)
        if m and period:
            code, level, t0, t1, teacher = m.groups()
            level = re.sub(r"\s*\(CHF[^)]*\)", "", level).strip()
            courses.append({
                "id": f"ssbb:{code}:{period[1]}",
                "provider": "Schwimmschule beider Basel",
                "code": code,
                "name": level,
                "kind": classify(level, heading),
                "weekday": period[0],
                "start": period[1],
                "end": period[2],
                "time": [t0, t1],
                "lessons": period[3],
                "source": source,
            })
    return courses


def scrape_ssbb():
    found = {}
    for url in ssbb_pdf_urls():
        try:
            pdf = fetch(url, binary=True)
        except urllib.error.HTTPError:
            continue
        if not pdf.startswith(b"%PDF"):
            continue
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(pdf)
            f.flush()
            text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True,
                                  text=True, check=True).stdout
        cs = parse_ssbb_pdf(text, url)
        print(f"ssbb: {urllib.parse.unquote(url.rsplit('/', 1)[-1])}: {len(cs)} Rialto courses", file=sys.stderr)
        for c in cs:
            found[c["id"]] = c
    return found


# --- Schwimmschule Knechtli -----------------------------------------------

KNECHTLI = "https://www.knechtli.com/"
KNECHTLI_RIALTO = KNECHTLI + "KursortDetails/Standort/9/LocRepGuid/0fb896c5-d749-4a42-b5b9-fcee7c0cfb8c/"


def scrape_knechtli():
    home = fetch(KNECHTLI_RIALTO)
    links = sorted(set(html.unescape(m) for m in re.findall(r"Kurse\.aspx\?[^'\"]+", home)))
    if not links:
        raise RuntimeError("no course type links found")
    found = {}
    for link in links:
        L = text_lines(fetch(KNECHTLI + urllib.parse.quote(link, safe="?&=/.")))
        i = 0
        while i < len(L):
            m = re.match(r"^(\d{5,}) - (.+)$", L[i])
            if not (m and i + 2 < len(L) and L[i + 1] == "Wann:"):
                i += 1
                continue
            code, name = m.groups()
            loc = L[L.index("Kursort:", i) + 1]
            k = L.index("Kursspanne", i) + 1
            dates, times = [], None
            while k < len(L) and L[k] != "Terminliste" and not re.match(r"^\d{5,} - ", L[k]):
                if re.fullmatch(r"\d\d\.\d\d\.\d{4}", L[k]) and k + 2 < len(L):
                    dates.append(ddmmyyyy(L[k]))
                    times = [L[k + 1].zfill(5), L[k + 2].lstrip("- ").strip().zfill(5)]
                    k += 3
                    continue
                k += 1
            i = k
            if "rialto" not in loc.lower() or code in found or not dates:
                continue
            found[f"knechtli:{code}"] = {
                "id": f"knechtli:{code}",
                "provider": "Schwimmschule Knechtli",
                "code": code,
                "name": name,
                "kind": classify(name),
                "weekday": date.fromisoformat(dates[0]).weekday(),
                "start": min(dates),
                "end": max(dates),
                "time": times,
                "dates": sorted(dates),
                "source": KNECHTLI + link,
            }
    print(f"knechtli: {len(found)} Rialto courses", file=sys.stderr)
    return found


# --- swimly.ch (Schwimmschule Delfin and others) --------------------------

def scrape_swimly():
    found, page = {}, 1
    while True:
        body = json.dumps({"p_surface": "marketplace", "p_only_listed": True, "p_only_available": False,
                           "p_exclude_booking_closed": False, "p_page": page, "p_page_size": 100,
                           "p_sort": "soonest"}).encode()
        d = json.loads(fetch("https://swimly.ch/api/search/courses", data=body,
                             headers={"Content-Type": "application/json"}))
        for h in d["hits"]:
            if "rialto" not in (h.get("location_name") or "").lower():
                continue
            sessions = [s for s in h.get("sessions") or [] if s.get("status") != "cancelled"]
            if not sessions:
                continue
            name = h["name"].get("de") or next(iter(h["name"].values()))
            by_time = {}
            for s in sessions:
                by_time.setdefault((s["start_time"][:5], s["end_time"][:5]), []).append(s["date"])
            for (t0, t1), dates in by_time.items():
                cid = f"swimly:{h['objectID']}:{t0}"
                found[cid] = {
                    "id": cid,
                    "provider": h.get("school_name") or "swimly",
                    "code": h.get("readable_id") or "",
                    "name": name,
                    "kind": classify(name, h.get("category_name") or ""),
                    "weekday": date.fromisoformat(dates[0]).weekday(),
                    "start": min(dates),
                    "end": max(dates),
                    "time": [t0, t1],
                    "dates": sorted(dates),
                    "source": f"https://swimly.ch/courses/{h.get('slug', '')}",
                }
        if page >= d.get("nbPages", 1):
            break
        page += 1
    print(f"swimly: {len(found)} Rialto courses", file=sys.stderr)
    return found


# --- school holidays --------------------------------------------------------

def scrape_holidays():
    ics = fetch(HOLIDAYS_ICS).replace("\r\n ", "").replace("\r", "")
    out = []
    for ev in re.findall(r"BEGIN:VEVENT(.*?)END:VEVENT", ics, re.S):
        def g(k):
            m = re.search(rf"^{k}[^:\n]*:(.*)$", ev, re.M)
            return m[1].strip() if m else ""
        s, e = g("DTSTART"), g("DTEND")
        if not s:
            continue
        sd = datetime.strptime(s[:8], "%Y%m%d").date()
        ed = datetime.strptime(e[:8], "%Y%m%d").date() - timedelta(days=1) if e else sd  # DTEND exclusive
        out.append({"start": sd.isoformat(), "end": ed.isoformat(), "name": g("SUMMARY")})
    return sorted(out, key=lambda x: x["start"])


PROVIDERS = {"ssbb": scrape_ssbb, "knechtli": scrape_knechtli, "swimly": scrape_swimly}


def main(argv):
    ok = True
    try:
        hol = scrape_holidays()
        if hol:
            (DATA / "school_holidays.json").write_text(json.dumps(hol, indent=1, ensure_ascii=False) + "\n")
    except Exception as e:
        print(f"holidays fetch failed: {e}", file=sys.stderr)
        ok = False

    path = DATA / "courses.json"
    existing = json.loads(path.read_text())["courses"] if path.exists() else []
    by_id = {c["id"]: c for c in existing if "id" in c}
    for name in argv or PROVIDERS:
        try:
            new = PROVIDERS[name]()
            by_id.update(new)
        except Exception as e:
            print(f"{name}: failed, keeping previous data: {e}", file=sys.stderr)
            ok = False
    courses = sorted(by_id.values(), key=lambda c: (c["start"], c["weekday"], c["time"][0], c["id"]))
    path.write_text(json.dumps({"courses": courses}, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(courses)} courses total", file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
