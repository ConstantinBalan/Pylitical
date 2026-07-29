# Data sources — terms, limits, and obligations

Two upstream APIs, with different roles and different rules. Both were agreed
to as a condition of access, so treat this as binding rather than advisory.

| | Open States (Plural) | LegiScan |
| --- | --- | --- |
| Role | Discovery + metadata | Bill text only |
| Supplies | identifiers, titles, actions, sponsors, subjects, votes | full document text |
| Key | `OPENSTATES_API_KEY` | `LEGISCAN_API_KEY` |
| Licence | open data | **CC BY 4.0 — attribution required** |
| Quota | free tier with key | **30,000 queries/month**, resets on the 1st |

Why both: Open States links to bill documents but does not host their text, and
Michigan's own site serves a bot-protection interstitial to automated clients.
LegiScan is the viable text source. Open States remains the primary because its
data model is cleaner and its licensing unambiguous.

---

## LegiScan rules we are bound by

These come from the API Crash Course and the API Manual. Three of them carry an
explicit penalty of **suspended access**.

1. **One public API key. Ever.** "Creating multiple Public API service keys is
   prohibited." The same key is used locally and in CI — do not create a second
   one to isolate environments, even though that is the right instinct
   everywhere else in this project.
2. **Never scrape legiscan.com.** Front-end scraping is prohibited. Only the
   documented API endpoints.
3. **If datasets are ever used, store `dataset_hash`** and skip unchanged
   downloads. "Failure to do so will result in suspended access."
4. **Attribution is mandatory.** CC BY 4.0. A visible credit linking to
   legiscan.com must appear on every page of the site and in every email.
5. Respect the published per-operation timing guidelines (manual, page 7).
   One run per day is well inside all of them.

## How the client honours the quota

`pylitical/legiscan.py` and `pylitical/usage.py`:

- **`change_hash` gating.** `getMasterListRaw` once per state per day; `getBill`
  only for bills whose hash moved. Their guidance is emphatic: "Use the hashes.
  No. Really. Use them."
- **`getBillText` is Static.** A document never changes, so it is fetched once
  and persisted. "There is no need to download the same document blob more than
  once."
- **Count before spending.** Every call checks a ceiling *before* the request
  goes out, and is recorded after a response is served — including API-level
  `ERROR` responses, which still consume a query.
- **Hard stop at 90%** of quota, leaving headroom to re-run a failed day.
- **Warn at 70%**, and project month-end usage from the current run rate.

Projected steady-state for one state: roughly 1,800 queries/month
(~31 `getMasterListRaw`, ~930 `getBill`, ~800 `getBillText`).

### The escape hatch, if you scale to many states

`getDataset` returns every `getBill`, `getRollCall`, and `getPerson` payload for
a whole session in one ZIP, rebuilt Sundays at 5am Eastern. Because `doc_id`
values live in those payloads, a weekly dataset pull could replace almost all
per-bill `getBill` calls — roughly 930/month down to about 5.

Not implemented, deliberately. Current usage is ~7% of the ceiling, so this
would be optimising a non-problem while adding ZIP handling and a suspension
risk if the `dataset_hash` logic were wrong. Revisit only if state count makes
`getBill` the binding constraint.

Note that datasets do **not** include bill text — `getBillText` is still needed
per document either way.

---

## Attribution, concretely

Required on every page and in every email:

> Bill data from [Open States](https://openstates.org/) and
> [LegiScan](https://legiscan.com/), licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Secrets

Both keys are secrets. Neither belongs in the repo, in Terraform state, or in
Cloudflare Worker config — the scrape runs in GitHub Actions, so they live in
`.env` locally and GitHub secrets in CI, and nowhere else.

Per rule 1 above, the LegiScan key is the *same* value in both places.
