"""Export matched per-question execution records for the user-study figure."""
import argparse
from pathlib import Path
from common import load, dump
from paired_statistics import summarize

def export(scores, output):
    rows=load(scores)
    assert len(rows)==500
    assert len({(r['id'],r['side'],r['cohort']) for r in rows})==500
    statistics=summarize(rows)
    for side in ['ours','ambisql']:
        for cohort,suffix in [('sim_visible','sim'),('human_internal','part')]:
            selected=sorted((r for r in rows if r['side']==side and r['cohort']==cohort),key=lambda r:r['id'])
            assert len(selected)==100 and all(type(r['ex_match']) is bool for r in selected)
            hits=sum(r['ex_match'] for r in selected)
            dump(output/f'{side}_{suffix}.json',{'n':100,'correct':{'gold':hits},'ex':{'gold':float(hits)},'gold_key':'gold',
                'per_question':[{'qid':r['id'],'gold':r['ex_match'],'sql':r['predicted_sql'],'request_key':r['request_key']} for r in selected]})
    dump(output/'pair_statistics.json',statistics)
    return statistics

if __name__=='__main__':
    default=Path(__file__).resolve().parents[1]/'outputs/user_study/replay_eval/paired_current'
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--scores',type=Path,default=default/'scores.json');p.add_argument('--out',type=Path,default=default);a=p.parse_args()
    result=export(a.scores,a.out)
    for side in ['ours','ambisql']:
        m=result['human_vs_sim'][side]
        print(side,'matrix=',m['matrix']['cells'],'delta_pp=',m['delta_pp'],'p=',m['mcnemar']['p_exact'])
