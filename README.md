# Pylitical

Scrapes bills and resolutions from the [Michigan Legislature daily report](https://legislature.mi.gov/Bills/DailyReport),
summarizes each one with the Gemini API, and renders the results as a static
site (`bills.json` + `index.html`).

## Installation

Requires Python 3.12+ and `make`.

```sh
git clone <this repo>
cd Pylitical
make bootstrap
```

`make bootstrap` creates a `venv/` and installs all pinned dependencies.

Summarization needs a Gemini API key. Create a `.env` file at the repo root
(it is gitignored — never commit it):

```sh
echo 'GOOGLE_API_KEY=your-key-here' > .env
```

## Usage

Summarize today's bills into `output/`:

```sh
make run
```

Pick a date range and open the result:

```sh
make run ARGS="--start-date 2026-07-01 --end-date 2026-07-02"
open output/index.html
```

Scrape without calling Gemini (no API key needed — useful for testing):

```sh
make run ARGS="--skip-summaries"
```

All flags:

| Flag | Meaning |
| --- | --- |
| `--start-date` | Range start, `YYYY-MM-DD` (default: today) |
| `--end-date` | Range end, `YYYY-MM-DD` |
| `--output-dir` | Output directory (default: `output`) |
| `--skip-summaries` | Skip the Gemini API; render scraped bills only |

## Using it as a library

The `pylitical` package is importable on its own:

```python
from pylitical import BillScraper

bills = BillScraper().find("2026-07-01", "2026-07-02")
for bill in bills:
    print(bill.as_json())
```

## Development

```sh
make lint   # pylint
make fmt    # black
```
