# User study

Official Condition B results only; raw participant answer sheets are not in this repository.

- Sample (100 = 40/30/30) and groups: `group_rule/sample_report.json`, `group_rule/assignment.json`, `group_rule/groups.json`.
- Simulated answers (choice indices): `scorer_pick/sim_answers.json`.
- Official Condition B results are in `replay/` and `rescored/rating_summary.json`. The replay keeps all 87 automatic interpretations in the parser input regardless of the audit, restores 8 interpretations across 6 queries, and gives Ours 74% (simulated) and 79% (human), AmbiSQL 68% and 71%, and Never-Ask 61%. Usefulness and clarity are in `rescored/rating_summary.json` (usefulness recoded 1→2, 2→3, 3→4; six AmbiSQL clarity ratings changed from 4 to 3). Agreement and accept rates are in `agreement.json` (143/184, 69/111, 79/87).
- A superseded replay (`paired_current/`, human Ours 81% / 8 flips) and the mixed `paper_summary/` were moved out of this tree on 2026-11-11.
- Regenerate Figure 5 from the repository root with `python paper/figure/make_user_pairs.py`. To build parser requests with the revised replay policy, use `python analysis/prepare_requests.py --keep-auto --output <new-directory>/requests.json`.
