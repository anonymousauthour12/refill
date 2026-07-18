#!/bin/bash
# run_3_models_concurrently.sh — launches Llama, gpt-4o, and gpt-5 concurrently (no Claude).
# Uses `at` so experiments keep running after the terminal is closed.
# Output is saved to log files under logs/.
#
# Usage:
#   ./run_3_models_concurrently.sh [gt_file] [strategies]

GT_FILE="${1:-all_surely_computed_and_surely_non_computed.csv}"
# Optional second argument: comma-separated strategies, e.g. "3,4" or "1,2,3,4"
STRATEGIES_ARG="${2:-1,2,3,4}"

echo "./run_llama.sh $GT_FILE $STRATEGIES_ARG"  | at now + 1 minute
echo "./run_gpt4o.sh $GT_FILE $STRATEGIES_ARG"  | at now + 2 minutes
echo "./run_gpt5.sh $GT_FILE $STRATEGIES_ARG"   | at now + 3 minutes

echo "Scheduled:"
echo "  +1 min : run_llama.sh   $GT_FILE  strategies=$STRATEGIES_ARG"
echo "  +2 min : run_gpt4o.sh   $GT_FILE  strategies=$STRATEGIES_ARG"
echo "  +3 min : run_gpt5.sh    $GT_FILE  strategies=$STRATEGIES_ARG"
echo ""
echo "Logs will be written to logs/ — monitor with:"
echo "  tail -f logs/Llama-3.3-70B-Instruct_s3.log"
echo "  tail -f logs/gpt-4o_s3.log"
echo "  tail -f logs/gpt-5_s3.log"
