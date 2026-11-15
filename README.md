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
| `data/courses.json` | Rialto courses of [Schwimmschule beider Basel](https://www.schwimmschulebeiderbasel.ch/de/informationen/kursprogramm/) (PDF programmes), [Schwimmschule Knechtli](https://www.knechtli.com/KursortDetails/Standort/9/LocRepGuid/0fb896c5-d749-4a42-b5b9-fcee7c0cfb8c/) and [swimly](https://swimly.ch/activities?location=23ae87c3-cdd2-4ee5-a7db-797ad0b01561) (Schwimmschule Delfin) | daily by GitHub Action |
| `data/school_holidays.json` | [BS school holidays ICS](https://data-bs.ch/stata/ed/schulferien/SchulferienBS.ics) | daily by GitHub Action |
| `data/manual_blocks.json` | Other groups using the kids pool | by hand |

Knechtli and swimly publish every lesson date. Schwimmschule beider Basel only publishes a
course period and the number of lessons, so those dates are inferred as weekly dates in that
period minus BS school holidays and pool closures. If the count doesn't match, `build.py`
prints a warning and the website shows it.

Courses are tagged as parent-kid, kids, adult or aqua (guessed from the course name). The
website lets you choose which types count as blocking; the `.ics` files count all of them.

## Usage

```sh
python3 scripts/update_sources.py           # fetch all providers + school holidays (needs pdftotext)
python3 scripts/update_sources.py knechtli  # or just one provider: ssbb, knechtli, swimly
python3 scripts/build.py                    # generate docs/days.json and docs/*.ics
```

No dependencies besides Python 3 and `pdftotext` (poppler-utils). The workflow in
`.github/workflows/update.yml` re-scrapes daily, commits changed data, builds and deploys
`docs/` to GitHub Pages (Settings → Pages → Source: GitHub Actions).
