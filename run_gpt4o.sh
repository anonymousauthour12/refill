#!/bin/bash
# run_gpt4o.sh — runs gpt-4o, strategies 1→4 sequentially.
# If two API keys are configured, GT is split in half automatically (key1/key2).
#
# Usage:
#   ./run_gpt4o.sh [gt_file] [strategy]
#   strategy: optional integer (1-4). If omitted, all four strategies run sequentially.
#   Examples:
#     ./run_gpt4o.sh selected_cc_20.csv      # runs strategies 1,2,3,4
#     ./run_gpt4o.sh selected_cc_20.csv 3    # runs strategy 3 only

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
MODEL="gpt-4o"
IFS=',' read -ra STRATEGIES <<< "${2:-1,2,3,4}"
# Workers per strategy — single endpoint shared with gpt-5 (same Azure resource).
# When all 4 models run concurrently, gpt-4o + gpt-5 combined must stay ≤30.
# gpt-4o gets ~half: S1=13, S2=10, S3=8, S4=5.
declare -A WORKERS_BY_STRATEGY=([1]=26 [2]=20 [3]=16 [4]=10)

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
