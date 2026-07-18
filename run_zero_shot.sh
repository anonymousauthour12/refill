#!/bin/bash
# run_zero_shot.sh — runs the zero-shot baseline (strategies 6, 7, 8) on 3 models sequentially.
#
# Strategy 6 = zero-shot S1 context (schema only)
# Strategy 7 = zero-shot S3 context (schema + stats + sample rows)
# Strategy 8 = zero-shot S2 context (schema + stats + distinct values)
#
# 9 experiments in total, run one after another.
# Each experiment uses multiple parallel workers internally.
#
# Usage:
#   ./run_zero_shot.sh [gt_file]
#
# Default gt_file: new_gt/all_surely_computed_and_surely_non_computed.csv

GT_FILE="${1:-new_gt/all_surely_computed_and_surely_non_computed.csv}"

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

BENCH_LOG="$LOG_DIR/zero_shot_$(date +%Y%m%d_%H%M%S).log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$BENCH_LOG"; }

log "=========================================="
log "  Zero-shot baseline: 9 experiments"
log "  GT file : gt/$GT_FILE"
log "=========================================="

# Run one experiment: ./run_workers.sh <gt_file> <model> <strategy> <workers>
run_exp() {
    local MODEL="$1"
    local STRATEGY="$2"
    local WORKERS="$3"

    log "START  model=$MODEL  strategy=$STRATEGY  workers=$WORKERS"
    start_ts=$(date +%s)

    ./run_workers.sh "$GT_FILE" "$MODEL" "$STRATEGY" "$WORKERS" \
        2>&1 | tee -a "$LOG_DIR/${MODEL}_s${STRATEGY}.log"

    elapsed=$(( $(date +%s) - start_ts ))
    elapsed_fmt=$(printf '%dh %dm %ds' $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60)))
    log "DONE   model=$MODEL  strategy=$STRATEGY  elapsed=$elapsed_fmt"
}

# ── 9 experiments, sequential ─────────────────────────────────────
# Worker counts: zero-shot = 1 LLM call per column → higher parallelism is safe.
# S7/S8 use larger context than S6 → slightly fewer workers.
# gpt-4o and gpt-5 do NOT overlap here (sequential), so each can use full Azure quota.

run_exp "Llama-3.3-70B-Instruct"  6  30
run_exp "Llama-3.3-70B-Instruct"  7  20
run_exp "Llama-3.3-70B-Instruct"  8  20
run_exp "gpt-4o"                  6  25
run_exp "gpt-4o"                  7  15
run_exp "gpt-4o"                  8  15
run_exp "gpt-5"                   6  25
run_exp "gpt-5"                   7  15
run_exp "gpt-5"                   8  15

log "=========================================="
log "All 9 zero-shot experiments completed."
log "=========================================="
