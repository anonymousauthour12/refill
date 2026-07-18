#!/bin/bash
#
# run_workers.sh — launch a parallel experiment run.
#
# Usage:
#   ./run_workers.sh <gt_file> <model> <strategy> [workers]
#
# Arguments:
#   gt_file   : ground-truth CSV file under gt/  (e.g. selected_cc_20.csv)
#   model     : model name                        (e.g. claude-opus-4-7 | gpt-5 | gpt-4o | Llama-3.3-70B-Instruct)
#   strategy  : data sharing strategy             (1=schema only | 2=+stats | 3=+rows | 4=smart)
#   workers   : number of parallel workers (default: 2)

GT_FILE="${1:?Usage: ./run_workers.sh <gt_file> <model> <strategy> [workers]}"
MODEL="${2:?Usage: ./run_workers.sh <gt_file> <model> <strategy> [workers]}"
STRATEGY="${3:?Usage: ./run_workers.sh <gt_file> <model> <strategy> [workers]}"
WORKERS="${4:-2}"

# Fixed settings
CC_FILTER=5
PROMPT_TEMPLATE=3
EARLY_STOPPING=False

GT_PATH="gt/${GT_FILE}"
TOTAL_ROWS=$(tail -n +2 "$GT_PATH" | wc -l)

# ── Create one shared experiment directory ────────────────────────
EXPERIMENTS_DIR="experiments"
mkdir -p "$EXPERIMENTS_DIR"
LAST_INDEX=$(find "$EXPERIMENTS_DIR" -maxdepth 1 -type d -name 'experiment_*' \
    | sed 's/.*experiment_//' | sort -n | tail -n 1)
NEW_INDEX=$(( ${LAST_INDEX:-0} + 1 ))
[[ -z "$LAST_INDEX" ]] && NEW_INDEX=0
EXPERIMENT_DIR="$EXPERIMENTS_DIR/experiment_$NEW_INDEX"
mkdir -p "$EXPERIMENT_DIR"
cp config.yaml "$EXPERIMENT_DIR/"

BULK_FILE="bulk_experiments/bulk_${MODEL}_$(date +%Y%m%d_%H%M%S).txt"
mkdir -p bulk_experiments
touch "$BULK_FILE"

echo "========================================"
echo "  Ground truth : $GT_PATH  ($TOTAL_ROWS rows)"
echo "  Model        : $MODEL"
echo "  Strategy     : $STRATEGY"
echo "  Workers      : $WORKERS"
echo "  Template     : $PROMPT_TEMPLATE"
echo "  Experiment   : $EXPERIMENT_DIR"
echo "  Bulk file    : $BULK_FILE"
echo "========================================"

./parallel_experiment.sh \
    "$GT_FILE" "$CC_FILTER" "$BULK_FILE" "$STRATEGY" \
    "$MODEL" "$PROMPT_TEMPLATE" "$EARLY_STOPPING" "$WORKERS" \
    "$EXPERIMENT_DIR"
