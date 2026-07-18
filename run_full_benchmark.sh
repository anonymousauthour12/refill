#!/bin/bash
#
# run_full_benchmark.sh — runs all 16 combinations sequentially.
# Order: claude → llama → gpt-4o → gpt-5, each with strategies 1→2→3→4.
# All runs use prompt template 3, 30 workers, early_stopping=False.
#
# Usage:
#   ./run_full_benchmark.sh [gt_file] [workers]
#
# Example:
#   ./run_full_benchmark.sh all_surely_computed_and_surely_non_computed.csv 30

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
STRATEGIES=(1 2 3 4)

# Workers per model based on TPM limits:
#   claude-opus-4-7       250K TPM  →  2 workers
#   Llama-3.3-70B         2M TPM    → 15 workers
#   gpt-4o / gpt-5        39M TPM   → 30 workers
declare -A MODEL_WORKERS=(
    ["claude-opus-4-7"]=2
    ["Llama-3.3-70B-Instruct"]=15
    ["gpt-4o"]=30
    ["gpt-5"]=30
)

MODELS=(
    "claude-opus-4-7"
    "Llama-3.3-70B-Instruct"
    "gpt-4o"
    "gpt-5"
)

LOG_DIR="logs"
mkdir -p "$LOG_DIR"
BENCH_LOG="$LOG_DIR/benchmark_$(date +%Y%m%d_%H%M%S).log"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$BENCH_LOG"; }

log "=========================================="
log "Full benchmark started"
log "  GT file   : gt/$GT_FILE"
log "  Models    : ${MODELS[*]}"
log "  Strategies: ${STRATEGIES[*]}"
log "=========================================="

total=${#MODELS[@]}
m_idx=0

for model in "${MODELS[@]}"; do
    (( m_idx++ ))
    workers=${MODEL_WORKERS[$model]}
    for strategy in "${STRATEGIES[@]}"; do

        log "[$m_idx/${total}] START  model=$model  strategy=$strategy  workers=$workers"
        start_ts=$(date +%s)

        ./run_workers.sh "$GT_FILE" "$model" "$strategy" "$workers" \
            >> "$LOG_DIR/${model}_s${strategy}.log" 2>&1

        exit_code=$?
        end_ts=$(date +%s)
        elapsed=$(( end_ts - start_ts ))
        elapsed_fmt=$(printf '%dh %dm %ds' $((elapsed/3600)) $((elapsed%3600/60)) $((elapsed%60)))

        if [[ $exit_code -eq 0 ]]; then
            log "[$m_idx/${total}] DONE   model=$model  strategy=$strategy  elapsed=$elapsed_fmt"
        else
            log "[$m_idx/${total}] FAILED model=$model  strategy=$strategy  exit=$exit_code  elapsed=$elapsed_fmt"
        fi

    done
done

log "=========================================="
log "Full benchmark completed."
log "=========================================="
