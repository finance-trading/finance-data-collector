---
name: sec-filings-download
description: Download complete SEC filing and exhibit packages for a company from EDGAR into the centralized local SEC store before primary-source financial analysis.
---

# SEC Filings Download

Download **all** SEC filings for a company from SEC EDGAR, including text, XBRL, and non-image exhibit files. Image attachments are skipped by default because they are usually not needed for financial/company analysis. Handles pagination for companies with 1000+ filings.

## When to Use

- **User explicitly asks** to download, fetch, or refresh SEC filings for a company
- **Before initiating-coverage Task 2** (Financial Modeling) — verify filings exist in `sec/<TICKER>/`
- **Before 3-statement-model, dcf-model, comps-analysis, earnings-analysis** — these skills need primary-source filings
- **When starting a new company** that has no `sec/` directory yet

**Do NOT use this skill when:**
- User wants to analyze a specific filing already downloaded (use the equity-research skills directly)
- User wants to search EDGAR for filings without downloading (use WebFetch or WebSearch)

## Prerequisites

1. **Python environment** with `requests` (already in `.venv`)
2. **SEC EDGAR User-Agent email** — one-time setup:
   - First run will prompt for your email address
   - Cached in `~/.sec_edgar_user_agent` (format: `email/1.0`)
   - Or set env var `SEC_EDGAR_UA=email/1.0`
3. **Internet connection** — EDGAR API calls required

## Key Features

### 1. Complete Historical Coverage
Downloads **all** filings from EDGAR, not just recent ones. The script handles pagination automatically — for companies like Microsoft with 2000+ filings, it downloads the main submissions file plus all historical pages (1994-2008, 2008-2020, 2020-present).

### 2. Full Exhibit Packages
Each filing includes **all files** from the SEC package:
- Primary document (10-K.htm, 10-Q.htm, etc.)
- All exhibit files (ex-10.01.htm, ex-23.01.htm, ex-31.01.htm, etc.)
- XBRL data files (.xsd, .xml, .cal, .lab, .pre)
- Any other attachments

## Invocation

```bash
# Download all 10-K, 10-Q, DEF 14A filings (default)
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT

# Specific form types only
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --forms 10-K,10-Q

# Include amended filings (10-K/A, 10-Q/A)
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --include-amended

# Force re-download of existing files
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --force

# Refresh cached metadata from EDGAR
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --refresh-cache

# Custom output directory
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --output-dir /path/to/output

# Include image attachments when a complete visual archive is needed
python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT --include-images
```

**CLI arguments:**

| Argument | Default | Description |
|----------|---------|-------------|
| `ticker` | (required) | Stock ticker symbol (e.g., MSFT, AAPL, GOOG) |
| `--forms LIST` | 10-K,10-Q,DEF 14A,20-F | Comma-separated form types to download |
| `--include-amended` | false | Include `/A` amended filings |
| `--force` | false | Re-download files that already exist |
| `--refresh-cache` | false | Force refresh of cached metadata from EDGAR |
| `--output-dir PATH` | sec/<TICKER> | Override output directory |
| `--include-images` | false | Include image attachments; images are skipped by default |
| `--include-txt` | false | Include the complete-submission `.txt` package (~25-40MB per filing, duplicates other files; skipped by default) |

## Output Structure

Files are organized by form type, with each filing in its own directory named by accession number:

```
sec/<TICKER>/
├── 10-K/
│   ├── 0000789019-25-000002/    # One directory per filing
│   │   ├── msft-20250630.htm    # Primary document
│   │   ├── ex-1001.htm          # Exhibit 10.01
│   │   ├── ex-2301.htm          # Exhibit 23.01
│   │   ├── msft-20250630.xsd    # XBRL schema
│   │   └── ...                  # All other exhibits
│   ├── 0000789019-24-000003/
│   │   └── ...
│   └── ...
├── 10-Q/
│   ├── 0000789019-25-000010/
│   └── ...
├── DEF-14A/
│   ├── 0000789019-24-000050/
│   └── ...
└── filings_index.json           # Metadata for all filings
```

The `filings_index.json` contains metadata for all filings:
- Form type, filing date, accession number
- Directory path for each filing
- Primary document filename

## Caching Behavior

The script caches metadata files locally to avoid redundant EDGAR requests:

| File | Location | Refresh Policy |
|------|----------|----------------|
| **Tickers dictionary** | `sec/.cache/company_tickers.json` | Use `--refresh-cache` to force re-download |
| **Company submissions** | `sec/.cache/submissions_{CIK}.json` | Use `--refresh-cache` to force re-download |
| **Historical pages** | `sec/.cache/submissions_{CIK}_*.json` | Use `--refresh-cache` to force re-download |
| **Filing documents** | `sec/<TICKER>/<FORM>/<accession>/` | Skipped if already exists; use `--force` to re-download |

