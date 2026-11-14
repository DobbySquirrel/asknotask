# scripts/

| Script | Role |
| --- | --- |
| `setup_databases.sh` | Link `dataset/databases` to a local SQLite tree (does not replace an existing path) |
| `start_vllm/start_vllm_qwencoder30b.sh` | Launch 1–8 local vLLM shards. Set `MODEL_PATH`; `CONDA_BASE` / `CONDA_ENV` are optional when conda is configured |
| `start_vllm/start_vllm_qwencoder30b_1vllm.sh` | Same script with 1 shard |
| `start_vllm/start_vllm_qwencoder30b_8vllm.sh` | Same script with 8 shards |
| `rescore_all.py` | Re-score `outputs/**/predictions` into `eval_rescored/` |
| `check_manifest.py` | Compare `eval/` numbers with the paper manifest |
| `rerun_bird_terra_ours_ambisql.py` | gpt-5.6-terra rerun from in-repo job files under `outputs/bird_arcwise/terra/jobs/` |
| `eval_scorer_clam_native.py` | Native-option CLAMBSQL scorer evaluation |

Run these from the repository root. See the top-level README for the full experiment sequence.
