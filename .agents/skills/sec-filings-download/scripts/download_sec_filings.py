#!/usr/bin/env python3
"""Download all SEC filings from EDGAR with complete exhibit packages.

Usage:
    python download_sec_filings.py MSFT
    python download_sec_filings.py MSFT --forms 10-K,10-Q
    python download_sec_filings.py MSFT --max-delay 2.0
    python download_sec_filings.py MSFT --concurrency 2
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from collections import deque

from fdc.sec_storage import CACHE_DIR, default_output_dir

try:
    import requests
except ImportError:
    print("Error: Missing dependencies. Install with: pip install requests beautifulsoup4 lxml")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_FORMS = [
    "10-K", "10-Q", "10-K/A", "10-Q/A",
    "8-K", "8-K/A",
    "DEF 14A", "DEFA14A",
    "20-F", "6-K",
    "S-1", "S-3", "S-8",
    "424B", "485A", "485B",
]
EDGAR_BASE = "https://www.sec.gov"
DATA_BASE = "https://data.sec.gov"
BASE_DELAY = 0.35
MAX_DELAY = 2.0
MIN_DELAY = 0.15
MAX_REQUESTS_PER_MINUTE = 10
MAX_CONSECUTIVE_429S = 3
USER_AGENT_FILE = Path.home() / ".sec_edgar_user_agent"
TICKERS_CACHE = CACHE_DIR / "company_tickers.json"

# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class RateLimiter:
    """Token-bucket rate limiter with exponential backoff and jitter."""

    def __init__(self, max_per_minute: int = MAX_REQUESTS_PER_MINUTE,
                 base_delay: float = BASE_DELAY,
                 max_delay: float = MAX_DELAY,
                 min_delay: float = MIN_DELAY):
        self.max_per_minute = max_per_minute
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.min_delay = min_delay
        self._timestamps: deque = deque()
        self._consecutive_429s = 0
        self._block_until: float = 0

    def _clean_old_timestamps(self) -> None:
        cutoff = time.time() - 60
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()

    def _wait(self, delay: float) -> None:
        if delay <= 0:
            return
        time.sleep(delay)

    def acquire(self, is_429: bool = False) -> float:
        """Returns the number of seconds to wait before next request."""
        now = time.time()

        # Handle temporary blocks (extended 429 responses)
        if now < self._block_until:
            wait = self._block_until - now
            self._wait(wait)
            return 0.0

        self._clean_old_timestamps()

        if is_429:
            self._consecutive_429s += 1
            backoff = min(self.base_delay * (2 ** self._consecutive_429s), self.max_delay)
            # Add jitter: random 0-20% of backoff
            jitter = backoff * 0.2 * (1 if self._consecutive_429s > 1 else 0)
            total = backoff + jitter
            self._wait(total)
            # If too many 429s, extend block
            if self._consecutive_429s >= MAX_CONSECUTIVE_429S:
                self._block_until = time.time() + self.max_delay
                print(f"    ⚠ Rate limit hit ({self._consecutive_429s}x consecutive 429s). Backing off {self.max_delay}s", file=sys.stderr)
            return total
        else:
            # Reset 429 counter on success
            self._consecutive_429s = 0

        # Token bucket: respect max requests per minute
        self._clean_old_timestamps()
        if len(self._timestamps) >= self.max_per_minute:
            oldest = self._timestamps[0]
            wait = 60.0 - (now - oldest)
            if wait > 0:
                self._wait(wait)
                self._timestamps.popleft()

        # Standard delay with jitter
        jitter = (time.time() * 1000 % 100) * 0.001  # 0-0.1s jitter
        delay = self.base_delay + jitter
        self._wait(delay)

        self._timestamps.append(time.time())
        return delay

    def mark_success(self) -> None:
        """Reset consecutive 429 count on successful response."""
        self._consecutive_429s = 0

    def stats(self) -> Dict:
        return {
            "requests_last_min": len(self._timestamps),
            "consecutive_429s": self._consecutive_429s,
            "block_until": datetime.fromtimestamp(self._block_until).isoformat() if self._block_until > 0 else "none",
        }

# Shared rate limiter instance
_limiter = RateLimiter()

# ---------------------------------------------------------------------------
# Progress tracking helpers (module-level counters)
# ---------------------------------------------------------------------------
_progress_start = 0.0
_progress_api_calls = 0
_progress_skipped = 0

def _tick_api():
    global _progress_api_calls
    _progress_api_calls += 1

def _tick_skip():
    global _progress_skipped
    _progress_skipped += 1

# ---------------------------------------------------------------------------
# User-Agent
# ---------------------------------------------------------------------------

def get_user_agent() -> str:
    ua = os.environ.get("SEC_EDGAR_UA")
    if ua:
        return ua
    if USER_AGENT_FILE.exists():
        return USER_AGENT_FILE.read_text().strip()
    print("SEC EDGAR requires a User-Agent with a valid email address.")
    email = input("Enter your email address: ").strip()
    if not email or "@" not in email:
        print("Error: Invalid email", file=sys.stderr)
        sys.exit(1)
    ua = f"{email}/1.0"
    USER_AGENT_FILE.write_text(ua)
    return ua

# ---------------------------------------------------------------------------
# HTTP with retries
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

def _request_with_retry(url: str, timeout: int = 30, method: str = "GET") -> requests.Response:
    """Make HTTP request with exponential backoff retry for 429/503 errors."""
    max_retries = 5
    for attempt in range(max_retries):
        try:
            resp = _session.request(method, url, timeout=timeout)
            if resp.status_code == 429:
                _limiter.acquire(is_429=True)
                continue
            if resp.status_code == 503:
                delay = min(1.0 * (2 ** attempt) + 0.5, 5.0)
                print(f"    ⚠ 503 Service Unavailable. Retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})", file=sys.stderr)
                time.sleep(delay)
                continue
            if resp.status_code >= 500:
                delay = 2.0 * (2 ** attempt)
                print(f"    ⚠ Server error {resp.status_code}. Retrying in {delay:.1f}s", file=sys.stderr)
                time.sleep(delay)
                continue
            resp.raise_for_status()
            _limiter.mark_success()
            return resp
        except requests.exceptions.Timeout:
            delay = 1.0 * (2 ** attempt)
            print(f"    ⚠ Timeout. Retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})", file=sys.stderr)
            time.sleep(delay)
        except requests.exceptions.ConnectionError as e:
            delay = 1.0 * (2 ** attempt)
            print(f"    ⚠ Connection error: {e}. Retrying in {delay:.1f}s", file=sys.stderr)
            time.sleep(delay)

    print(f"    ✗ Failed after {max_retries} retries: {url}", file=sys.stderr)
    sys.exit(1)

def _get(url: str, timeout: int = 30) -> requests.Response:
    resp = _request_with_retry(url, timeout=timeout)
    return resp

# ---------------------------------------------------------------------------
# Ticker → CIK
# ---------------------------------------------------------------------------

def ticker_to_cik(ticker: str, ua: str, refresh: bool = False) -> Optional[int]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    if not refresh and TICKERS_CACHE.exists():
        data = json.loads(TICKERS_CACHE.read_text())
    else:
        url = f"{EDGAR_BASE}/files/company_tickers.json"
        resp = _get(url, timeout=60)
        data = resp.json()
        TICKERS_CACHE.write_text(json.dumps(data))

    ticker_upper = ticker.upper()
    for entry in data.values():
        if entry.get("ticker", "").upper() == ticker_upper:
            return int(entry["cik_str"])
    return None

# ---------------------------------------------------------------------------
# Get all submissions (with pagination)
# ---------------------------------------------------------------------------

def get_all_filings(cik: int, ua: str, refresh: bool = False) -> List[Dict]:
    cik_padded = str(cik).zfill(10)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    all_filings = []

    # Main submissions file
    main_cache = CACHE_DIR / f"submissions_{cik_padded}.json"
    if refresh or not main_cache.exists():
        url = f"{DATA_BASE}/submissions/CIK{cik_padded}.json"
        try:
            resp = _get(url, timeout=30)
            main_cache.write_bytes(resp.content)
            _tick_api()
        except Exception as e:
            print(f"  Error downloading submissions: {e}", file=sys.stderr)
            return []

    data = json.loads(main_cache.read_text())

    def extract(recent):
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        primary_docs = recent.get("primaryDocument", [])
        return [
            {"form": f, "date": d, "accession": a, "primary_doc": p}
            for f, d, a, p in zip(forms, dates, accessions, primary_docs)
        ]

    all_filings.extend(extract(data["filings"]["recent"]))

    # Historical pages (pagination)
    for file_info in data.get("filings", {}).get("files", []):
        filename = file_info["name"]
        cache_file = CACHE_DIR / f"submissions_{cik_padded}_{filename}"

        if refresh or not cache_file.exists():
            url = f"{DATA_BASE}/submissions/{filename}"
            try:
                print(f"  Downloading historical page {filename}")
                resp = _get(url, timeout=30)
                cache_file.write_bytes(resp.content)
                _tick_api()
            except Exception as e:
                print(f"  Error downloading {filename}: {e}", file=sys.stderr)
                continue

        page_data = json.loads(cache_file.read_text())
        all_filings.extend(extract(page_data))

    return all_filings

# ---------------------------------------------------------------------------
# Filter filings
# ---------------------------------------------------------------------------

def filter_filings(filings: List[Dict], forms: List[str]) -> List[Dict]:
    forms_set = set(forms)
    return [f for f in filings if f["form"] in forms_set]

# ---------------------------------------------------------------------------
# Get filing file list from index page
# ---------------------------------------------------------------------------

def get_filing_files(cik: int, accession: str, ua: str) -> List[str]:
    accession_clean = accession.replace("-", "")
    headers = {"User-Agent": ua}

    # Try the JSON index first (EDGAR's preferred machine-readable index)
    index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.json"
    try:
        resp = _get(index_url, timeout=30)
        _tick_api()
        data = resp.json()
        items = data.get("directory", {}).get("item", [])
        files = [item["name"] for item in items if item.get("name")]
        if files:
            return files
    except requests.HTTPError as e:
        if e.response.status_code != 404:
            print(f"    Error fetching filing index: {e}", file=sys.stderr)
            return []
    except Exception as e:
        print(f"    Error fetching filing index.json: {e}", file=sys.stderr)

    # Fallback: parse the HTML index page
    index_url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_clean}/{accession}-index.htm"
    try:
        resp = _get(index_url, timeout=30)
        _tick_api()

        pattern = rf'href="[^"]*/Archives/edgar/data/{cik}/{accession_clean}/([^"#?]+)"'
        matches = re.findall(pattern, resp.text)

        seen = set()
        files = []
        for m in matches:
            name = m.strip()
            if not name or "/" in name or name in seen:
                continue
            seen.add(name)
            files.append(name)
        return files
    except Exception as e:
        print(f"    Error getting filing index: {e}", file=sys.stderr)
        return []

# ---------------------------------------------------------------------------
# Download filing
# ---------------------------------------------------------------------------

def download_filing(cik: int, filing: Dict, output_dir: Path, ua: str, force: bool) -> List[Path]:
    form = filing["form"]
    accession = filing["accession"]
    accession_clean = accession.replace("-", "")

    form_dir = form.replace(" ", "-").replace("/", "-")
    filing_dir = output_dir / form_dir / accession

    # If the entire filing directory exists and not forcing, skip entirely
    if filing_dir.exists() and not force:
        existing = list(filing_dir.rglob("*"))
        if any(f.is_file() for f in existing):
            return []

    files = get_filing_files(cik, accession, ua)
    if not files:
        return []

    downloaded = []
    for filename in files:
        if not filename or ".." in filename:
            continue

        file_path = filing_dir / filename
        if file_path.exists() and not force:
            continue

        filing_dir.mkdir(parents=True, exist_ok=True)
        url = f"{EDGAR_BASE}/Archives/edgar/data/{cik}/{accession_clean}/{filename}"

        try:
            resp = _get(url, timeout=60)
            file_path.write_bytes(resp.content)
            _tick_api()
            downloaded.append(file_path)
        except Exception as e:
            print(f"      Error downloading {filename}: {e}", file=sys.stderr)

    return downloaded

# ---------------------------------------------------------------------------
# Update index
# ---------------------------------------------------------------------------

def update_index(output_dir: Path, filings: List[Dict]):
    index_path = output_dir / "filings_index.json"
    index_data = {
        "last_updated": datetime.now().isoformat(),
        "total_filings": len(filings),
        "filings": [
            {
                "form": f["form"],
                "date": f["date"],
                "accession": f["accession"],
                "directory": f"{f['form'].replace(' ', '-').replace('/', '-')}/{f['accession']}",
            }
            for f in filings
        ],
    }
    index_path.write_text(json.dumps(index_data, indent=2))

# ---------------------------------------------------------------------------
# Progress tracking
# ---------------------------------------------------------------------------

_progress_start = time.time()
_progress_requests = 0

def update_progress() -> None:
    global _progress_requests, _progress_start
    _progress_requests += 1
    elapsed = time.time() - _progress_start
    rpm = (_progress_requests / elapsed * 60) if elapsed > 0 else 0
    stats = _limiter.stats()
    print(f"    [req #{_progress_requests} | {rpm:.1f} req/min | 429s: {stats['consecutive_429s']}]", end="", flush=True)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Download SEC filings from EDGAR")
    parser.add_argument("ticker", help="Stock ticker symbol")
    parser.add_argument("--forms", default=",".join(DEFAULT_FORMS),
                        help="Comma-separated form types (default: all major types)")
    parser.add_argument("--force", action="store_true", help="Re-download existing files")
    parser.add_argument("--refresh-cache", action="store_true", help="Refresh cached metadata from EDGAR")
    parser.add_argument("--output-dir", help="Override output directory")
    parser.add_argument("--max-delay", type=float, default=MAX_DELAY,
                        help=f"Maximum backoff delay on 429s (default: {MAX_DELAY}s)")
    parser.add_argument("--min-delay", type=float, default=MIN_DELAY,
                        help=f"Minimum delay between requests (default: {MIN_DELAY}s)")
    parser.add_argument("--base-delay", type=float, default=BASE_DELAY,
                        help=f"Base delay between requests (default: {BASE_DELAY}s)")
    parser.add_argument("--max-rpm", type=int, default=MAX_REQUESTS_PER_MINUTE,
                        help=f"Max requests per minute (default: {MAX_REQUESTS_PER_MINUTE})")
    parser.add_argument("--concurrency", type=int, default=1,
                        help="Number of concurrent downloads (default: 1, use 2-3 for speed)")

    args = parser.parse_args()

    # Update rate limiter config
    _limiter.max_delay = args.max_delay
    _limiter.min_delay = args.min_delay
    _limiter.base_delay = args.base_delay
    _limiter.max_per_minute = args.max_rpm

    ua = get_user_agent()

    print(f"SEC Filings Downloader")
    print(f"  Ticker: {args.ticker.upper()}")
    print(f"  Rate limit: {args.max_rpm} req/min, base delay {args.base_delay}s, max backoff {args.max_delay}s")
    print(f"  Cache: {CACHE_DIR}")
    print()

    print(f"Looking up CIK for {args.ticker.upper()}")
    try:
        cik = ticker_to_cik(args.ticker, ua, args.refresh_cache)
    except Exception as e:
        print(f"Error looking up CIK: {e}", file=sys.stderr)
        sys.exit(1)

    if not cik:
        print(f"Error: Could not find CIK for {args.ticker}", file=sys.stderr)
        sys.exit(1)
    print(f"CIK: {cik}\n")

    output_dir = Path(args.output_dir) if args.output_dir else default_output_dir(args.ticker)
    output_dir.mkdir(parents=True, exist_ok=True)

    forms = [f.strip() for f in args.forms.split(",")]

    print(f"Fetching all filings...")
    try:
        all_filings = get_all_filings(cik, ua, args.refresh_cache)
    except Exception as e:
        print(f"Error fetching filings: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Total filings: {len(all_filings)}")

    filtered = filter_filings(all_filings, forms)
    print(f"Filtered to {len(filtered)} filings matching {forms}\n")

    if not filtered:
        print("No filings match criteria")
        sys.exit(0)

    print(f"Downloading...")
    total_downloaded = 0
    total_errors = 0
    global _progress_start, _progress_api_calls, _progress_skipped
    _progress_start = time.time()
    _progress_api_calls = 0
    _progress_skipped = 0

    for i, filing in enumerate(filtered, 1):
        form = filing["form"]
        date = filing["date"]
        accession = filing["accession"]

        print(f"\n[{i}/{len(filtered)}] {form} filed {date}", end="")

        try:
            downloaded = download_filing(cik, filing, output_dir, ua, args.force)
            total_downloaded += len(downloaded)
            if not downloaded:
                _tick_skip()
                print(f"  Skipped (already exists)")
            else:
                print(f"  Downloaded {len(downloaded)} files")
        except Exception as e:
            total_errors += 1
            print(f"  Error: {e}", file=sys.stderr)

        if i % 20 == 0:
            stats = _limiter.stats()
            elapsed = time.time() - _progress_start
            rpm = (_progress_api_calls / elapsed * 60) if elapsed > 5 else 0
            print(f"\n    ── Rate: {stats['requests_last_min']}/min | 429s: {stats['consecutive_429s']} | Elapsed: {elapsed/60:.1f}min ──")

    # Final stats
    stats = _limiter.stats()
    elapsed = time.time() - _progress_start
    print(f"\n\n{'='*60}")
    print(f"✓ COMPLETE")
    print(f"{'='*60}")
    print(f"  Total filings processed: {len(filtered)}")
    print(f"  Files downloaded: {total_downloaded}")
    print(f"  Filings skipped (up to date): {_progress_skipped}")
    print(f"  Errors: {total_errors}")
    print(f"  Time elapsed: {elapsed/60:.1f} minutes")
    print(f"  Final rate: {stats['requests_last_min']}/min | 429s remaining: {stats['consecutive_429s']}")
    print(f"  Output: {output_dir}")
    print(f"{'='*60}")

    update_index(output_dir, filtered)

if __name__ == "__main__":
    main()
