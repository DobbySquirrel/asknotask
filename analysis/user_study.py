"""Compute the user-study summary from answer sheets and paired execution records."""
import argparse
import glob
from pathlib import Path
import analyze_responses
from common import load, dump
from paired_statistics import summarize
from export_user_study_pairs import export

REPO=Path(__file__).resolve().parents[1]
US=REPO/'outputs/user_study'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=US/'summary.json')
    p.add_argument('--sheets',default=str(US/'answers_*.json'))
    p.add_argument('--sim',type=Path)
    p.add_argument('--replay',nargs='*',type=Path)
    p.add_argument('--scores',type=Path,default=US/'replay_eval/paired_current/scores.json')
    args=p.parse_args()
    tasks=load(US/'reference/tasks.json')
    sheets={int(h['group'])+1:h for h in map(load,map(Path,glob.glob(args.sheets)))}
    sheets=dict(sorted(sheets.items()))
    assert set(sheets)==set(range(1,11)), 'Expected all ten answer sheets'
    histories={side:load(US/f'reference/{side}_simulation.json') for side in ['ours','ambisql']}
    analyze_responses.OUT=US/'analysis_results'
    des=analyze_responses.describe(tasks,sheets,histories)
    rows=load(args.scores);stats=summarize(rows)
    if args.sim:
        mapped=load(args.sim)
        for side in ['ours','ambisql']:
            for row in des[side]['choice_agreement']['rows']:
                if not row['eligible']:continue
                value=mapped.get(row['card_id'])
                choices=value.get('choices',[]) if isinstance(value,dict) else value
                assert choices is not None and set(map(str,choices))==set(row['sim_choices']), 'Simulation input differs from the paired reference'
    if args.replay:
        if len(args.replay) not in [4,5]:raise SystemExit('--replay requires four paired files and optionally Never-Ask')
        conditions=[('ours','sim_visible'),('ours','human_internal'),('ambisql','sim_visible'),('ambisql','human_internal'),('never_ask','never_ask_control')]
        for path,(side,cohort) in zip(args.replay,conditions):
            data=load(path);key=data.get('gold_key','gold');actual={r['qid']:r[key] for r in data['per_question']}
            expected={r['id']:r['ex_match'] for r in rows if r['side']==side and r['cohort']==cohort}
            assert actual==expected, 'Replay files differ from the selected score records'
    export(args.scores,args.scores.parent)
    summary={'n_questions':len(tasks),'n_answer_sheets':len(sheets),
        'n_bird_arcwise':sum(t['dataset']=='bird' for t in tasks),
        'n_ambrosia':sum(t['dataset']=='ambrosia' for t in tasks),
        'n_clambsql':sum(t['dataset']=='clambsql' for t in tasks),
        'asked':{s:des[s]['ratings']['n_cards'] for s in ['ours','ambisql']},
        'clarity':{s:des[s]['ratings']['clarity'] for s in ['ours','ambisql']},
        'usefulness':{s:des[s]['ratings']['usefulness'] for s in ['ours','ambisql']},
        'agree':{s:{'match':des[s]['choice_agreement']['matches'],'total':des[s]['choice_agreement']['n_comparable'],'pct':des[s]['choice_agreement']['percent']} for s in ['ours','ambisql']},
        'settled':{'accepted':des['ours']['auto']['judgments'].get('同意',0),'total':des['ours']['auto']['n_cards'],'pct':des['ours']['auto']['agree_percent']},
        'surveys':[s for h in sheets.values() for s in h['surveys']],
        'ex_simulated':{s:stats['metrics']['sim_visible'][s]['ex_percent'] for s in ['ours','ambisql']},
        'ex_participants':{s:stats['metrics']['human_internal'][s]['ex_percent'] for s in ['ours','ambisql']},
        'confusion':{s:stats['human_vs_sim'][s]['matrix']['cells'] for s in ['ours','ambisql']},
        'flips':{s:{'to_correct':stats['human_vs_sim'][s]['mcnemar']['only_b'],'to_wrong':stats['human_vs_sim'][s]['mcnemar']['only_a']} for s in ['ours','ambisql']},
        'mcnemar':{s:stats['human_vs_sim'][s]['mcnemar'] for s in ['ours','ambisql']}}
    summary['ex_simulated']['never_ask']=stats['metrics']['never_ask_control']['never_ask']['ex_percent']
    dump(args.out,summary)
    print('wrote',args.out)
    for k in ['ex_simulated','ex_participants','flips']:print(k,summary[k])

if __name__=='__main__':main()
