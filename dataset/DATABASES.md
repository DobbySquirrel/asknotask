# Database layout

`dataset/databases` is a local pointer (usually a symlink) to SQLite files. It is not part of the published tree, because the target path is machine-specific. Gold labels stay in `dataset/<name>/gold.jsonl` and use repo-relative `db_path` values such as `dataset/databases/bird_arcwise/<db_id>/<db_id>.sqlite`.

## Expected tree

```text
dataset/databases/
  bird_arcwise/<db_id>/<db_id>.sqlite
  ambrosia/          # as in the official AMBROSIA release
  clambsql/          # as in the official CLAMBSQL release
  birdtrain/<db_id>/<db_id>.sqlite
```

Exact subfolders under `ambrosia/` and `clambsql/` follow the official dumps. Path templates are in `configs/datasets.json`; when a gold row has its own `db_path`, that path wins.

## How to attach them

```bash
export ASK_DATABASES=/path/to/sqlite/roots
bash scripts/setup_databases.sh
```

Or pass the directory as the first argument. If `dataset/databases` already exists, the script prints the current target and exits.

Place the official BIRD (dev / train), AMBROSIA, and CLAMBSQL SQLite releases into that tree under the names above. BIRD-Arcwise uses the BIRD dev databases (`california_schools`, `financial`, and so on).
