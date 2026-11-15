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


# Organisations in the occupancy plan whose individual lesson dates we know.
# Their plan slots only count on days the school actually teaches at Rialto, so
# school holidays etc. show up as free.
ORG_PROVIDER = {"knechtli": "knechtli", "delfin": "delfin", "svb": "beider basel"}


def main():
    rialto = load("rialto.json")
    holidays = load("school_holidays.json", [])
    courses = load("courses.json", {"courses": []})["courses"]
    manual = load("manual_blocks.json", {"blocks": []})["blocks"]
    plan = load("belegungsplan.json")
    pool = rialto.get("kids_pool", "LSB2")
    early = rialto.get("learner_pool_closes_early_min", 0)
    warnings = []

    # lessons per day: iso date -> list of (start, end, provider, label)
    lessons = {}
    for c in courses:
        if c.get("dates"):
            dates = [d(x) for x in c["dates"]]
        else:
            # Schwimmschule beider Basel doesn't publish lesson dates: infer weekly
            # dates minus BS school holidays and pool closures.
            dates = [x for x in weekly(d(c["start"]), d(c["end"]), c["weekday"])
                     if not in_holiday(x, holidays)
                     and not rialto["special"].get(x.isoformat(), {}).get("closed")]
            if c.get("lessons") and len(dates) != c["lessons"]:
                warnings.append(f"{c['provider']} {c.get('code', '')}: inferred {len(dates)} lessons, "
                                f"source says {c['lessons']} - check dates manually")
        label = f"{c['name']}" + (f" ({c['code']})" if c.get("code") else "")
        for x in dates:
            lessons.setdefault(x.isoformat(), []).append(
                (mins(c["time"][0]), mins(c["time"][1]), c["provider"], label))

    def provider_active(key, day):
        return any(key in c["provider"].lower() and c["weekday"] == day.weekday()
                   and d(c["start"]) <= day <= d(c["end"]) for c in courses)

    blocks = {}  # iso date -> list of dicts

    def add(day, s, e, org, what, note=""):
        blocks.setdefault(day.isoformat(), []).append({"s": s, "e": e, "org": org, "what": what, "note": note})

    first = min(d(s["start"]) for s in rialto["seasons"])
    last = max(d(s["end"]) for s in rialto["seasons"])
    if plan:
        valid_from = d(plan["valid_from"]) if plan.get("valid_from") else first
        slots = [x for x in plan["slots"] if x["pool"] == pool]
        day = max(first, valid_from)
        while day <= last:
            iso = day.isoformat()
            if opening(rialto, day)[0]:
                for sl in (x for x in slots if x["weekday"] == day.weekday()):
                    s, e = mins(sl["from"]), mins(sl["to"])
                    key = next((v for k, v in ORG_PROVIDER.items() if k in sl["org"].lower()), None)
                    if key and provider_active(key, day):
                        todays = [l for l in lessons.get(iso, []) if key in l[2].lower()]
                        if not todays:
                            continue  # school not teaching today (holidays etc.)
                        what = [f"{hhmm(a)}–{hhmm(b)} {lab}" for a, b, _, lab in sorted(todays) if a < e and b > s]
                        add(day, s, e, sl["org"], what)
                    elif key and in_holiday(day, holidays):
                        continue  # these schools pause during school holidays
                    else:
                        note = "per occupancy plan; may not take place during school holidays" if in_holiday(day, holidays) else ""
                        add(day, s, e, sl["org"], [], note)
            day += timedelta(days=1)
    else:
        warnings.append("no occupancy plan (data/belegungsplan.json); falling back to all known courses")
        for iso, ls in lessons.items():
            for a, b, prov, lab in ls:
                add(d(iso), a, b, prov, [lab])

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
                add(x, mins(b["time"][0]), mins(b["time"][1]), b["label"], [])

    days = {}
    cur = first
    while cur <= last:
        iso = cur.isoformat()
        o, note = opening(rialto, cur)
        bl = sorted(blocks.get(iso, []), key=lambda x: x["s"])
        kp = (o[0], o[1] - early) if o else None  # kids pool closes earlier
        free = []
        if kp:
            t = kp[0]
            for b in bl:
                if b["s"] > t and t < kp[1]:
                    free.append((t, min(b["s"], kp[1])))
                t = max(t, b["e"])
            if t < kp[1]:
                free.append((t, kp[1]))
        days[iso] = {
            "open": [hhmm(o[0]), hhmm(o[1])] if o else None,
            "kids_pool_open": [hhmm(kp[0]), hhmm(kp[1])] if kp else None,
            "note": note,
            "blocked": [{"from": hhmm(b["s"]), "to": hhmm(b["e"]), "org": b["org"], "what": b["what"],
                         "note": b["note"]} for b in bl],
            "free": [[hhmm(a), hhmm(b)] for a, b in free],
            "school_holiday": in_holiday(cur, holidays),
        }
        cur += timedelta(days=1)

    OUT.mkdir(exist_ok=True)
    (OUT / "days.json").write_text(json.dumps({
        "pool": rialto["name"],
        "address": rialto["address"],
        "plan": {k: plan.get(k) for k in ("source", "title", "valid_from")} if plan else None,
        "kids_pool_closes_early_min": early,
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
                ev(f"blocked-{iso}-{b['from']}", f"Rialto kids pool: {b['org']}", dt(b["from"]), dt(b["to"]),
                   desc="\n".join(b["what"] + ([b["note"]] if b["note"] else [])))
            continue
        if not v["open"]:
            if v["note"] != "Off season":
                nxt = (date.fromisoformat(iso) + timedelta(days=1)).strftime("%Y%m%d")
                ev(f"closed-{iso}", f"Rialto closed ({v['note']})", ymd, nxt, allday=True)
            continue
        extra = f" – {v['note']}" if v["note"] else ""
        busy = "\n".join(f"Blocked {b['from']}–{b['to']}: {b['org']}" for b in v["blocked"])
        for f in v["free"]:
            ev(f"free-{iso}-{f[0]}", f"Rialto kids pool free{extra}", dt(f[0]), dt(f[1]),
               desc=f"Pool open {v['open'][0]}–{v['open'][1]}, kids pool until {v['kids_pool_open'][1]}.\n{busy}")

    lines.append("END:VCALENDAR")
    path.write_text("\r\n".join(lines) + "\r\n")


if __name__ == "__main__":
    main()
