#!/usr/bin/env python3
"""Build docs/days.json and the .ics calendars from the files in data/.

No network access needed; run scripts/update_sources.py first to refresh data.
"""
import hashlib
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs"

WD_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def d(s):
    return date.fromisoformat(s)


def mins(t):
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def hhmm(m):
    return f"{m // 60:02d}:{m % 60:02d}"


def load(name, default=None):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def opening(rialto, day):
    """Return (open_interval_or_None, note)."""
    sp = rialto["special"].get(day.isoformat())
    for s in rialto["seasons"]:
        if d(s["start"]) <= day <= d(s["end"]):
            if sp and sp.get("closed"):
                return None, sp.get("note", "Closed")
            hours = sp["hours"] if sp and "hours" in sp else s["hours"][WD_KEYS[day.weekday()]]
            return (mins(hours[0]), mins(hours[1])), (sp or {}).get("note", "")
    return None, "Off season"


def in_holiday(day, holidays):
    for h in holidays:
        if d(h["start"]) <= day <= d(h["end"]):
            return h["name"]
    return None


def weekly(start, end, weekday):
    cur = start + timedelta(days=(weekday - start.weekday()) % 7)
    while cur <= end:
        yield cur
        cur += timedelta(days=7)


def main():
    rialto = load("rialto.json")
    holidays = load("school_holidays.json", [])
    courses = load("courses.json", {"courses": []})["courses"]
    manual = load("manual_blocks.json", {"blocks": []})["blocks"]
    warnings = []

    blocks = {}  # iso date -> list of (start, end, label)

    def add(day, t, label, kind="other"):
        blocks.setdefault(day.isoformat(), []).append((mins(t[0]), mins(t[1]), label, kind))

    # Courses with explicit dates (Knechtli, swimly) are used as-is. For the
    # others (Schwimmschule beider Basel) lesson dates aren't published, so infer
    # them as weekly dates within the course period minus BS school holidays and
    # pool closures, then check against the published number of lessons.
    for c in courses:
        if c.get("dates"):
            dates = [d(x) for x in c["dates"]]
        else:
            dates = [x for x in weekly(d(c["start"]), d(c["end"]), c["weekday"])
                     if not in_holiday(x, holidays)
                     and not rialto["special"].get(x.isoformat(), {}).get("closed")]
            if c.get("lessons") and len(dates) != c["lessons"]:
                warnings.append(f"{c['provider']} {c.get('code', '')}: inferred {len(dates)} lessons, "
                                f"source says {c['lessons']} - check dates manually")
        label = f"{c['provider']}: {c['name']}" + (f" ({c['code']})" if c.get("code") else "")
        for x in dates:
            add(x, c["time"], label, c["kind"])

    for b in manual:
        if "dates" in b:
            ds = [d(x) for x in b["dates"]]
        else:
            ds = list(weekly(d(b["start"]), d(b["end"]), WD_KEYS.index(b["weekday"])))
            if b.get("skip_school_holidays"):
                ds = [x for x in ds if not in_holiday(x, holidays)]
        excl = set(b.get("exclude", []))
        for x in ds:
            if x.isoformat() not in excl:
                add(x, b["time"], b["label"], b.get("kind", "other"))

    first = min(d(s["start"]) for s in rialto["seasons"])
    last = max(d(s["end"]) for s in rialto["seasons"])
    for k in blocks:
        first, last = min(first, d(k)), max(last, d(k))

    days = {}
    cur = first
    while cur <= last:
        iso = cur.isoformat()
        o, note = opening(rialto, cur)
        raw = sorted(blocks.get(iso, []))
        # merge overlapping/adjacent blocks
        merged = []
        for s, e, lab, kind in raw:
            if merged and s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
                merged[-1][2].append(lab)
                merged[-1][3].add(kind)
            else:
                merged.append([s, e, [lab], {kind}])
        free = []
        if o:
            t = o[0]
            for s, e, _, _ in merged:
                if s > t and s <= o[1]:
                    free.append((t, min(s, o[1])))
                t = max(t, e)
            if t < o[1]:
                free.append((t, o[1]))
        days[iso] = {
            "open": [hhmm(o[0]), hhmm(o[1])] if o else None,
            "note": note,
            "blocked": [{"from": hhmm(s), "to": hhmm(e), "what": labs, "kinds": sorted(k)}
                        for s, e, labs, k in merged],
            "courses": [{"from": hhmm(s), "to": hhmm(e), "what": lab, "kind": kind} for s, e, lab, kind in raw],
            "free": [[hhmm(s), hhmm(e)] for s, e in free],
            "school_holiday": in_holiday(cur, holidays),
        }
        cur += timedelta(days=1)

    OUT.mkdir(exist_ok=True)
    (OUT / "days.json").write_text(json.dumps({
        "pool": rialto["name"],
        "address": rialto["address"],
        "warnings": warnings,
        "days": days,
    }, indent=1, ensure_ascii=False) + "\n")

    write_ics(OUT / "rialto.ics", "Rialto kids pool", days, rialto, mode="all")
    write_ics(OUT / "rialto-blocked.ics", "Rialto kids pool blocked", days, rialto, mode="blocked")

    for w in warnings:
        print("WARNING:", w, file=sys.stderr)
    print(f"built {len(days)} days, {sum(1 for v in days.values() if v['blocked'])} with blocks")


