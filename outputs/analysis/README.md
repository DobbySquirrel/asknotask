# Experimental results (paper appendix)

CLEAR 和 AmbiSQL 的对照代码在 [`baselines/`](../../baselines/README.md)。

This directory is the source map for the Experimental Evaluation section. All paper numbers below are checked by:

```bash
python3 scripts/check_manifest.py --expected outputs/analysis/expected.json
```

One-stage forward detection uses \(Q=2.32\) (raw 2.3233), not 2.18. Official execution accuracy is against \(y^{*}\) (BIRD `gold`, AMBROSIA `gold_1`, CLAMBSQL `intended`).

A machine-readable path map is in [`sources.json`](sources.json). Small extracts that are not in the standard eval layout are in [`paper/`](paper/).

## Official sources only

Superseded copies that conflicted with the paper numbers were moved out of this repository on 2026-11-11 to `._archive/2026-11-11_not_in_paper/` (HPC only, not part of the public appendix): `paired_current/`, `paper_summary/` (old Condition B: 81% EX, 8 flips, usefulness about 2.58), and the external `gold_sensitivity.json` symlink.

- One-stage is `paper/fwd_onestage.json` (also copied at `outputs/bird_arcwise/eval/qwen_coder/fwd_onestage.json`; the two files are identical): 304/498 = 61.0, \(Q=2.32\). Do not use `oneprompt_bc` (320/498, \(Q=2.3313\)) or the `s123` arm (309/498 = 62.0) in place of official staged `fwd_nocheck` (310/498 = 62.2, \(Q=3.66\)).
- `theta_curve/summary.json` execution accuracy on BIRD at \(\theta=0.5\) is 331 hits (66.47%). Official eval is 333/498 = 66.9%. Use the curve for \(Q\) and auto-resolution agreement only.
- Scorer training and validation sizes come from the frozen `paper/select_theta.json` (1,454 / 261 questions). If `outputs/scorer/select_theta.json` differs, ignore it for paper numbers.
- Condition B agreement and accept rates (143/184, 69/111, 79/87) are in `outputs/user_study/agreement.json`.

## Table II / Figure 4 (RQ1, Qwen3-Coder, official \(y^{*}\))

Paths: `outputs/<dataset>/eval/qwen_coder/{never_ask,clear,ambisql,ours_wo_scorer,ours}.json`.

| Dataset | n | Never-Ask | CLEAR EX / Q | AmbiSQL EX / Q | Ours w/o EX / Q | Ours EX / Q |
| --- | ---: | --- | --- | --- | --- | --- |
| BIRD-Arcwise | 498 | 59.2 (295) | 60.0 / 0.29 (299) | 60.0 / 1.91 (299) | 66.9 / 2.93 (333) | 66.9 / 1.89 (333) |
| AMBROSIA | 1149 | 12.2 (140) | 17.0 / 0.75 (195) | 20.2 / 2.00 (232) | 46.8 / 2.55 (538) | 47.6 / 1.82 (547) |
| CLAMBSQL | 1400 | 45.9 (643) | 49.2 / 1.18 (689) | 49.0 / 1.88 (686) | 57.4 / 2.89 (803) | 56.9 / 1.97 (797) |

EX gains versus Never-Ask are computed from unrounded rates, then printed to one decimal (Ours w/o scorer: +7.6 / +34.6 / +11.4).

## Stronger parsers (AMBROSIA / CLAMBSQL)

Paths: `outputs/<dataset>/eval/{gpt56_terra,deepeye}/<method>.json`. The `q` field in these files is 0; \(Q\) is shared with the Coder ambiguities and should not be read from these files.

Printed EX: Terra on AMBROSIA 25.8 / 28.9 / 33.3 / 58.6 / 58.4; on CLAMBSQL 52.9 / 54.1 / 56.1 / 61.4 / 61.3. DeepEye on AMBROSIA 27.2 / 32.8 / 36.3 / 47.6 / 47.7; on CLAMBSQL 54.1 / 56.4 / 58.9 / 61.4 / 60.8.

## Span recall

`outputs/analysis/span/span_recall.json`: overall 72.8 / 59.5 / 39.7 (Ours / CLEAR / AmbiSQL); spans per question 1.87 / 1.15 / 1.12.

