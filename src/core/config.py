
from pathlib import Path
import yaml

import configparser

from dataclasses import dataclass

def load_config(config_file_path: str):
    """
    Load configuration from config.yaml and return it as a dict.
    Adjust the number of `.parents[...]` to match your project layout.
    """
    # Example: go up 2 levels from this file, then /config.yaml
    # Your original used parent.parent.parent (3 levels); resolve for safety.
    print(f"config_path: {config_file_path}")

    with open(config_file_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}   # ensure dict even if file is empty/null
    return cfg


@dataclass
class Configuration:

    strategy: int = 1
    prompt_template: int = 1
    guided_search_mode: int = 1   # 0=Tree, 1=Flat, 2=Single-shot (S4 only)
    number_of_data_points_from_target_table_to_send: int = 0
    cleaning_threshold: int = 0
    max_context_tokens: int = 120000
    diagnoses_rows_count: int = 0
    max_candidate_formulas_single_table: int = 10
    max_candidate_formulas_count_exists: int = 10
    max_candidate_formulas_across_tables: int = 10
    schema_pruning_fk_hops: int = 3
    max_tables_in_join_path: int = 4
    is_computed_max_attempts: int = 3
    data_sharing_size_limit_in_bytes: int = 0
    data_sharing_max_number_of_tockens: int = 0

    early_stopping: bool = True
    use_sample_table: bool = False
    execute_query_max_tries: int = 0

    different_formula_max_tries: int = 0

    #data_sharing_strategy: int = 0
    data_sharing_schema_and_diagnoses: int = 0
    data_sharing_statistics_and_distinct_values: int = 0
    data_sharing_random_rows_of_each_table: int = 0
    data_sharing_selected_data_points: int = 0
    data_sharing_strategy_2_number_of_distinct_samples: int = 0
    data_sharing_strategy_3_number_of_rows: int = 0
    maximum_potential_data_points_in_target_table: int = 0

    database_host: str = ""
    database_port: int = 0
    database_user: str = ""
    database_pw: str = ""

    api_key: str = ""
    api_version: str = ""
    azure_endpoint: str = ""
    huggingface_access_token: str = ""
    model: str = ""
    tpm_limit: int = 240000
    temperature: float = 0
    top_p: float = 0
    frequency_penalty: float = 0
    presence_penalty: float = 0
    max_tokens: int = 4096

    target_database_name = ""
    target_table_name = ""
    target_column_name = ""
    work_space = ""
    sample_table_name = ""   # set by create_sample_table(); cleared by drop_sample_table()

config = Configuration()

