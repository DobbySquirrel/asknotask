# Ask or Not Ask

A Text-to-SQL pipeline that detects ambiguities in a question, settles what it can with the database and a parser, predicts the user's choice when it is confident, and asks otherwise. The code is organized around the modules in the paper and is evaluated on BIRD-Arcwise, AMBROSIA, and CLAMBSQL.

## Pipeline

### Detection

Forward detection looks for ambiguities of nine types, organized into three stages of query construction: question structure (Scope, Attachment), row set (Column, Join, Value, NULL), and measure and output (Aggregate, Project, Tie). Each stage is asked only for its own types, and later stages also see earlier findings.

Backward detection starts from groups of draft queries. It returns ambiguities on the spans where the groups disagree, then marks groups already separated from the default reading and proposes a typed ambiguity for an unmarked group only when the difference matches a reading of the question.

Coverage adds questions for draft groups that earlier findings do not separate. The raw set of ambiguities is the union of forward and backward detection (backward can be omitted).

Code: `pipeline/detection/`, `pipeline/presql_group/`.

### Ambiguity Checks

The checks run in order: Existence, Difference, then Relevance. Each check keeps only what the previous one passed.

- **Existence** tests whether an interpretation names elements or values that occur in the schema, evidence, and database. If a single interpretation remains, it is auto-resolved and later checks are skipped.
- **Difference** instantiates a query for each remaining interpretation and drops the ambiguity if all queries execute and return the same result. A second call checks that each query implements its interpretation.
- **Relevance** tests whether answering the ambiguity could change the parser's query. The ambiguity is dropped if the unclarified query and all probes execute and agree.

A check removes an interpretation or drops an ambiguity only when its test succeeds. Failed or incomplete tests leave the ambiguity unchanged.

Code: `pipeline/checks/`.

### Scorer

For ambiguities that remain open, a lightweight listwise classifier estimates the user's choice from answer-token logits. Confidence is the normalized entropy of that distribution. Above a threshold selected on validation data, the system asks; at or below it, it writes the top interpretation automatically. The scorer is trained on simulated user choices produced by the same pipeline on held-out training databases.

Code: `pipeline/scorer/`.

### Composition and Parsing

Each kept ambiguity contributes at most one clarification sentence, which is appended to the evidence. The final query is produced by a Text-to-SQL parser from the question, schema, and this updated evidence.

Code: `simulator/`, `parsers/`.

## Setup

```bash
pip install -r requirements.txt
```

Gold annotations are in the repository; the SQLite databases are not. Point `dataset/databases` at a local copy (see `dataset/DATABASES.md`), or:

```bash
export ASK_DATABASES=/path/to/sqlite/roots
bash scripts/setup_databases.sh
```

Detection and the checks talk to a local OpenAI-compatible endpoint (default `http://127.0.0.1:8000/v1`). To serve the detection model with vLLM:

```bash
export MODEL_PATH=/path/to/Qwen3-Coder-30B-A3B-Instruct
bash scripts/start_vllm/start_vllm_qwencoder30b.sh 1
```

Common environment variables are listed in `.env.example`.

## Running experiments

From the repository root, results go to `outputs/<dataset>/...`. A typical full run is Forward ∪ Backward ∪ Coverage, followed by the three checks:

```bash
python pipeline/detection/run_forward_bc_erd.py all --port 8000 \
    --out outputs/bird_arcwise/detection/erd
```

Score execution accuracy (EX) and questions per instance (Q) with `evaluator/`:

```bash
python -m evaluator.ex --ds bird_arcwise --pred path/to/pred.jsonl --out path/to/eval.json
python -m evaluator.question_count --ds bird_arcwise --pred path/to/pred.jsonl
```

CLEAR and AmbiSQL reimplementations used in the paper are in `baselines/`. Figures live under `paper/`.

## Data

Please use the original BIRD, AMBROSIA, and CLAMBSQL databases under their own terms. This repository provides gold annotations and code, not the SQLite files.
