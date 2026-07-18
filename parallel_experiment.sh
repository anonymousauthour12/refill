#!/bin/bash
#
# parallel_experiment.sh — like experiment.sh but runs N columns in parallel.
#
# Usage:
#   ./parallel_experiment.sh <gt_file> <cc_filter> <bulk_file> <strategy> <model> <prompt_template> <early_stopping> [workers]
#
# Example (2 workers, safe for 250K TPM):
#   ./parallel_experiment.sh selected_cc_20.csv 5 bulk.txt 4 claude-opus-4-7 3 True 2

gt_file_name="$1"
cc_filter=${2:-5}
bulk_experiments_file_path="$3"
strategy="$4"
model="$5"
prompt_template="$6"
early_stopping="$7"
workers=${8:-2}
existing_exp_dir="${9:-}"   # optional: reuse a pre-created experiment directory

# Accept either a full path (e.g. /tmp/...) or a filename relative to gt/
if [[ -f "$gt_file_name" ]]; then
    gt_file_path="$gt_file_name"
else
    gt_file_path="gt/${gt_file_name}"
fi

# ── Create experiment directory (or reuse existing) ───────────────
prepare_experiment() {
    local target_dir="experiments"
    mkdir -p "$target_dir"
    local last_index
    last_index=$(find "$target_dir" -maxdepth 1 -type d -name 'experiment_*' \
        | sed 's/.*experiment_//' | sort -n | tail -n 1)
    local new_index=$(( ${last_index:-0} + 1 ))
    [[ -z "$last_index" ]] && new_index=0
    local exp_dir="$target_dir/experiment_$new_index"
    mkdir -p "$exp_dir"
    cp config.yaml "$exp_dir/"
    echo "$exp_dir"
}

if [[ -n "$existing_exp_dir" ]]; then
    experiment_dir="$existing_exp_dir"
else
    experiment_dir=$(prepare_experiment)
fi
echo "Experiment dir : $experiment_dir"
echo "Workers        : $workers"
echo "Model          : $model"
echo "Prompt template: $prompt_template"
echo "Strategy       : $strategy"

export experiment_dir strategy model prompt_template early_stopping bulk_experiments_file_path

