# Rialto kids pool calendar

When Hallenbad Rialto (Basel) is open, and when the kids pool is blocked by
parent-kid courses of the Schwimmschule beider Basel.

- Website (GitHub Pages from `docs/`): month view with today marked
- `docs/rialto.ics`: open times with the kids pool free, plus closed days
- `docs/rialto-blocked.ics`: only the times the kids pool is blocked

## Data

| File | Source | Updated |
|---|---|---|
| `data/rialto.json` | Opening hours and special days from [bs.ch](https://www.bs.ch/themen/kultur-sport-und-freizeit/baeder-kunsteisbahnen-sportanlagen-und-raeume/hallenbaeder/hallenbad-rialto) | by hand, once per season |
| `data/courses.json` | Rialto courses scraped from [schwimmschulebeiderbasel.ch](https://www.schwimmschulebeiderbasel.ch/de/kurs-angebote/eltern-kind-schwimmen) | weekly by GitHub Action |
| `data/school_holidays.json` | [BS school holidays ICS](https://data-bs.ch/stata/ed/schulferien/SchulferienBS.ics) | weekly by GitHub Action |
| `data/manual_blocks.json` | Other groups using the kids pool | by hand |

The swim school only publishes a course period and the number of lessons. Lesson dates
are inferred as weekly dates in that period, minus BS school holidays and days the pool
is closed. If the count doesn't match the published number of lessons, `build.py` prints
a warning and the website shows it.

## Usage

```sh
python3 scripts/update_sources.py   # fetch courses + school holidays
python3 scripts/build.py            # regenerate docs/
```

No dependencies besides Python 3. The workflow in `.github/workflows/update.yml` runs
both every Monday and on pushes that change `data/` or `scripts/`.

To also count other course types at Rialto (e.g. Kinderschwimmen), add their category
path to `CATEGORIES` in `scripts/update_sources.py`.
