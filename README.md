# Rialto kids pool calendar

**Website: https://sveitser.github.io/schwuemme/** · Calendar feed: https://sveitser.github.io/schwuemme/rialto.ics

When Hallenbad Rialto (Basel) is open, and when the kids pool is blocked by
parent-kid courses of the Schwimmschule beider Basel.

- Website (GitHub Pages from `docs/`): month view with today marked
- `docs/rialto.ics`: open times with the kids pool free, plus closed days
- `docs/rialto-blocked.ics`: only the times the kids pool is blocked

## Data

Hallenbad Rialto has a 25m pool and two learner pools (Lernschwimmbecken). According to the
official occupancy plan, learner pool 2 (LSB2) is where courses happen; when it isn't booked
it's open to the public. The calendar shows when LSB2 is free.

| File | Source | Updated |
|---|---|---|
| `data/belegungsplan.json` | Official occupancy plan (xlsx, linked from [bs.ch](https://www.bs.ch/themen/kultur-sport-und-freizeit/baeder-kunsteisbahnen-sportanlagen-und-raeume/hallenbaeder/hallenbad-rialto)); bookings are decoded from cell colours | daily by GitHub Action |
| `data/rialto.json` | Opening hours and special days from bs.ch; which pool to track; learner pools closing 30 min early (unconfirmed) | by hand, once per season |
| `data/courses.json` | Rialto courses of [Schwimmschule beider Basel](https://www.schwimmschulebeiderbasel.ch/de/informationen/kursprogramm/) (PDF programmes), [Schwimmschule Knechtli](https://www.knechtli.com/KursortDetails/Standort/9/LocRepGuid/0fb896c5-d749-4a42-b5b9-fcee7c0cfb8c/) and [swimly](https://swimly.ch/activities?location=23ae87c3-cdd2-4ee5-a7db-797ad0b01561) (Schwimmschule Delfin) | daily by GitHub Action |
| `data/school_holidays.json` | [BS school holidays ICS](https://data-bs.ch/stata/ed/schulferien/SchulferienBS.ics) | daily by GitHub Action |
| `data/manual_blocks.json` | Extra bookings not in the plan | by hand |

The occupancy plan is a weekly pattern. For organisations whose lesson dates we know
(Knechtli, Delfin, Schwimmschule beider Basel) a plan slot only counts on days they actually
teach at Rialto, so school holidays show up as free. Slots of other organisations (Aquamaris,
Uni Sport, FloatFit, ...) count every week; during school holidays they are marked as uncertain.

Schwimmschule beider Basel doesn't publish lesson dates; they're inferred as weekly dates in
the course period minus BS school holidays and pool closures, and checked against the
published number of lessons.

## Usage

```sh
python3 scripts/update_sources.py           # fetch plan, courses + school holidays
python3 scripts/update_sources.py knechtli  # or just one: belegungsplan, ssbb, knechtli, swimly
python3 scripts/build.py                    # generate docs/days.json and docs/*.ics
```

Needs Python 3 with `openpyxl` and `pdftotext` (poppler-utils). The workflow in
`.github/workflows/update.yml` re-scrapes daily, commits changed data, builds and deploys
`docs/` to GitHub Pages (Settings → Pages → Source: GitHub Actions).
