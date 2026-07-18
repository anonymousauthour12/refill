#!/bin/bash


gt_file_name="$1"
cc_filter=${2:-2}
strategy="$3"
model="$4"
prompt_template="$5"
early_stopping="$6"

gt_file_path="gt/${gt_file_name}"


bulk_experiments_folder_path="$(pwd)/bulk_experiments/"

bulk_experiments_file_path="${bulk_experiments_folder_path}multiple_experiments_${gt_file_name}"

mkdir -p "$bulk_experiments_folder_path"

rm "$bulk_experiments_file_path"

touch "$bulk_experiments_file_path"

: << 'COMMENT'


#sed -E -i 's/^( *data_sharing_strategy:).*/\1 0/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path
#sed -E -i 's/^( *data_sharing_strategy:).*/\1 1/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path
#sed -E -i 's/^( *data_sharing_strategy:).*/\1 2/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path
#sed -E -i 's/^( *data_sharing_strategy:).*/\1 3/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path
#sed -E -i 's/^( *data_sharing_strategy:).*/\1 4/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path

#sed -E -i 's/^( *data_sharing_strategy:).*/\1 5/' config.yaml
#./experiment.sh $1 $2 $bulk_experiments_file_path



sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 0/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 0/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 1/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 1/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 0/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 0/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 0/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 1/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path



sed -E -i 's/^( *data_sharing_statistics_and_distinct_values:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_random_rows_of_each_table:).*/\1 1/' config.yaml
sed -E -i 's/^( *data_sharing_selected_data_points:).*/\1 1/' config.yaml
./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

COMMENT

./experiment.sh $1 $2 $bulk_experiments_file_path $strategy "$model" "$prompt_template" "$early_stopping"

#./experiment.sh $1 $2 $bulk_experiments_file_path
#./experiment.sh $1 $2 $bulk_experiments_file_path

#sed -i 's/^different_formula_max_tries *= *.*/different_formula_max_tries = 1/' "$experiment_dir/config.ini"
#sed -i 's/^formula_max_subtries *= *.*/formula_max_subtries = 1/' "$experiment_dir/config.ini"

# Read the file line by line

#
