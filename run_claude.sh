#!/bin/bash
# run_claude.sh — runs claude-opus-4-7, strategies 1→4 sequentially.
# If two API keys are configured, GT is split in half automatically (key1/key2).
#
# Usage:
#   ./run_claude.sh [gt_file]

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
MODEL="claude-opus-4-7"
IFS=',' read -ra STRATEGIES <<< "${2:-1,2,3,4}"
# Workers per strategy — single endpoint, 250K TPM limit.
# 3 total was fine for S1-S3; S4 reduced to 2 due to heavier context.
declare -A WORKERS_BY_STRATEGY=([1]=6 [2]=6 [3]=4 [4]=4)

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
BENCH_LOG="$LOG_DIR/${MODEL}_$(date +%Y%m%d_%H%M%S).log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$BENCH_LOG"; }

log "=========================================="
log "  Model    : $MODEL"
log "  GT file  : gt/$GT_FILE"
log "=========================================="

for strategy in "${STRATEGIES[@]}"; do
    WORKERS="${WORKERS_BY_STRATEGY[$strategy]}"
    log "START  strategy=$strategy  workers=$WORKERS/key ($(( WORKERS * 2 )) total)"
    start_ts=$(date +%s)

    ./run_workers.sh "$GT_FILE" "$MODEL" "$strategy" "$WORKERS" \
        2>&1 | tee -a "$LOG_DIR/${MODEL}_s${strategy}.log"

    elapsed=$(( $(date +%s) - start_ts ))
    elapsed_fmt=$(printf '%dh %dm %ds' $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60)))
    log "DONE   strategy=$strategy  elapsed=$elapsed_fmt"
done

log "=========================================="
log "$MODEL benchmark completed."
log "=========================================="
