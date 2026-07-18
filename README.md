# ReFILL — Relational Formula Inference for Lost Lookups

ReFILL automatically recovers SQL formulas for computed columns in relational databases using large language models. Given a target `database.table.column`, the pipeline analyses the schema, optionally samples data, and runs an LLM-guided SQL validation loop until it finds a formula that reconstructs the column's values above a configurable accuracy threshold.

## Requirements

- Python 3.9+
- MySQL 8.0+ (databases must be loaded locally)
- An Azure OpenAI or Anthropic endpoint

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml   # then fill in your credentials
```

## Configuration

Edit `config.yaml`:

| Key | Description |
|-----|-------------|
| `database.host/user/password` | MySQL connection |
| `llm.api_key` / `llm.azure_endpoint` | LLM credentials |
| `llm.model` | Active model (`gpt-4o`, `gpt-5`, `claude-opus-4-7`, `Llama-3.3-70B-Instruct`) |
| `general.prompt_template` | Prompt style: `1` (direct), `2` (structured), `3` (skills-style, default) |
| `general.cleaning_threshold` | Minimum accuracy % to accept a formula (default: `100`) |

## Running a single column

```bash
python main.py \
  --steps 1 5 \
  --db_name   <database> \
  --table_name <table> \
  --column_name <column> \
  --work_space experiments/exp_0 \
  --strategy   3
```

**Strategies:**

| Flag | Context provided to LLM |
|------|--------------------------|
| `1` | Schema only |
| `2` | Schema + column statistics + distinct values |
| `3` | Schema + statistics + sample rows |
| `4` | Schema + smartly selected data points (Join-Aware) |

**Example — recover `gpa` in the `uni` database:**

```bash
python main.py --steps 1 5 --db_name uni --table_name Student \
               --column_name gpa --work_space experiments/exp_0 --strategy 3
```

Output is written to `experiments/exp_0/`:
- `reported_accuracy_*.csv` — formula found, accuracy, and timing
- `sql_log.sql` — all SQL queries issued during the run
- `column_diagnosis.log` — one-line root-cause summary

## Reproducing Section 7 experiments

The ground truth benchmark is `gt/new_gt/ground_truth.csv` (801 columns: 315 computed, 486 non-computed across 11 databases).

### Single model / single strategy

```bash
./run_workers.sh <gt_file> <model> <strategy> [workers]
```

| Argument | Values |
|----------|--------|
| `gt_file` | file under `gt/` — use `new_gt/ground_truth.csv` for the full benchmark |
| `model` | `gpt-4o` \| `gpt-5` \| `claude-opus-4-7` \| `Llama-3.3-70B-Instruct` |
| `strategy` | `1` `2` `3` `4` |
| `workers` | parallel columns (tune to your rate limit; see table below) |

**Example — GPT-4o, Strategy 3, 8 workers:**

```bash
./run_workers.sh new_gt/ground_truth.csv gpt-4o 3 8
```

### Recommended worker counts (rate-limit safe)

| Model | S1 | S2 | S3 | S4 |
|-------|----|----|----|----|
| `gpt-4o` | 13 | 10 | 8 | 5 |
| `gpt-5` | 12 | 10 | 7 | 5 |
| `claude-opus-4-7` | 3 | 3 | 2 | 2 |
| `Llama-3.3-70B-Instruct` | 15 | 12 | 10 | 8 |

### Full benchmark (all models, all strategies)

```bash
./run_full_benchmark.sh new_gt/ground_truth.csv
```

Results are written to `experiments/experiment_N/`. Each experiment directory contains one subdirectory per column (`db/table/column/`) with `reported_accuracy_*.csv` files.

## Project structure

```
main.py                              Entry point
config.example.yaml                  Configuration template
src/
  core/
    config.py                        Configuration dataclass
    llm_layer.py                     LLM abstraction (Azure OpenAI / Anthropic)
    db_layer.py                      MySQL connection and query execution
    db_functions.py                  Schema analysis and data sharing
    prompt_templates/                Prompt template package (PT1 / PT2 / PT3)
    report_util.py                   Accuracy metrics and timing reports
  steps/
    collect_statistical_metadata.py  Step 1 — schema and statistics collection
    find_formula_schema_based.py     Step 5 — formula search (Strategies 1-3)
    find_formula_smartly_selected.py Step 5 — formula search (Strategy 4)
    formula_common.py                Shared validation and plausibility logic
gt/
  new_gt/ground_truth.csv            Full benchmark ground truth (801 columns)
  selected_cc_20.csv                 20-column development subset
```
