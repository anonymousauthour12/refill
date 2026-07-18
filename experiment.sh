#!/bin/bash


gt_file_name="$1"
cc_filter=${2:-2}
bulk_experiments_file_path="$3"
strategy="$4"
model="$5"
prompt_template="$6"
early_stopping="$7"

gt_file_path="gt/${gt_file_name}"





prepare_experiment() {
    target_dir="experiments"
    mkdir -p "$target_dir"
    last_index=$(find "$target_dir" -maxdepth 1 -type d -name 'experiment_*' \
    | sed 's/.*experiment_//' \
    | sort -n \
    | tail -n 1)

    if [[ -z "$last_index" ]]; then
        new_index=0
    else
        new_index=$((last_index + 1))
    fi

    experiment_dir="$target_dir/experiment_$new_index"
    mkdir -p "$experiment_dir"

    #./set_default_config.sh;
    cp config.yaml "$experiment_dir/"
    
    echo $experiment_dir
}

experiment_dir=$(prepare_experiment)

#sed -i 's/^data_sharing_strategy *= *.*/data_sharing_strategy = 3/' "$experiment_dir/config.ini"

#sed -i 's/^different_formula_max_tries *= *.*/different_formula_max_tries = 1/' "$experiment_dir/config.ini"
#sed -i 's/^formula_max_subtries *= *.*/formula_max_subtries = 1/' "$experiment_dir/config.ini"

# Read the file line by line
while IFS=$'\t' read -r database table column cc; do
    if [[ "$cc_filter" -eq "$cc" ]]; then
        #python main.py --steps 1 2 5 --db_name "$database" --table_name "$table" --column_name "$column" --work_space "$experiment_dir"
        model_arg=""
        if [[ -n "$model" ]]; then
            model_arg="--model $model"
        fi
        pt_arg=""
        if [[ -n "$prompt_template" ]]; then
            pt_arg="--prompt_template $prompt_template"
        fi
        es_arg=""
        if [[ -n "$early_stopping" ]]; then
            es_arg="--early_stopping $early_stopping"
        fi
        python main.py --steps 1 5 --db_name "$database" --table_name "$table" --column_name "$column" --work_space "$experiment_dir" --bulk_experiments_file_path "$bulk_experiments_file_path" --strategy "$strategy" $model_arg $pt_arg $es_arg
    fi
    

done < <(tail -n +2 "$gt_file_path")
