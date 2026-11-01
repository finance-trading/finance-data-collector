#!/bin/bash
# Download SEC filings for all companies in layers.json
# Skips image files with --no-images
# Usage: download_all_sec.sh [watchlist]   # "watchlist" runs only the strategy watchlist tickers

# AI value-chain universe
TICKERS="AAPL ADBE ACN ADI ADSK AI ALAB AMAT AMD AMZN ANET APP ARM ASML AVGO BABA BKNG CDNS CEG CHTR CIEN COHR COST CRDO CRM CRWD CRWV CSCO DDOG DELL DOCU DUOL ENTG EPAM ESTC ETN FICO FTNT FRSH GEV GFS GOOG GOOGL GTLB HPE HPQ IBM INFY INTC INTU IDXX ISRG KEYS KLAC LITE LIN LRCX LULU MBLY MDB META MNDY MPWR MRVL MSFT MU NBIS NET NFLX NOK NOW NRG NVDA OKTA ON ONTO ORCL PAYX PANW PATH PDD PLTR PWR QCOM RBLX RDDT RMD ROL ROP SHOP SMCI SNDK SNPS SONO SOUN SPOT STX T TER TLN TMUS TSLA TSM TTD TTWO TXN U UBER V VRSK VRSN VRT VRTX VST VZ WDC ZS"

# Core-quality watchlist from Docs/strategy/core-quality-watchlist-v0.md
WATCHLIST_TICKERS="MSFT GOOG META AAPL ADBE INTU ADSK CDNS FTNT VRSN FICO VRSK AMAT MPWR QCOM IDXX VRTX RMD ISRG BKNG LULU PAYX ROL V COST CRM NOW ROP LIN AMZN ORCL"

if [ "$1" = "watchlist" ]; then
    TICKERS="$WATCHLIST_TICKERS"
    LABEL="strategy watchlist"
else
    LABEL="AI value-chain universe"
fi

# Conservative SEC rate settings. Full defaults (10 rpm / 2s max backoff) trigger
# intermittent EDGAR IP blocks on the larger tickers (~450+ filings), which aborts
# the run mid-list. Lower rpm + longer backoff + cooldown below keeps the batch going.
MAX_RPM=8
MAX_DELAY=30
COOLDOWN_SECONDS=90

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$SCRIPT_DIR/.venv/bin/python"
DOWNLOAD_SCRIPT="$SCRIPT_DIR/.agents/skills/sec-filings-download/scripts/download_sec_filings.py"

TOTAL=$(echo $TICKERS | wc -w | tr -d ' ')
COUNT=0
FAILED=""

echo "========================================="
echo "  SEC Filings Batch Download ($LABEL)"
echo "  Total tickers: $TOTAL"
echo "========================================="
echo ""

for TICKER in $TICKERS; do
    COUNT=$((COUNT + 1))
    echo ""
    echo "[$COUNT/$TOTAL] ========== $TICKER =========="
    echo ""

    $PYTHON "$DOWNLOAD_SCRIPT" "$TICKER" --no-images --max-rpm "$MAX_RPM" --max-delay "$MAX_DELAY" 2>&1
    RC=$?
    # cooldown between tickers to avoid prolonged EDGAR IP bans
    sleep "$COOLDOWN_SECONDS"

    if [ $RC -ne 0 ]; then
        echo "  ✗ FAILED: $TICKER"
        FAILED="$FAILED $TICKER"
    else
        echo "  ✓ DONE: $TICKER"
    fi
done

echo ""
echo "========================================="
echo "  BATCH COMPLETE"
echo "  Processed: $TOTAL"
if [ -n "$FAILED" ]; then
    echo "  Failed:$FAILED"
fi
echo "========================================="
