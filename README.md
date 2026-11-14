# Ask or Not Ask

这是「要不要问」的文本转 SQL 代码：判断何时该向用户澄清，并在 BIRD-Arcwise、AMBROSIA、CLAMBSQL 上评测。

## 目录

| 路径 | 作用 |
| --- | --- |
| `dataset/` | 各数据集的 `gold.jsonl`，以及下面说明的 `databases/` 指针 |
| `pipeline/presql_group/` | 候选 SQL 池（DC / Skeleton / ICL） |
| `pipeline/detection/` | Forward / Backward / Coverage 检出 |
| `pipeline/checks/` | Existence、Difference、Relevance 检查 |
| `simulator/` | 模拟作答与 evidence 改写 |
| `parsers/` | SQL 解析器（Qwen-Coder、DeepEye、gpt-5.6-terra） |
| `pipeline/scorer/` | Auto/Ask 打分器的训练与推理 |
| `evaluator/` | 执行正确率（EX）、提问数（Q）、McNemar 检验 |
| `analysis/` | gold 敏感性、agreement-θ、用户研究 |
| `paper/` | 论文图 |
| `scripts/` | vLLM 启动、重打分和数据挂载 |
| `outputs/` | 按数据集和阶段存放的实验结果 |
| `baselines/` | 论文对照用的 CLEAR 与 AmbiSQL 代码（上游快照和包装脚本） |
| `configs/datasets.json` | 官方规模、gold 键和数据库路径模板 |

仓库根目录的 `schema_text.py` 负责 schema 文本和 `GoldItem`，供各段流水线共用。

## 安装

```bash
pip install -r requirements.txt
```

训练打分器还需要 PyTorch、Transformers 和 PEFT。

### 数据库

gold 文件在仓库里，SQLite 数据库不随仓库分发。把 `dataset/databases` 指到如下布局的目录（详见 [dataset/DATABASES.md](dataset/DATABASES.md)）：

```text
dataset/databases/
  bird_arcwise/<db_id>/<db_id>.sqlite
  ambrosia/...
  clambsql/...
  birdtrain/<db_id>/<db_id>.sqlite
```

```bash
export ASK_DATABASES=/path/to/sqlite/roots
bash scripts/setup_databases.sh
```

若 `dataset/databases` 已经存在（包括软链接），脚本不会改动它。

### 语言模型

检出和检查默认连接本机 `http://127.0.0.1:8000/v1`（可用 `LLM_URL` 覆盖）。

```bash
export MODEL_PATH=/path/to/Qwen3-Coder-30B-A3B-Instruct
# 如果 conda 已在 PATH 里，不必设置 CONDA_BASE
export CONDA_BASE=/path/to/miniconda3
export CONDA_ENV=Qwen3-32B
bash scripts/start_vllm/start_vllm_qwencoder30b.sh 1    # GPU 0，端口 8000
# bash scripts/start_vllm/start_vllm_qwencoder30b.sh 8  # 八张卡，端口 8000、8100、…
```

`scripts/start_vllm/start_vllm_qwencoder30b_1vllm.sh` 和 `_8vllm.sh` 是同一脚本的封装。常用环境变量见 `.env.example`。

若要用远程接口，设置 `LLM_PRESET=env`，并提供 `OPENAI_API_KEY` 与 `OPENAI_BASE_URL`；或把 `configs/llm.yaml.example` 复制为 `configs/llm.yaml` 后设置 `LLM_PRESET`。不要把密钥提交进仓库。

## 跑实验

在仓库根目录执行，结果写到 `outputs/<数据集>/...`。下面是仓库内的入口，不会自动开一轮新的全量扫描。

### 1. 候选 SQL 池

```bash
python pipeline/presql_group/sql_pool.py --dataset bird_arcwise --out outputs/bird_arcwise/detection/presql
python pipeline/presql_group/sql_pool.py --dataset birdtrain --out outputs/birdtrain/detection/presql --few-shot
```

`--dataset bird` 是 `bird_arcwise` 的别名。多卡时可设 `--ports`（默认 `8000,8100`，或环境变量 `ABC_PORTS`）。

### 2. 检出

