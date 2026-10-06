# Bot diagnostic

A small Python 3.10+ package that classifies Crawlbase Crawling API responses and measures usable data on URLs you are authorized to collect. It does not solve challenges or change request identity. Use it on pages your terms already allow.

The first request uses the normal token and `format=json`. `cb_status` is the fetch layer, `original_status` is the target, `url` is the final URL, and domain complexity is the tier name (`standard`, `moderate`, or `complex` when the API sends it). Credit multipliers are not in that field; read those from the Crawlbase dashboard.

Python 3.10 or newer. These commands use PowerShell.

## Setup

```powershell
cd code
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` and set `CRAWLBASE_TOKEN`. Set `CRAWLBASE_JS_TOKEN` only if a response comes back `520` or `525`. You do not need either token for the dry-run path below.

## Dry run, no keys

From `code/`:

```powershell
python steps/step_01_first_request.py --dry-run
python steps/step_02_inspect_response.py --dry-run
python steps/step_03_classify_response.py --dry-run
python steps/step_04_escalate_on_failure.py --dry-run
python steps/step_05_sample_evaluation.py --dry-run
```

Each numbered file mirrors the matching walkthrough section. `--help` on any step also runs without a token.

From `code/final`:

```powershell
cd final
python -m bot_diag evaluate urls.example.txt --fields price,title --dry-run
```

`--dry-run` writes `sample_results.csv` in the working directory and prints usable rate, nearest-rank p50 and p95 latency, and retry overhead. It does not call Crawlbase.

Tests, from `code/`:

```powershell
python -m pytest -q -m "not live"
```

## Live sample

From `code/final`, with the virtualenv active and `CRAWLBASE_TOKEN` set, and a file of URLs you are authorized to collect:

```powershell
python -m bot_diag evaluate urls.txt --fields price,title
```

Optional flags: `--country US` (a two-letter code you choose; the tool does not rotate countries), `--concurrency 4` (capped at 8), `--max-retries 2`, `--out sample_results.csv`.

The same call as one request:

```powershell
python ..\steps\step_01_first_request.py --url https://example.com/
```

## What the labels and statuses mean

`classify_response` returns `blocked`, `challenged`, `invalid_content`, or `ok`. It looks at the target status, commonly observed Cloudflare, DataDome, and Akamai markers, and the fields you named. HTTP 200 with a missing field is `invalid_content`. A confirmed block is not retried.

| cb_status | Action |
| --- | --- |
| 422 | Fix URL encoding. Do not retry. |
| 520 | Switch to the JavaScript token. |
| 521 | Target unreachable: retry with backoff; verify that the target is up if it persists. |
| 522 | Connection timeout: retry with backoff; consider `country` only for a geo-dependent target. |
| 523 | Retry without `country`, or choose a different country. |
| 525 | Switch to the JavaScript token. If it persists, retry once, then contact support. |
| 595 | Correct the missing CSS selector or add a fallback. Do not retry unchanged. |
| 599 | Retry; if it persists, contact support with the request ID. |

Retry overhead counts those fetch-layer retries and JavaScript escalations, per usable row. Usable means the label was `ok`.

Billing is not identical to HTTP success. Crawlbase documents that failed requests are not charged, but successful target `404` and `410` responses can be billable. Enterprise Crawler webhook-delivery retries are also charged. Confirm current terms on the pricing and Crawler documentation pages before a large run.

## Layout

`final/bot_diag/` is the package. Run it with `python -m bot_diag` from `code/final`. `steps/` calls the same functions one piece at a time. `final/urls.example.txt` lists `https://example.com` URLs for the dry run.

The optional live test is marked `live` and is skipped unless `CRAWLBASE_TOKEN` is set and the URL host is `example.com`.

---

Copyright 2026 [Crawlbase](https://crawlbase.com/)
