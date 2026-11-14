"""Re-execute frozen SQL against externally supplied read-only SQLite databases."""
import argparse
import hashlib
import json
from pathlib import Path
from common import load,dump
from sqlite_scoring import run_sql,norm_row,compare_results

def fingerprint(result):
    if not result.ok or result.rows is None:return None
    rows=sorted({norm_row(r) for r in result.rows},key=lambda r:json.dumps(r,ensure_ascii=False,default=str))
    return hashlib.sha1(json.dumps(rows,ensure_ascii=False,default=str).encode()).hexdigest()

if __name__=="__main__":
    root=Path(__file__).resolve().parents[1]
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--database-root",type=Path,required=True,help="Directory containing databases/ from the original handoff");p.add_argument("--scores",type=Path,default=root/"outputs/user_study/replay_eval/paired_current/scores.json");p.add_argument("--output",type=Path,default=root/"outputs/user_study/analysis_results/executed_scores.json");a=p.parse_args()
    index=load(root/"outputs/user_study/reference/db_index.json");rows=load(a.scores);gold={};cache={}
    for q in index:
        db=(a.database_root/index[q]["db_path"]).resolve()
        if not db.is_relative_to(a.database_root.resolve()) or not db.is_file():raise SystemExit(f"Missing/external database: {q}")
        result=run_sql(index[q]["gold_sql"],str(db),"sqlite",30)
        assert result.ok and fingerprint(result)==index[q]["gold_fp"],f"Gold fingerprint mismatch: {q}"
        gold[q]=result
    out=[]
    for row in rows:
        q=row["id"];key=(q,row["predicted_sql"])
        if key not in cache:cache[key]=run_sql(row["predicted_sql"],str(a.database_root/index[q]["db_path"]),"sqlite",30)
        result=cache[key];item=dict(row);hit=bool(result.ok and fingerprint(result)==index[q]["gold_fp"])
        item.update(ex_match=hit,legacy_fingerprint_match=hit,numeric_set_match=bool(result.ok and compare_results(result.rows,gold[q].rows,mode="bird")),pred_ok=result.ok,error=result.error,pred_n_rows=result.n_rows,pred_result_sample=(result.rows or [])[:6]);out.append(item)
    dump(a.output,out);print(f"Executed {len(out)} items; {len(gold)} gold results verified.")