# ── Worker function (runs in a subshell via xargs) ────────────────
run_one_column() {
    local database="$1" table="$2" column="$3"

    # Each column gets its own work dir — no shared-file conflicts
    local col_dir="${experiment_dir}/${database}_${table}_${column}"
    mkdir -p "$col_dir"
    cp "${experiment_dir}/config.yaml" "$col_dir/"

    # Resume: skip if already completed
    if [[ -f "${col_dir}/reported_accuracy_${database}_${table}_${column}.csv" ]]; then
        echo "[SKIP]    $database.$table.$column"
        cp "$col_dir"/reported_accuracy_*.csv "$experiment_dir/" 2>/dev/null
        return
    fi

    local model_arg="" pt_arg="" es_arg=""
    [[ -n "$model" ]]           && model_arg="--model $model"
    [[ -n "$prompt_template" ]] && pt_arg="--prompt_template $prompt_template"
    [[ -n "$early_stopping" ]]  && es_arg="--early_stopping $early_stopping"

    echo "[START]   $database.$table.$column"

    timeout -k 30 3600 python main.py \
        --steps 1 5 \
        --db_name "$database" \
        --table_name "$table" \
        --column_name "$column" \
        --work_space "$col_dir" \
        --bulk_experiments_file_path "$bulk_experiments_file_path" \
        --strategy "$strategy" \
        $model_arg $pt_arg $es_arg

    local exit_code=$?

    # Shell-level MySQL cleanup: if the Python process was killed by SIGKILL
    # (e.g. the 30-second grace period after SIGTERM expired), its cleanup
    # code never ran and the MySQL query may still be executing as a zombie.
    # The active thread ID was written to a file by db_layer._write_thread_id_file()
    # before each query; read it and issue KILL now.
    local thread_file="${col_dir}/active_mysql_thread.txt"
    local kill_log="${experiment_dir}/kill_trace.log"
    local ts
    ts=$(date '+%Y-%m-%d %H:%M:%S')
    local col_id="${database}.${table}.${column}"
    if [[ -f "$thread_file" ]]; then
        local tid
        tid=$(cat "$thread_file" 2>/dev/null)
        if [[ -n "$tid" ]]; then
            # Thread file still exists → Python was SIGKILL'd before its finally block ran
            [[ -f "$kill_log" ]] || echo "timestamp,event,tid,column,elapsed_sec,detail" >> "$kill_log"
            echo "${ts},SIGKILL_DETECTED,${tid},${col_id},,Python exited without deleting thread file" >> "$kill_log"
            echo "${ts},SHELL_KILL_ATTEMPT,${tid},${col_id},,source=shell_cleanup" >> "$kill_log"
            if mysql -u root -p777 --connect-timeout=5 -e "KILL ${tid};" 2>/dev/null; then
                echo "${ts},SHELL_KILL_SUCCESS,${tid},${col_id},,success=True | source=shell_cleanup" >> "$kill_log"
                # Verify: wait 1 second then check if thread is actually gone
                sleep 1
                ts=$(date '+%Y-%m-%d %H:%M:%S')
                still_running=$(mysql -u root -p777 --connect-timeout=5 --skip-column-names -e \
                    "SELECT CONCAT('command=',command,' | state=',state,' | time=',time,'s') FROM information_schema.processlist WHERE id=${tid};" \
                    2>/dev/null)
                if [[ -z "$still_running" ]]; then
                    echo "${ts},KILL_VERIFY_DEAD,${tid},${col_id},,success=True | source=shell_cleanup | thread not in processlist" >> "$kill_log"
                else
                    echo "${ts},KILL_VERIFY_STILL_RUNNING,${tid},${col_id},,success=False | source=shell_cleanup | ${still_running}" >> "$kill_log"
                fi
            else
                echo "${ts},SHELL_KILL_FAILED,${tid},${col_id},,success=False | source=shell_cleanup" >> "$kill_log"
            fi
        fi
        rm -f "$thread_file"
    fi
    if [[ $exit_code -eq 124 ]]; then
        echo "[TIMEOUT] $database.$table.$column" | tee -a "${experiment_dir}/failed.log"
    elif [[ $exit_code -ne 0 ]]; then
        echo "[FAILED]  $database.$table.$column (exit $exit_code)" | tee -a "${experiment_dir}/failed.log"
    else
        echo "[DONE]    $database.$table.$column"
    fi

    # Copy per-column result up to the shared experiment dir
    cp "$col_dir"/reported_accuracy_*.csv "$experiment_dir/" 2>/dev/null
}

export -f run_one_column

# ── Run all columns in parallel ───────────────────────────────────
tail -n +2 "$gt_file_path" \
    | awk -F'\t' -v cc="$cc_filter" '$4==cc {print $1"\t"$2"\t"$3}' \
    | xargs -P "$workers" -I '{}' bash -c '
        IFS=$'"'"'\t'"'"' read -r db tbl col <<< "{}"
        run_one_column "$db" "$tbl" "$col"
    '

# ── Merge time_metrics_log.csv from all col dirs ──────────────────
echo "Merging time_metrics_log.csv..."
header_written=0
for col_dir in "$experiment_dir"/*/; do
    log="${col_dir}time_metrics_log.csv"
    [[ -f "$log" ]] || continue
    if [[ $header_written -eq 0 ]]; then
        cat "$log" >> "${experiment_dir}/time_metrics_log.csv"
        header_written=1
    else
        tail -n +2 "$log" >> "${experiment_dir}/time_metrics_log.csv"
    fi
done

echo "Merging warnings.log..."
for col_dir in "$experiment_dir"/*/; do
    log="${col_dir}warnings.log"
    [[ -f "$log" ]] || continue
    cat "$log" >> "${experiment_dir}/warnings.log"
done

echo "Merging errors.jsonl..."
for col_dir in "$experiment_dir"/*/; do
    log="${col_dir}errors.jsonl"
    [[ -f "$log" ]] || continue
    cat "$log" >> "${experiment_dir}/errors.jsonl"
done

echo "Done. Results in: $experiment_dir"
[[ -f "${experiment_dir}/warnings.log" ]] && echo "Warnings logged in: ${experiment_dir}/warnings.log"
[[ -f "${experiment_dir}/errors.jsonl"  ]] && echo "Errors   logged in: ${experiment_dir}/errors.jsonl"
[[ -f "${experiment_dir}/failed.log" ]]   && echo "Failures logged in: ${experiment_dir}/failed.log"