```bash
# 三阶段 vs 单枪（都跑 QC）
python pipeline/detection/run_forward_ablation_v2.py smoke --id bird:62 --workers 1
python pipeline/detection/run_forward_ablation_v2.py all --workers 1

# 把 Backward 卡并进 forward，再作答
python pipeline/detection/run_forward_backward.py all --port 8000

# 补 Coverage 问题
python pipeline/detection/run_forward_backward_coverage.py all --port 8000

# Forward ∪ Backward ∪ Coverage，再按 Existence → Difference → Relevance 检查
python pipeline/detection/run_forward_bc_erd.py all --port 8000 \
    --out outputs/bird_arcwise/detection/erd
```

合并入口需要已有的 forward / backward / coverage 输入（默认路径见该脚本说明）。同一输出目录可用 `--resume` 续跑。

### 3. 在冻结预测上做检查

```bash
python pipeline/checks/run_ext_checks.py existence
python pipeline/checks/run_diff_checks.py
python pipeline/checks/run_relevance_checks.py
```

默认从 `outputs/bird_arcwise/detection/forward` 起步，可用 `--pred`、`--out`、`--limit`、`--ids`、`--resume`。细节见 `pipeline/checks/README.md`。

### 4. 评测

```bash
python -m evaluator.ex --ds bird_arcwise --pred path/to/pred.jsonl --out path/to/eval.json
python -m evaluator.question_count --ds bird_arcwise --pred path/to/pred.jsonl
python -m evaluator.significance outputs/a/eval.json outputs/b/eval.json
python scripts/rescore_all.py
python scripts/check_manifest.py
```

评测写在 `outputs/<数据集>/eval/<解析器>/<方法>.json`，包含 `ex` 和 `q`。论文采用的 gold 键分别是 `gold`（BIRD-Arcwise）、`gold_1`（AMBROSIA）、`intended`（CLAMBSQL）。

### 5. 打分器与解析器重跑

```bash
# 新训练卡默认写到 outputs/scorer/build/，不覆盖官方的 train_set.jsonl / val_set.jsonl
python -m pipeline.scorer.build \
  --pred outputs/birdtrain/detection/step1/a/pred.jsonl \
  --pred outputs/birdtrain/detection/step1/b/pred.jsonl \
  --pred outputs/birdtrain/detection/step1/c/pred.jsonl \
  --ds birdtrain
python -m pipeline.scorer.train
python -m pipeline.scorer.select_theta
python -m pipeline.scorer.infer
```

详见 `pipeline/scorer/README.md`。BIRD-Arcwise 上 Ours / AmbiSQL 的 gpt-5.6-terra 重跑会读取 `outputs/bird_arcwise/terra/jobs/`，需要 `OPENAI_API_KEY`（`OPENAI_BASE_URL` 可选）：

```bash
python scripts/rerun_bird_terra_ours_ambisql.py
```

## 环境变量

| 变量 | 作用 |
| --- | --- |
| `LLM_URL` | 本机 OpenAI 兼容接口（默认 `http://127.0.0.1:8000/v1`） |
| `LLM_MAX_TOKENS` | 生成长度上限 |
| `LLM_SEED_VALUE` / `LLM_SEED` | 固定种子，或按 prompt 哈希 |
| `LLM_PRESET` / `LLM_CONFIG` | 预设名，或 YAML 配置路径 |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL` | 远程客户端（`LLM_PRESET=env`，以及 terra 重跑） |
| `MODEL_PATH` / `CONDA_BASE` / `CONDA_ENV` | vLLM 启动脚本 |
| `ASK_DATABASES` | 将要链接为 `dataset/databases` 的目录 |
| `SCORER_WORK` / `SCORER_BUILD` / `SCORER_MODEL` / `SCORER_THETA` | 打分器工作目录、`build` 输出目录、基座模型和可选的 θ* 覆盖 |
| `SCORER_ENABLE` | 设为 `1`/`true`/`yes` 时，检测在问人之前做 Auto/Ask。默认关闭。 |
| `SCORER_DEVICE` | scorer 推理设备，如 `cuda:1`。未设则优先用 `cuda`，否则 CPU。不要和正在跑的 vLLM 抢同一张卡。 |
| `CLAM_JSON` | 官方 CLAMBSQL 原始选项文件（若你有） |

旧的 `PAPER_EXP_LLM_*` 名称在 LLM 客户端里仍然可用，等价于 `LLM_MAX_TOKENS` 和 `LLM_SEED_*`。

## 许可与数据

请按 BIRD、AMBROSIA、CLAMBSQL 各自的发布条款使用原始数据库。本仓库提供 gold 标注和代码，不含 SQLite 原库。
