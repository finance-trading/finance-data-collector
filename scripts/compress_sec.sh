#!/bin/bash
# Compress sec/<TICKER> into sec_archive/<TICKER>.tar.zst one ticker at a time.
# Each ticker is fully verified (archive integrity + file count) before its
# source directory is removed, so a failure never loses data.
#
# Resume-safe: tickers that already have a verified archive are skipped.

set -uo pipefail

SEC_DIR="$HOME/WorkSpace/finance/finance-data-collector/sec"
OUT_DIR="$HOME/WorkSpace/finance/finance-data-collector/sec_archive"
LOG="$OUT_DIR/compress.log"
LEVEL=3          # zstd level; 3 is the speed/ratio sweet spot for text
THREADS=0        # 0 = use all cores

mkdir -p "$OUT_DIR"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

# Skip the cache dir; it is rebuilt on demand and only ~107MB.
cd "$SEC_DIR" || exit 1

TICKERS=($(find . -mindepth 1 -maxdepth 1 -type d ! -name '.*' -exec basename {} \; | sort))
TOTAL=${#TICKERS[@]}
log "=== START: $TOTAL tickers, zstd level $LEVEL ==="

DONE=0; SKIPPED=0; FAILED=0
TOTAL_BEFORE=$(du -sk "$SEC_DIR" | cut -f1)

for T in "${TICKERS[@]}"; do
    SRC="$SEC_DIR/$T"
    DST="$OUT_DIR/$T.tar.zst"
    [ -d "$SRC" ] || { SKIPPED=$((SKIPPED+1)); continue; }

    # Already archived and verified in a previous run -> skip.
    if [ -f "$DST" ]; then
        if zstd -tq "$DST" 2>/dev/null; then
            log "SKIP  $T (archive exists and is valid)"
            SKIPPED=$((SKIPPED+1))
            continue
        fi
        log "WARN  $T has a corrupt archive, re-compressing"
        rm -f "$DST"
    fi

    BEFORE_KB=$(du -sk "$SRC" | cut -f1)
    N_FILES=$(find "$SRC" -type f | wc -l | tr -d ' ')

    log " compressing $T (${BEFORE_KB}KB, $N_FILES files)"

    # Write to a .part file so an interrupted run never leaves a
    # truncated archive that a later run would mistake for complete.
    if ! tar -cf - -C "$SEC_DIR" "$T" 2>>"$LOG" | zstd -T"$THREADS" -"$LEVEL" -q -o "$DST.part"; then
        log "ERROR $T compression failed, source intact"
        rm -f "$DST.part"
        FAILED=$((FAILED+1))
        continue
    fi

    # --- Verification gate: nothing is deleted unless all checks pass ---

    # 1. archive passes its own checksum
    if ! zstd -tq "$DST.part" 2>/dev/null; then
        log "ERROR $T failed zstd integrity check, source intact"
        rm -f "$DST.part"
        FAILED=$((FAILED+1))
        continue
    fi

    # 2. every file made it into the archive
    N_IN=$(zstd -dc "$DST.part" 2>/dev/null | tar -tf - 2>/dev/null | grep -vc '/$')
    if [ "$N_IN" != "$N_FILES" ]; then
        log "ERROR $T file count mismatch (src=$N_FILES archive=$N_IN), source intact"
        rm -f "$DST.part"
        FAILED=$((FAILED+1))
        continue
    fi

    # 3. archive unpacks cleanly (catches truncated streams)
    if ! zstd -dc "$DST.part" 2>/dev/null | tar -tf - >/dev/null 2>&1; then
        log "ERROR $T archive does not unpack cleanly, source intact"
        rm -f "$DST.part"
        FAILED=$((FAILED+1))
        continue
    fi

    # All checks passed -> promote and drop the source.
    mv "$DST.part" "$DST"
    AFTER_KB=$(du -sk "$DST" | cut -f1)
    rm -rf "$SRC"

    DONE=$((DONE+1))
    log "OK     $T  $((BEFORE_KB/1024))MB -> $((AFTER_KB/1024))MB  (freed ~$(( (BEFORE_KB-AFTER_KB)/1024 ))MB)"
done

TOTAL_AFTER=$(du -sk "$SEC_DIR" 2>/dev/null | cut -f1)
log "=== DONE: compressed=$DONE skipped=$SKIPPED failed=$FAILED ==="
log "sec/  : $((TOTAL_BEFORE/1024/1024))GB -> $((TOTAL_AFTER/1024/1024))GB"
log "archive total: $(du -sh "$OUT_DIR" | cut -f1)"
df -h /System/Volumes/Data | tail -1 | tee -a "$LOG"
