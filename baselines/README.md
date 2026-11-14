# baselines

论文里 CLEAR 和 AmbiSQL 的对照实现，以及当时用到的上游代码快照。正式分数已经在 `outputs/` 里，这里收的是代码。

## 目录

| 路径 | 内容 |
| --- | --- |
| `clear/` | [CLEAR](https://github.com/mengzhang18/CLEAR) 上游快照（commit `d9a4501`，2025-02-19）。上游没有附带 LICENSE，来源见 `clear/NOTICE`。 |
| `ambisql/` | [AmbiSQL](https://github.com/JustinzjDing/AmbiSQL) 上游快照（commit `defbdc5`，Apache 2.0，见 `ambisql/LICENSE`）。 |
| `compare/systems/` | 论文实验用的包装：官方 prompt，加上本仓库的 Human 模拟与改写。 |

包装脚本只改了上游仓库在本附录中的路径，没有改官方 prompt 或规则文件。CLEAR 未收录 `dataset/clambsql.json`（本仓库已有 `dataset/clambsql`）和 `cases.pdf`；AmbiSQL 未收录演示截图 `figs/demo_ui.png`。

## 论文里怎么跑

主表数字来自 Qwen3-Coder-30B 解析器，以及同一套澄清再交给 DeepEye 和 gpt-5.6-terra。跑基线时的设置是：

- CLEAR：`--system clear --clear-faithful off --rewrite schema_dqg`（正文里的 CLEAR-dqg）
- AmbiSQL：`--system ambisql --ambisql-full`

检测函数入口是 `compare.systems.clear.detect_clear` 和 `compare.systems.ambisql.detect_ambisql`。在仓库根目录把 `baselines/` 放进 `PYTHONPATH` 即可导入。官方预测和评测文件在：

```text
outputs/<dataset>/predictions/<parser>/{clear,ambisql}.jsonl
outputs/<dataset>/eval/<parser>/{clear,ambisql}.json
```

数据集是 `bird_arcwise`、`ambrosia`、`clambsql`；解析器是 `qwen_coder`、`gpt56_terra`、`deepeye`。数字对照见 `outputs/analysis/README.md`。
