# parsers/

SQL parser prompts and helpers (not part of `pipeline/`).

| Path | Role |
| --- | --- |
| `sql_parser_base.py` / `qwen_coder.py` | Base parser prompt (`format_parser_base`) |
| `sql_parser_deepeye.py` / `deepeye.py` | DeepEye parser prompt |
| `run.py` | `build_parser_prompt` / `run_parser` for `base` and `deepeye` |
| `contract.py` | `DetectResult` bag used by `run.py` |
| `gpt56_terra.py` | gpt-5.6-terra soft note (`insert_note`) plus the base parser |

Import from the repository root, for example `from parsers.sql_parser_base import format_parser_base`.