## Auto-resolution by type (RQ2, \(\theta^{*}=0.5\))

`outputs/analysis/theta/theta_curve/by_type_t0.5.json`. Fold Table into Column and Rank into Tie before comparing with the paper table. The paper prints Join auto-% on BIRD as 6.3 (half-up), not 6.2 from banker's rounding.

## Ablation on BIRD-Arcwise (Coder)

| Variant | EX | Q | Source |
| --- | --- | --- | --- |
| Never-Ask | 59.2 | 0 | `eval/qwen_coder/never_ask.json` |
| Single-stage forward | 61.0 | **2.32** | `analysis/paper/fwd_onestage.json` |
| Staged forward, no checks | 62.2 | 3.66 | `eval/qwen_coder/fwd_nocheck.json` (310/498) |
| + ambiguity checks | 65.3 | 2.51 | `eval/qwen_coder/fwd_checks.json` |
| + backward detection | 66.9 | 2.93 | `eval/qwen_coder/ours_wo_scorer.json` |
| + scorer | 66.9 | 1.89 | `eval/qwen_coder/ours.json` |
| Random control (prose only; mean of three seeds) | 65.2 | 1.88 | `eval/qwen_coder/random_control.json` (1.7 points below the scorer) |

The checks remove 31% of the staged questions and add 3.0 points. Backward detection adds 1.6 points and 0.42 questions. The scorer then removes 35% of the questions at unchanged EX.

## Scorer and LTT

`outputs/analysis/paper/select_theta.json` is the official scorer-setup file: \(\theta^{*}=0.5\); 5,267 training cards / 1,454 questions / 60 databases; 1,006 validation cards / 261 questions / 9 databases. The scorer auto-resolves 305 validation ambiguities (30.3%) at 90.2% agreement. LTT at \(\delta=0.1\) gives \(U(\theta^{*})=14.4\%\) (`outputs/analysis/ltt/`).

Test-set disagreement at \(\theta^{*}\) (`outputs/analysis/theta/theta_curve/summary.json`): BIRD 8.4% (45/535), AMBROSIA 5.8% (50/869), CLAMBSQL 32.7% (438/1339).

At \(\theta=0.9\), \(Q\) is 0.64 / 0.52 / 0.55. Official EX is in `ours_theta0.9.json` (326 / 503 / 762), which is 5.4 / 23.6 / 5.2 points above the stronger baseline (difference computed before rounding).

## Any-gold

`outputs/analysis/gold_sensitivity/gold_sensitivity_rescore.json`: Ours versus Never-Ask is +20.6 on AMBROSIA and +7.8 on CLAMBSQL.

## Ask harm

`outputs/analysis/harm_analysis/ask_harm.json`: among questions the simulated user was asked, clarification turned a correct query into a wrong one on at most 1.6% on AMBROSIA and 3.0% on CLAMBSQL.

## User study (RQ3)

Raw participant answer sheets are not part of this public appendix; only aggregated official results are kept.

Condition A: `outputs/user_study_wo_nl/analysis_results/round_a/summary.json`. On 50 items, 42 have identical option sets (84.0%), and both annotators selected the scorer's interpretation on 45 (90.0%).

Condition B: `outputs/user_study/replay/pair_statistics.json`. Simulated-user EX is 74.0 / 68.0 / 61.0; human EX is 79.0 (Ours) and 71.0 (AmbiSQL); Ours flips 6 vs 1, \(p=0.125\). Usefulness and clarity are in `outputs/user_study/rescored/rating_summary.json` (re-coded usefulness 3.3 / 3.1, clarity 4.8 / 4.7). Agreement and accept rates are in `outputs/user_study/agreement.json` (143/184 = 77.7%, 69/111 = 62.2%, 79/87 = 90.8%). The figure script `paper/figure/make_user_pairs.py` defaults to `outputs/user_study/replay`.

Unused analyses were moved out of this tree on 2026-11-11 (CLAMBSQL native-option scorer check, probe-call cost file, case-study candidate dump, BIRD check-variant ablations, and the leftover BIRD terra rerun). Official paper sources above are unchanged.