def set_configuration(config_file_path: str, target_db_name: str, target_table_name: str, target_column_name: str, work_space: str, model_override: str = None):
    
    conf = load_config(config_file_path)

    # Safely fetch sections (use {} if missing)
    general_config = conf.get("general", {})
    folders_config = conf.get("folders", {})
    llm_config = conf.get("llm", {})
    db_config = conf.get("database", {})
    execution_config = conf.get("execution", {})
    data_sharing_config = conf.get("data_sharing", {})
    
    config.prompt_template = int(general_config.get('prompt_template', 1))
    config.guided_search_mode = int(general_config.get('guided_search_mode', 1))
    config.number_of_data_points_from_target_table_to_send = int(general_config.get('number_of_data_points_from_target_table_to_send'))
    config.cleaning_threshold = int(general_config.get('cleaning_threshold'))
    config.diagnoses_rows_count = int(general_config.get('diagnoses_rows_count'))
    config.max_candidate_formulas_single_table = int(general_config.get('max_candidate_formulas_single_table', 10))
    config.max_candidate_formulas_count_exists = int(general_config.get('max_candidate_formulas_count_exists', 10))
    config.max_candidate_formulas_across_tables = int(general_config.get('max_candidate_formulas_across_tables', 10))
    config.schema_pruning_fk_hops = int(general_config.get('schema_pruning_fk_hops', 3))
    config.max_tables_in_join_path = int(general_config.get('max_tables_in_join_path', 4))
    config.is_computed_max_attempts = int(general_config.get('is_computed_max_attempts', 3))
    config.data_sharing_size_limit_in_bytes = int(general_config.get('data_sharing_size_limit_in_bytes'))
    config.data_sharing_max_number_of_tockens = int(general_config.get('data_sharing_max_number_of_tockens'))
    

    config.early_stopping = bool(execution_config.get('early_stopping', True))
    config.use_sample_table = bool(execution_config.get('use_sample_table', False))
    config.execute_query_max_tries = int(execution_config.get('execute_query_max_tries'))
    config.different_formula_max_tries = int(execution_config.get('different_formula_max_tries'))
    

    config.data_sharing_schema_and_diagnoses = int(data_sharing_config.get('data_sharing_schema_and_diagnoses'))
    config.data_sharing_statistics_and_distinct_values = int(data_sharing_config.get('data_sharing_statistics_and_distinct_values'))
    config.data_sharing_random_rows_of_each_table = int(data_sharing_config.get('data_sharing_random_rows_of_each_table'))
    config.data_sharing_selected_data_points = int(data_sharing_config.get('data_sharing_selected_data_points'))
    config.data_sharing_strategy_2_number_of_distinct_samples = int(data_sharing_config.get('data_sharing_strategy_2_number_of_distinct_samples'))
    config.data_sharing_strategy_3_number_of_rows = int(data_sharing_config.get('data_sharing_strategy_3_number_of_rows'))
    config.maximum_potential_data_points_in_target_table = int(data_sharing_config.get('maximum_potential_data_points_in_target_table'))
    

    print(f"#############################################################################################################")
    print(f"config.data_sharing_schema_and_diagnoses: {config.data_sharing_schema_and_diagnoses}")
    print(f"config.data_sharing_statistics_and_distinct_values: {config.data_sharing_statistics_and_distinct_values}")
    print(f"config.data_sharing_random_rows_of_each_table: {config.data_sharing_random_rows_of_each_table}")
    print(f"config.data_sharing_selected_data_points: {config.data_sharing_selected_data_points}")
    print(f"#############################################################################################################")
    

    config.database_host = str(db_config.get('host'))
    config.database_port = int(db_config.get('port'))
    config.database_user = str(db_config.get('user'))
    config.database_pw = str(db_config.get('password'))

    config.api_key = str(llm_config.get('api_key'))
    config.api_version = str(llm_config.get('api_version'))
    config.azure_endpoint = str(llm_config.get('azure_endpoint'))
    config.huggingface_access_token = str(llm_config.get('huggingface_access_token', ''))
    config.model = str(llm_config.get('model'))
    config.temperature = float(llm_config.get('temperature'))
    config.top_p = float(llm_config.get('top_p'))
    config.frequency_penalty = float(llm_config.get('frequency_penalty'))
    config.presence_penalty = float(llm_config.get('presence_penalty'))
    config.max_tokens = int(llm_config.get('max_tokens', 4096))

    config.tpm_limit = int(llm_config.get('tpm_limit', 240000))
    config.max_context_tokens = int(general_config.get('max_context_tokens', 120000))

    if model_override:
        config.model = model_override
        for i in range(10):
            if llm_config.get(f'model_{i}_model') == model_override:
                config.azure_endpoint = str(llm_config.get(f'model_{i}_azure_endpoint', config.azure_endpoint))
                config.tpm_limit = int(llm_config.get(f'model_{i}_tpm_limit', config.tpm_limit))
                config.max_context_tokens = int(llm_config.get(f'model_{i}_max_context_tokens', config.max_context_tokens))
                break

    config.temporary_folder = str(folders_config.get('temporary'))

    config.target_database_name = target_db_name
    config.target_table_name = target_table_name
    config.target_column_name = target_column_name
    config.work_space = work_space

    # Rewrite config.yaml in the workspace so the folder is self-documenting
    # (reflects the actual model/endpoint used, not the default from root config.yaml)
    conf["llm"]["model"] = config.model
    conf["llm"]["azure_endpoint"] = config.azure_endpoint
    import os
    ws_config = os.path.join(work_space, "config.yaml")
    if os.path.exists(ws_config):
        with open(ws_config, "w", encoding="utf-8") as f:
            yaml.dump(conf, f, default_flow_style=False, allow_unicode=True)














































