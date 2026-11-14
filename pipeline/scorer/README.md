# pipeline/scorer

仓库内的 Auto/Ask 打分器（字母读出与 θ*）。训练数据从 `outputs/` 里的检出或检查 `pred.jsonl` 生成，不依赖仓库外的实验树。

```bash
# 从 birdtrain 上的 pred 生成新训练卡（默认写到 outputs/scorer/build/，不覆盖官方卡）
python -m pipeline.scorer.build \
  --pred outputs/birdtrain/detection/step1/a/pred.jsonl \
  --pred outputs/birdtrain/detection/step1/b/pred.jsonl \
  --pred outputs/birdtrain/detection/step1/c/pred.jsonl \
  --ds birdtrain

# 训练、选阈值和推理默认使用官方卡和 checkpoint
python -m pipeline.scorer.train
python -m pipeline.scorer.select_theta
python -m pipeline.scorer.infer          # 默认打验证集
python scripts/eval_scorer_clam_native.py
```

工作目录默认是 `outputs/scorer`：

- 官方训练卡：`train_set.jsonl`、`val_set.jsonl`
- 新生成的训练卡：`build/train_set.jsonl`、`build/val_set.jsonl`（`build` 的默认 `--out`；可用 `SCORER_BUILD` 或 `--out` 改路径）
- adapter：`checkpoint/`
- 阈值：`select_theta.json`（可用 `SCORER_THETA` 覆盖）
- 基座模型：`SCORER_MODEL`，或 `models/Qwen3-8B`

若要用新生成的卡训练，把 `SCORER_WORK` 指到该输出目录，例如 `SCORER_WORK=outputs/scorer/build`。

`eval_scorer_clam_native.py` 需要官方 CLAMBSQL JSON，路径为 `dataset/clambsql/clambsql.json` 或环境变量 `CLAM_JSON`。

## 接入检测（默认关闭）

打开 `SCORER_ENABLE=1` 后，检测在问模拟人之前会按 $H_{norm} \le \theta^*$ 自动采纳低熵卡（token 的 `source` 为 `scorer`），其余仍问人。需要 `SCORER_MODEL` 指向 Qwen3-8B，以及 `outputs/scorer/checkpoint`。缺任一文件会直接退出，而不是悄悄改回全问。请把 `SCORER_DEVICE` 设到未被占用的 GPU，不要和正在跑的 vLLM 抢同一张卡。
