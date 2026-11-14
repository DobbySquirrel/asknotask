# Ambiguity checks

独立入口：

- `existence.py`：`apply_existence(gold, phi, span_types, healed)`
- `difference.py`：`apply_difference(gold, phi, span_types, llm, ...)`，只处理 Attachment
- `relevance.py`：`apply_relevance(gold, phi, span_types, llm, format_parser_base, ...)`
- `runtime.py`：gold、冻结 pred、只读 SQL、问剩余卡并重解析、EX 打分
- `run_ext_checks.py` / `run_diff_checks.py` / `run_relevance_checks.py`：实验 runner

三份 runner 都是冻一份现成 pred 的 φ，只开一种 check，再全问剩余 ≥2 的卡并重解析。默认冻 `outputs/bird_arcwise/detection/forward`。

```bash
python pipeline/checks/run_ext_checks.py existence
python pipeline/checks/run_ext_checks.py existence \
    --pred outputs/bird_arcwise/detection/forward/score_paper.json
python pipeline/checks/run_ext_checks.py existence --limit 8 --ids bird:62

python pipeline/checks/run_diff_checks.py
python pipeline/checks/run_diff_checks.py --fidelity off

python pipeline/checks/run_relevance_checks.py
python pipeline/checks/run_relevance_checks.py --limit 8 --ids bird:1472
```

共用参数：`--pred`、`--baseline-score`、`--out`、`--limit`、`--ids`、`--resume`。
