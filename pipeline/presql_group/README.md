# SQL 池生成

从数据集读入问题、evidence 和 schema，按 DC / Skeleton / ICL 采样候选 SQL，再按执行结果分组。

在仓库根目录调用：

```bash
python pipeline/presql_group/sql_pool.py --dataset bird_arcwise --out DIR
python pipeline/presql_group/sql_pool.py --dataset bird_arcwise --out DIR --few-shot
```

`--dataset` 读本仓库 `dataset/` 下的数据，常用 `bird_arcwise`（也可写 `bird`）、`birdtrain`、`ambrosia`、`clambsql`。运行前需在 `--ports` 对应端口拉好 LLM 服务。

## 参数

| 参数 | 说明 |
|---|---|
| `--dataset` | 必填，输入数据集 |
| `--out` | 必填，输出目录 |
| `--few-shot` | 可选，给 ICL 填入 BIRD few-shot 例子 |
| `--ports` | LLM 端口，逗号分隔；默认 `8000,8100`，也可用环境变量 `ABC_PORTS` |
| `--per` | DC / Skeleton / ICL 每路条数；默认 `2`，也可用环境变量 `ABC_PER_PATH` |

## 输入与提示词

每条样本使用数据集中的问题、evidence，以及用本仓库 `schema_text` 从对应 sqlite 生成的编号 schema。

- DC / Skeleton / ICL 使用 `prompts/birdtrain_{dc,skeleton,icl}.md`
- ICL 默认不带 few-shot；加上 `--few-shot` 时，从本目录的 `bird_dev_few_shots.json` 按题号查找，找不到则用编号 `0` 那一组
- 同一趟还会用 `prompts/parser_base.md` 采 1 条温度 0 的未澄清 SQL，只用于分组对照，不计入 `--per`

DC / Skeleton / ICL 的温度为 0.7，不传种子。未澄清 SQL 的温度为 0。已有足够条数的 `(qid, path)` 会跳过，可断点续跑。

## 输出

`--out` 目录下写两个文件：

- `drafts.jsonl`：每行是一条路径的采样结果。`path` 为 `never`、`DC`、`Skeleton` 或 `ICL`，`sqls` 是该路得到的 SQL。
- `groups.jsonl`：按执行 fingerprint 分组。`n_draft` 是 DC / Skeleton / ICL 的有效条数；`is_y` 表示与未澄清 SQL 执行结果相同；`differ` 表示存在与未澄清结果不同的组。执行失败的草稿不进入分组。
