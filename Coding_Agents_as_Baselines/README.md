# Coding agents as baselines

Files of the three coding-agent baselines that Refill is compared with.

```
Agent-Generated/
    task_description_generate_c.md   task description used to produce the program
    c.py                             the program
Agent-Direct/
    task_description.md              task description, one target column per run
Refill-Skill/
    task_description.md              Agent-Direct description plus a sentence about the skills
    SFR-L3/skills/                   six skills (SFR-L3 variant)
    JFR-Generic/skills/              six skills (JFR-Generic variant)
```

## Agent-Generated

`c.py` is run once per target column:

```
python c.py --column <database>.<table>.<column> --llm <gpt5|sonnet55>
```

The database and LLM settings are read from three JSON files in the current directory: `db_access.json`, `llm_gpt5.json` and `llm_sonnet55.json`. The real files hold credentials and are not included; `Agent-Generated/*.example.json` show the format. Copy them without `.example`, fill in your own values, and put them next to `c.py`. The host names and keys that appear in `c.py` and in the task description are placeholders.

## Agent-Direct and Refill-Skill

In the task descriptions `{DATABASE}`, `{TABLE}` and `{COLUMN}` are replaced by the target column. The agent finds the database account in a file `config.json` in its working directory (`db_user` and `db_password`, a read-only account). The real file is not included; `config.example.json` shows the format.

Refill-Skill uses the Agent-Direct description with one added sentence that points to the skills, and a second comment line in each formula file that says whether the formula was checked on all rows or on a sample. Each skill is a folder `<skill name>/SKILL.md`. The two variants differ only in `formula-proposer` and `formula-validation`.
