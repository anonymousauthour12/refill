#!/bin/bash
#
# run_all_models.sh — run Claude, GPT-4o, and Llama in parallel, each on its own endpoint.
#
# Usage:
#   ./run_all_models.sh <gt_file> <strategy> [workers_per_model]
#
# Submit via at:
#   at now -f ./run_all_models.sh    (starts immediately, survives logout)
#   at 22:00 -f ./run_all_models.sh  (starts at 10 PM)

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
STRATEGY="${2:-4}"
WORKERS="${3:-2}"

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# Activate conda so python/packages are available
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate base

cd "$PROJECT_DIR"

echo "[$(date)] Starting 3-model parallel run" | tee "$LOG_DIR/run_all.log"

./run_workers.sh "$GT_FILE" claude-opus-4-7          "$STRATEGY" "$WORKERS" \
    > "$LOG_DIR/claude.log"  2>&1 &
PID_CLAUDE=$!

./run_workers.sh "$GT_FILE" gpt-4o                   "$STRATEGY" "$WORKERS" \
    > "$LOG_DIR/gpt4o.log"   2>&1 &
PID_GPT4O=$!

./run_workers.sh "$GT_FILE" Llama-3.3-70B-Instruct   "$STRATEGY" "$WORKERS" \
    > "$LOG_DIR/llama.log"   2>&1 &
PID_LLAMA=$!

echo "[$(date)] PIDs — Claude: $PID_CLAUDE  GPT-4o: $PID_GPT4O  Llama: $PID_LLAMA" \
    | tee -a "$LOG_DIR/run_all.log"

wait $PID_CLAUDE $PID_GPT4O $PID_LLAMA
echo "[$(date)] All 3 runs finished." | tee -a "$LOG_DIR/run_all.log"
