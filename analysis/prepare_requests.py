"""Build parser requests from responses and frozen study context; no API calls."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from common import load,dump,evidence,format_parser_base

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1];p=argparse.ArgumentParser(description=__doc__);p.add_argument("--output",type=Path,default=root/"outputs/user_study/analysis_results/requests.json");p.add_argument("--keep-auto",action="store_true",help="Keep all system-generated interpretations in replay evidence");a=p.parse_args()
    tasks=load(root/"outputs/user_study/reference/tasks.json");traces=load(root/"outputs/user_study/reference/trace_templates.json");fixed=load(root/"outputs/user_study/reference/fixed_ours_context.json");histories={s:load(root/f"outputs/user_study/reference/{s}_simulation.json") for s in ["ours","ambisql"]};humans={n:load(root/f"outputs/user_study/answers_{n}.json") for n in range(1,11)};jobs=[];audit=[]
    for task in tasks:
        q=task["id"];g=task["group"]+1
        for side in ["ours","ambisql","never_ask"]:
            trace=traces[side][q];inp=trace["input"];settings=trace["run"]
            for cohort in ["never_ask_control"] if side=="never_ask" else ["sim_visible","human_internal"]:
                ev=inp["evidence"] if side=="never_ask" else evidence(task,side,cohort,humans[g],histories[side][q],trace,fixed,audit,keep_auto=a.keep_auto)
                request={k:settings[k] for k in ["model","max_completion_tokens","reasoning_effort"]};request["messages"]=[{"role":"user","content":format_parser_base(inp["schema"],inp["question"],ev)}]
                key=hashlib.sha256(json.dumps({"base_url":settings["base_url"],"request":request},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                jobs.append({"id":q,"group":g,"dataset":task["dataset"],"side":side,"cohort":cohort,"request_key":key,"base_url":settings["base_url"],"request":request})
    assert len(jobs)==500;dump(a.output,jobs);dump(a.output.with_name("request_special_cases.json"),audit);print(f"Prepared {len(jobs)} items, {len({j['request_key'] for j in jobs})} distinct requests.")
