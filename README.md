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
| `--api-origin` | Worker API origin; with `--turnstile-sitekey`, adds the signup form |
| `--turnstile-sitekey` | Turnstile site key (public) |
| `--digest-file` | Write the email digest payload here (skipped when no bills) |

## Deployment

The site is hosted on Cloudflare Pages, the email subscription API is a
Cloudflare Worker backed by D1, and a daily GitHub Actions cron scrapes,
publishes, and triggers the digest.

| Path | What it is |
| --- | --- |
| `worker/` | Subscription + digest Worker (`npm test`, `npm run typecheck`) |
| `infra/cloudflare/` | Terraform: D1, Pages, Turnstile, DNS |
| `.github/workflows/daily-digest.yml` | The daily job |
| `docs/DEPLOY_RUNBOOK.md` | Ordered first-deploy steps |
| `docs/THREAT_MODEL.md` | Attack surface, mitigations, known gaps |
| `infra/` (bootstrap/modules/envs) | The earlier AWS build, kept intact |

Readers subscribe with double opt-in and can unsubscribe in one click from any
message. Quiet days send no email.

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
