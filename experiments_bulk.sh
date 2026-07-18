#!/bin/bash

gt_file="selected_cc_20.csv"
cc_filter=5

./experiments.sh "$gt_file" $cc_filter 4 gpt-5 3 False
./experiments.sh "$gt_file" $cc_filter 4 gpt-4o 3 False
./experiments.sh "$gt_file" $cc_filter 4 model-router 3 False
./experiments.sh "$gt_file" $cc_filter 4 claude-opus-4-7 3 False
./experiments.sh "$gt_file" $cc_filter 4 Llama-3.3-70B-Instruct 3 False


./experiments.sh "$gt_file" $cc_filter 4 gpt-5 2 False
./experiments.sh "$gt_file" $cc_filter 4 gpt-4o 2 False
./experiments.sh "$gt_file" $cc_filter 4 model-router 2 False
./experiments.sh "$gt_file" $cc_filter 4 claude-opus-4-7 2 False
./experiments.sh "$gt_file" $cc_filter 4 Llama-3.3-70B-Instruct 2 False