The tickers file (~2MB JSON, all US-listed companies) is shared across all runs. The submissions files are per-CIK. Metadata caches stay indefinitely until `--refresh-cache` is passed.

## Verification

After download completes:

1. **Check `filings_index.json`** — lists all filings with metadata (form, date, accession number, directory path)
2. **Count filings by form type** — script prints summary at the end
3. **Spot-check one filing** — open an HTML file in browser to confirm it's a real SEC filing
4. **Verify exhibit files** — check that each filing directory contains multiple files (primary + exhibits)
5. **Verify idempotency** — re-run the same command; all files should be skipped

## Rate Limits & Compliance

- **User-Agent**: EDGAR requires a valid email in User-Agent header (`email/1.0`)
- **Rate limit**: 0.11s delay between requests (≤10 req/sec, EDGAR's limit)
- **Idempotent**: Skips files that already exist (unless `--force`)
- **Image policy**: Skips common image attachments by default; use `--include-images` to download them
- **Respect robots.txt**: Only downloads requested filing types

## Downstream Usage

After downloading filings, these skills can consume them:

- **initiating-coverage Task 2** (Financial Modeling) — extracts historical data from 10-K/10-Q
- **3-statement-model** — populates income statement, balance sheet, cash flow from filings
- **dcf-model** — uses historical financials to build projections
- **comps-analysis** — references filings for peer company data
- **earnings-analysis** — compares actuals (from 10-Q) vs estimates

**Reference path pattern:** `sec/<TICKER>/<FORM>/<accession>/<filename>`

Example: `sec/MSFT/10-K/0000789019-25-000002/msft-20250630.htm`

## Error Handling

| Error | Cause | Solution |
|-------|-------|----------|
| `Error: Could not find CIK for ticker` | Invalid or delisted ticker | Verify ticker symbol on SEC.gov |
| `No filings found matching criteria` | Wrong form types specified | Adjust `--forms` parameter |
| `Error downloading [URL]` | Network failure, rate limit, or SEC outage | Wait and retry; check internet connection |
| `403 Forbidden` | Missing/invalid User-Agent, or blocked by EDGAR | Verify email in `~/.sec_edgar_user_agent`; wait 1 hour |
| `Error: Missing dependencies` | `requests` not installed | Run `pip install requests beautifulsoup4 lxml` |

## Example Workflow

**Scenario**: Starting initiating-coverage for Microsoft (MSFT)

1. **Download all filings**:
   ```bash
   python .agents/skills/sec-filings-download/scripts/download_sec_filings.py MSFT
   ```
   → Downloads 2000+ filings into `sec/MSFT/`

2. **Verify**:
   ```bash
   ls sec/MSFT/10-K/ | wc -l
   cat sec/MSFT/filings_index.json | jq '.total_filings'
   ```
   → Confirm all historical annual reports present

3. **Check a specific filing**:
   ```bash
   ls sec/MSFT/10-K/0000789019-25-000002/
   ```
   → See primary document + all exhibits

4. **Start Task 2** (Financial Modeling):
   ```
   User: "Do initiating-coverage Task 2 for MSFT"
   ```
   → Skill reads `sec/MSFT/10-K/` and `10-Q/` to extract historical data

## Performance Notes

- **First run**: Downloads all filings, may take 10-30 minutes for companies with 1000+ filings
- **Subsequent runs**: Only downloads new filings, much faster
- **Disk space**: ~1-5 MB per filing (including exhibits); MSFT's 2000+ filings ≈ 5-10 GB
- **Download speed**: ~1 file per second (rate-limited to 10 req/sec)

## Limitations

- **No XBRL parsing**: Script downloads raw XBRL files; use Python libraries (`edxbrl`, `arelle`) for structured data extraction
- **No full-text search**: Use `grep` or `ripgrep` on downloaded HTML files
- **Amended filings**: Excluded by default; use `--include-amended` if needed
- **Large downloads**: Companies with extensive history (MSFT, GOOG, AAPL) may take significant time on first run
- **Image attachments**: Skipped by default; use `--include-images` if an image-only exhibit is needed for visual due diligence

## Compliance Notice

This script accesses SEC EDGAR, a public government service. You must:

1. Provide a valid email address in User-Agent header (EDGAR's requirement)
2. Respect rate limits (≤10 requests/second)
3. Not redistribute downloaded filings for commercial purposes (SEC filings are public domain, but bulk redistribution may require attribution)

See https://www.sec.gov/os/accessing-edgar-data for EDGAR's terms of use.