VTIMEZONE = """BEGIN:VTIMEZONE
TZID:Europe/Zurich
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE"""


def esc(s):
    return s.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def fold(line):
    b = line.encode()
    if len(b) <= 75:
        return line
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode()) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def write_ics(path, name, days, rialto, mode):
    stamp = "20260101T000000Z"
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//schwuemme//rialto//EN", "CALSCALE:GREGORIAN",
             "METHOD:PUBLISH", f"X-WR-CALNAME:{name}", "X-WR-TIMEZONE:Europe/Zurich",
             "REFRESH-INTERVAL;VALUE=DURATION:PT12H", "X-PUBLISHED-TTL:PT12H", VTIMEZONE]

    def ev(uid_key, summary, start, end=None, allday=False, desc=""):
        uid = hashlib.sha1(uid_key.encode()).hexdigest()[:16] + "@schwuemme"
        lines.extend(["BEGIN:VEVENT", f"UID:{uid}", f"DTSTAMP:{stamp}"])
        if allday:
            lines.append(f"DTSTART;VALUE=DATE:{start}")
            lines.append(f"DTEND;VALUE=DATE:{end}")
        else:
            lines.append(f"DTSTART;TZID=Europe/Zurich:{start}")
            lines.append(f"DTEND;TZID=Europe/Zurich:{end}")
        lines.append(fold("SUMMARY:" + esc(summary)))
        lines.append(fold("LOCATION:" + esc(f"{rialto['name']}, {rialto['address']}")))
        if desc:
            lines.append(fold("DESCRIPTION:" + esc(desc)))
        lines.extend(["TRANSP:TRANSPARENT", "END:VEVENT"])

    for iso, v in days.items():
        ymd = iso.replace("-", "")
        dt = lambda t: f"{ymd}T{t.replace(':', '')}00"
        if mode == "blocked":
            for b in v["blocked"]:
                ev(f"blocked-{iso}-{b['from']}", "Rialto kids pool blocked", dt(b["from"]), dt(b["to"]),
                   desc="\n".join(b["what"]))
            continue
        if not v["open"]:
            if v["note"] != "Off season":
                nxt = (date.fromisoformat(iso) + timedelta(days=1)).strftime("%Y%m%d")
                ev(f"closed-{iso}", f"Rialto closed ({v['note']})", ymd, nxt, allday=True)
            continue
        extra = f" – {v['note']}" if v["note"] else ""
        if not v["blocked"]:
            ev(f"free-{iso}-{v['open'][0]}", f"Rialto open, kids pool free{extra}",
               dt(v["open"][0]), dt(v["open"][1]))
            continue
        busy = "\n".join(f"Blocked {b['from']}–{b['to']}: " + "; ".join(b["what"]) for b in v["blocked"])
        for f in v["free"]:
            ev(f"free-{iso}-{f[0]}", f"Rialto kids pool free{extra}", dt(f[0]), dt(f[1]),
               desc=f"Pool open {v['open'][0]}–{v['open'][1]}.\n{busy}")

    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n")


if __name__ == "__main__":
    main()
