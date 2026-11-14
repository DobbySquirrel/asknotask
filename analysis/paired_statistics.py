"""Recompute EX summaries and exact paired tests from per-task execution records."""
import argparse
from math import comb
from pathlib import Path
from common import load,dump
def mcnemar(a: dict[str, bool], b: dict[str, bool]) -> dict:
    ids = sorted(set(a) & set(b))
    only_a = sum(1 for i in ids if a[i] and not b[i])
    only_b = sum(1 for i in ids if (not a[i]) and b[i])
    n = only_a + only_b
    if n == 0:
        p = 1.0
    else:
        pb = comb(n, only_a) / (2 ** n)
        p = sum(comb(n, k) / (2 ** n) for k in range(n + 1) if comb(n, k) / (2 ** n) <= pb + 1e-15)
    return {
        "n": len(ids),
        "only_a": only_a,
        "only_b": only_b,
        "agree_both_true": sum(1 for i in ids if a[i] and b[i]),
        "agree_both_false": sum(1 for i in ids if (not a[i]) and (not b[i])),
        "p_exact": round(p, 6),
    }

def summarize(rows,field="ex_match"):
    groups={"never_ask_control":["never_ask"],"sim_visible":["ours","ambisql"],"human_internal":["ours","ambisql"]}
    metrics={};maps={}
    for cohort,sides in groups.items():
        metrics[cohort]={};maps[cohort]={}
        for side in sides:
            selected=[r for r in rows if r["cohort"]==cohort and r["side"]==side]
            assert len(selected)==100 and len({r["id"] for r in selected})==100
            maps[cohort][side]={r["id"]:r[field] for r in selected}
            metrics[cohort][side]={"n":len(selected),"n_hit":sum(r[field] for r in selected),"ex_percent":100*sum(r[field] for r in selected)/len(selected),"sql_execution_errors":sum(not r["pred_ok"] for r in selected)}
    paired={}
    for side in ["ours","ambisql"]:
        t=mcnemar(maps["sim_visible"][side],maps["human_internal"][side])
        paired[side]={"delta_pp":metrics["human_internal"][side]["ex_percent"]-metrics["sim_visible"][side]["ex_percent"],"matrix":{"rows":["sim_ok","sim_fail"],"cols":["human_ok","human_fail"],"cells":[[t["agree_both_true"],t["only_a"]],[t["only_b"],t["agree_both_false"]]]},"mcnemar":t}
    return {"metrics":metrics,"human_vs_sim":paired,"ours_vs_ambisql":{c:mcnemar(maps[c]["ours"],maps[c]["ambisql"]) for c in ["sim_visible","human_internal"]}}

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--scores",type=Path,default=Path(__file__).resolve().parents[1]/"outputs/user_study/replay_eval/paired_current/scores.json");p.add_argument("--output",type=Path,default=Path(__file__).resolve().parents[1]/"outputs/user_study/analysis_results/ex_statistics.json");a=p.parse_args()
    rows=load(a.scores);assert len(rows)==500
    result=summarize(rows);result["numeric_diagnostic"]=summarize(rows,"numeric_set_match");dump(a.output,result)
    print(__import__("json").dumps(result["metrics"],indent=2))
