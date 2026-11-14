"""Fig. 5: paired per-question user-study execution outcomes."""
import argparse
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch, Rectangle

HERE=Path(__file__).resolve().parent
REPO=HERE.parent.parent
SYSTEMS={'AmbiSQL':'ambisql','Ours':'ours'}
FIXED,BROKEN='#1b7837','#d95f02'

def correctness(path):
    d=json.loads(path.read_text(encoding='utf-8'));key=d.get('gold_key','gold')
    rows=d['per_question']
    if len(rows)!=100 or len({str(r['qid']) for r in rows})!=100:
        raise SystemExit(f'{path}: expected 100 unique question IDs')
    if any(type(r.get(key)) is not bool for r in rows):
        raise SystemExit(f'{path}: correctness values must be JSON booleans')
    return {str(r['qid']):r[key] for r in rows}

def confusion(sim,part):
    if set(sim)!=set(part):raise SystemExit('Question IDs differ between paired files')
    m=[[0,0],[0,0]]
    for q in sim:m[0 if sim[q] else 1][0 if part[q] else 1]+=1
    return m

def load(replay):
    scores=replay/'scores.json'
    records=json.loads(scores.read_text(encoding='utf-8')) if scores.exists() else None
    data={}
    for name,stem in SYSTEMS.items():
        paths=[replay/f'{stem}_{suffix}.json' for suffix in ['sim','part']]
        if any(not p.is_file() for p in paths):raise SystemExit(f'Missing paired execution results in {replay}')
        sim,part=map(correctness,paths)
        if records is not None:
            for cohort,actual in [('sim_visible',sim),('human_internal',part)]:
                expected={r['id']:r['ex_match'] for r in records if r['side']==stem and r['cohort']==cohort}
                if actual!=expected:raise SystemExit(f'{stem} {cohort}: pair files do not match scores.json')
        data[name]=confusion(sim,part)
    return data

def plot(data,out):
    plt.rcParams.update({'font.size':7,'font.family':'serif','axes.linewidth':0.6})
    fig,axes=plt.subplots(1,2,figsize=(3.5,1.85),gridspec_kw={'wspace':0.12})
    for i,(ax,(name,m)) in enumerate(zip(axes,data.items())):
        m=np.array(m);n=m.sum();sim_ex=m[0].sum()*100/n;part_ex=m[:,0].sum()*100/n
        im=ax.pcolormesh(np.arange(3)-0.5,np.arange(3)-0.5,m,cmap='Blues',vmin=0,vmax=n,edgecolors='white',linewidth=1.0)
        ax.set_xlim(-0.5,1.5);ax.set_ylim(1.5,-0.5);ax.set_aspect('equal')
        for row in range(2):
            for col in range(2):
                value=m[row,col];ax.text(col,row,f'{value}\n({value*100/n:.0f}%)',ha='center',va='center',fontsize=7,color='white' if value>0.5*n else '#222222')
        ax.add_patch(Rectangle((-0.46,0.54),0.92,0.92,fill=False,ec=FIXED,lw=1.4))
        ax.add_patch(Rectangle((0.54,-0.46),0.92,0.92,fill=False,ec=BROKEN,lw=1.4,ls=(0,(3,1.5))))
        ax.set_title(f'{name}\nEX: {sim_ex:.0f}% $\\rightarrow$ {part_ex:.0f}%',fontsize=7.5,pad=3)
        ax.set_xticks([0,1],['Correct','Incorrect']);ax.set_yticks([0,1],['Correct','Incorrect'] if i==0 else [])
        ax.set_xlabel("Participants' answers",fontsize=7)
        if i==0:ax.set_ylabel('Simulated answers',fontsize=7)
        ax.tick_params(length=0,labelsize=6.5)
        for spine in ax.spines.values():spine.set_visible(False)
    cb=fig.colorbar(im,ax=axes,fraction=0.04,pad=0.03);cb.set_label('Questions (% of 100)',fontsize=6.5);cb.ax.tick_params(labelsize=6,length=2);cb.outline.set_linewidth(0.5);cb.solids.set_rasterized(False)
    fig.legend([Patch(fc='none',ec=FIXED,lw=1.4),Patch(fc='none',ec=BROKEN,lw=1.4,ls=(0,(3,1.5)))],['Incorrect $\\rightarrow$ correct','Correct $\\rightarrow$ incorrect'],loc='lower center',bbox_to_anchor=(0.45,-0.1),ncol=2,frameon=False,fontsize=6.5,handlelength=1.2,columnspacing=1.2)
    fig.savefig(out,bbox_inches='tight');plt.close(fig)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--replay',type=Path,default=REPO/'outputs/user_study/replay');p.add_argument('--out',type=Path,default=HERE/'user_pairs.pdf');a=p.parse_args()
    data=load(a.replay)
    for name,m in data.items():print(f'{name}: sim {sum(m[0])}, part {m[0][0]+m[1][0]}, fixed {m[1][0]}, broken {m[0][1]}')
    plot(data,a.out);print(f'wrote {a.out}')

if __name__=='__main__':main()
