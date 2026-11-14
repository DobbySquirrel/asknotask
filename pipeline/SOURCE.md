# pipeline/

In-repo modules for draft SQL, detection, checks, and the Auto/Ask scorer.

| Path | Role |
| --- | --- |
| `presql_group/sql_pool.py` | Sample DC / Skeleton / ICL drafts and group them by execution result |
| `presql_group/prompts/` | Draft and parser prompts |
| `detection/three_stage.py` | S1+S2+S3 detection, QC, human simulation, evidence rewrite |
| `detection/one_stage.py` | Single-prompt nine-type detection |
| `detection/coverage.py` | Coverage questions over draft groups |
| `detection/common.py` | Gold evidence, option picking, serialization |
| `detection/run_common.py` | Shared helpers for experiment runners |
| `detection/run_forward_ablation_v2.py` | `s123` vs `oneprompt` ablation (both use QC) |
| `detection/run_forward_backward.py` | Merge Backward cards into forward and re-answer |
| `detection/run_forward_backward_coverage.py` | Add coverage questions on top of forward+B |
| `detection/run_forward_bc_erd.py` | Forward ∪ B ∪ C, then Existence → Difference → Relevance |
| `checks/existence.py` | Existence check |
| `checks/difference.py` | Difference check (Attachment probes; optional fidelity) |
| `checks/relevance.py` | Relevance check |
| `checks/runtime.py` | Shared gold loading, read-only SQL, re-parse, EX |
| `checks/run_ext_checks.py` / `run_diff_checks.py` / `run_relevance_checks.py` | Run one check on a frozen prediction |
| `scorer/` | Auto/Ask scorer; see `scorer/README.md` and `scorer/paths.py` |

Compose / rewrite lives in `simulator/compose/`. Parser prompts live in `parsers/`.

Coverage first decides whether a draft group is already covered, and only then proposes `new_questions`. Detection merges cards by span with first-write-wins (`union_phi`). The combined ERD runner applies checks in the order Existence, Difference, Relevance.
