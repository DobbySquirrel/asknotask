"""Recompute agreement, rating means and confirmed group surveys (offline)."""
import argparse
import collections
import json
import re
import statistics
from pathlib import Path
from types import SimpleNamespace
from common import load,dump,history_record,BAD_CARD,UNANSWERABLE_HUMAN_CARD
base=SimpleNamespace(dump=dump)
def describe(tasks,humans,histories):
    result={}
    for side,key in [('ours','system_a'),('ambisql','system_b')]:
        agreement=[];ratings=[];task_means=[];judgments=[];surveys=[]
        for t in tasks:
            h=humans[t['group']+1];ans=h['answers'].get(t['id']+'|'+key,{});task_r=[]
            for c in t[key].get('ask',t[key].get('questions',[])):
                cid=c.get('card_id',c.get('qid_local'));record=history_record(c,histories[side][t['id']],side)
                actual=set(map(str,ans['ask'][cid]['choices']));expected=set(map(str,record.get('sim_indices') or []));valid={str(o['i']) for o in c['options']}
                reason=('malformed_stimulus' if cid==BAD_CARD else 'known_unanswerable_human_card' if cid==UNANSWERABLE_HUMAN_CARD and not actual else 'hidden_abstain' if record.get('sim_abstain') else 'free_history_without_visible_option_mapping' if record.get('sim_free_text') and not expected else 'missing_or_unmapped_simulation_answer' if not expected else 'invisible_simulation_choice' if not expected<=valid else None)
                agreement.append({'id':t['id'],'group':t['group']+1,'card_id':cid,'human_choices':sorted(actual),'sim_choices':sorted(expected),'eligible':reason is None,'exclusion_reason':reason,'exact_set_match':actual==expected if reason is None else None,'human_free_text':ans['ask'][cid].get('other'),'sim_free_text':record.get('sim_free_text')})
                r={'id':t['id'],'group':t['group']+1,'card_id':cid,**ans['ratings'][cid]};ratings.append(r);task_r.append(r)
            if task_r:task_means.append({'id':t['id'],'group':t['group']+1,'understand':statistics.mean(r['understand'] for r in task_r),'worth':statistics.mean(r['worth'] for r in task_r)})
            judgments.extend({'id':t['id'],'card_id':cid,**a} for cid,a in ans.get('auto',{}).items())
        for g,h in humans.items():surveys.append({'assignment':g,**next(s for s in h['surveys'] if s['system']==('System A' if side=='ours' else 'System B'))})
        eligible=[r for r in agreement if r['eligible']];clean=[r for r in ratings if r['card_id']!=BAD_CARD]
        result[side]={'choice_agreement':{'n_cards':len(agreement),'n_comparable':len(eligible),'matches':sum(r['exact_set_match'] for r in eligible),'percent':100*sum(r['exact_set_match'] for r in eligible)/len(eligible),'exclusions':dict(collections.Counter(r['exclusion_reason'] for r in agreement if not r['eligible'])),'rows':agreement},
            'ratings':{'n_cards':len(ratings),'clarity':statistics.mean(r['understand'] for r in ratings),'usefulness':statistics.mean(r['worth'] for r in ratings),'without_malformed':{'n_cards':len(clean),'clarity':statistics.mean(r['understand'] for r in clean),'usefulness':statistics.mean(r['worth'] for r in clean)},'task_weighted':{'n_tasks':len(task_means),'clarity':statistics.mean(r['understand'] for r in task_means),'usefulness':statistics.mean(r['worth'] for r in task_means)},'rows':ratings,'task_rows':task_means},
            'auto':{'n_cards':len(judgments),'judgments':dict(collections.Counter(r['judgment'] for r in judgments)),'agree_percent':100*sum(r['judgment']=='同意' for r in judgments)/len(judgments) if judgments else None,'rows':judgments},
            'surveys':{'n_groups':10,'burden_mean':statistics.mean(r['burden'] for r in surveys),'willingness_mean':statistics.mean(r['willing'] for r in surveys),'rows':surveys}}
    base.dump(OUT/'descriptive_metrics.json',result)
    return result

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    a=p.parse_args();OUT=a.root/"outputs/user_study/analysis_results"
    tasks=load(a.root/"outputs/user_study/reference/tasks.json")
    humans={n:load(a.root/f"outputs/user_study/answers_{n}.json") for n in range(1,11)}
    histories={s:load(a.root/f"outputs/user_study/reference/{s}_simulation.json") for s in ["ours","ambisql"]}
    result=describe(tasks,humans,histories)
    print(json.dumps({s:{"agreement":{k:v for k,v in result[s]["choice_agreement"].items() if k!="rows"},"clarity":result[s]["ratings"]["clarity"],"usefulness":result[s]["ratings"]["usefulness"]} for s in ["ours","ambisql"]},indent=2))
