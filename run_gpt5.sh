#!/bin/bash
# run_gpt5.sh — runs gpt-5, strategies 1→4 sequentially.
# If two API keys are configured, GT is split in half automatically (key1/key2).
#
# Usage:
#   ./run_gpt5.sh [gt_file]

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
MODEL="gpt-5"
IFS=',' read -ra STRATEGIES <<< "${2:-1,2,3,4}"
# Workers per strategy — single endpoint shared with gpt-4o (same Azure resource).
# When all 4 models run concurrently, gpt-4o + gpt-5 combined must stay ≤30.
# gpt-5 gets ~half: S1=12, S2=10, S3=7, S4=5.
declare -A WORKERS_BY_STRATEGY=([1]=24 [2]=20 [3]=14 [4]=5)

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
