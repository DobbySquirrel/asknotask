"""Original serializers and parser template, extracted without host paths or credentials."""
from __future__ import annotations
import json
import copy
import re
from pathlib import Path
from types import SimpleNamespace

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def dump(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def selected_reading(card, answer, audit, source):
    """Visible option IDs remain original indices; never guess an answer."""
    opts = {str(option['i']): option['text'] for option in card['options']}
    choices = [str(i) for i in answer.get('choices', [])]
    if any(i not in opts for i in choices):
        raise ValueError(f'invisible/invalid option: {card}, {choices}')
    is_other = any(i == 'other' or re.search(r'Others|都不是', opts[i], re.I) for i in choices)
    if is_other:
        text = (answer.get('other') or '').strip()
        if not text:
            raise ValueError('Others must contain a nonempty answer')
        return text
    if answer.get('_free_history'):
        return answer['_free_history']
    if not choices:
        audit.append({'source': source, 'card_id': card.get('card_id', card.get('qid_local')), 'status': 'no_historical_answer_not_imputed'})
        return None
    values = [opts[i] for i in choices]
    return values[0] if len(values) == 1 else values

def tree_paths(evidence):
    """Read original branch locations; do not regenerate ambiguity categories."""
    paths, stack = {}, []
    for line in evidence.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip())
        if stripped == 'root':
            stack = []
            continue
        if stripped.startswith('Q: ') and ' | A:' in stripped:
            question = stripped[3:].split(' | A:', 1)[0]
            paths[question] = [label for depth, label in stack if depth < indent]
            continue
        if indent > 0:
            while stack and stack[-1][0] >= indent:
                stack.pop()
            stack.append((indent, stripped))
    return paths

"""CLEAR official single-SQL parser prompt (dataset/parser.py PROMPT_BASE)."""


PROMPT_BASE = """## Text-to-SQL task
### The task is to write SQL queries based on the provided questions in English. 
### Questions can take the form of an instruction or command. 
### Do not include any explanations, and do not select extra columns beyond those requested in the question.
### Use Evidence / user clarifications when present.
### Target database is SQLite. Do NOT copy MySQL/generic functions from Evidence.
### Forbidden: YEAR(), MONTH(), DAY(), SUBSTRING(), SUBTRACT(), CURDATE().
### Use strftime('%Y', col), strftime('%m', col), substr(col, ...), and CAST(... AS INTEGER) instead.
### Mapping snippets are already table.column — do not concatenate the column name again
### (never emit table.col.col or alias."col.col").

Given the following SQLite database schema:

[SCHEMA_WITH_CONTENT]

Evidence:
[EVIDENCE]

Answer the following:
[QUESTION]

SQL:"""


def format_parser_base(schema_with_content: str, question: str, evidence: str = "") -> str:
    return (
        PROMPT_BASE
        .replace("[SCHEMA_WITH_CONTENT]", schema_with_content or "")
        .replace("[EVIDENCE]", evidence.strip() if evidence and str(evidence).strip() else "NULL")
        .replace("[QUESTION]", question or "")
    )

BAD_CARD="bird:1507#ambi1"
UNANSWERABLE_HUMAN_CARD="clambsql:299#ambi2"
base=SimpleNamespace(selected_reading=selected_reading,tree_paths=tree_paths)
def original_b_prefix(evidence):
    marker=re.search(r'(?m)^root\s*$',evidence)
    if not marker:return evidence.rstrip()
    prefix=evidence[:marker.start()].rstrip();suffix=[]
    lines=evidence[marker.end():].splitlines()
    for n,line in enumerate(lines):
        if line.strip() and not line[0].isspace():suffix=lines[n:];break
    return '\n\n'.join(s for s in [prefix,'\n'.join(suffix).strip()] if s)

def render_repeated_tree(pairs,paths):
    # List children preserve identical questions as distinct responses.
    tree=[]
    for question,answer in pairs:
        node=tree
        for label in paths.get(question,['Participant-visible clarifications']):
            existing=next((entry for entry in node if entry[0]=='branch' and entry[1]==label),None)
            if existing is None:existing=['branch',label,[]];node.append(existing)
            node=existing[2]
        node.append(['leaf',question,answer])
    lines=['root']
    def emit(node,indent):
        for kind,label,value in node:
            if kind=='branch':lines.append(' '*indent+label);emit(value,indent+2)
            else:
                text=json.dumps(value,ensure_ascii=False) if isinstance(value,list) else str(value).replace('\n','\\n')
                lines.append(' '*indent+'Q: '+label+' | A: '+text)
    emit(tree,2)
    return '\n'.join(lines) if pairs else ''

def history_record(card,history,side):
    cid=card.get('card_id',card.get('qid_local'))
    return next((r for r in history.get('cards' if side=='ours' else 'questions',[]) if r.get('card_id',r.get('qid_local'))==cid),{})

def reading(card,human,history,side,cohort,audit):
    cid=card.get('card_id',card.get('qid_local'))
    if cid==BAD_CARD:
        audit.append({'card_id':cid,'cohort':cohort,'status':'malformed_stimulus_omitted_in_both_cohorts'});return None
    if cid==UNANSWERABLE_HUMAN_CARD and cohort=='human_internal':
        assert not human['ask'][cid]['choices']
        audit.append({'card_id':cid,'cohort':cohort,'status':'known_unanswerable_card_no_human_choice_no_imputation'});return None
    if cohort=='sim_visible':
        record=history_record(card,history,side)
        if record.get('sim_abstain'):
            # The author explicitly states Abstain entered simulated evidence.
            # Keep the historical answer, without exposing an Abstain human choice.
            values=[record['options'][int(i)] for i in record['sim_indices']]
            assert 'Abstain' in values
            audit.append({'card_id':cid,'cohort':cohort,'status':'historical_abstain_retained_in_sim_evidence','values':values})
            return values
        if record.get('sim_free_text'):return record['sim_free_text']
        answer={'choices':list(map(str,record.get('sim_indices') or []))}
    else:answer=human.get('ask',{}).get(cid,{})
    opts={str(o['i']):o['text'] for o in card['options']}
    choices=set(map(str,answer.get('choices',[])))
    others={i for i,v in opts.items() if i=='other' or re.search('Others|都不是',v,re.I)}
    if choices & others:
        text=(answer.get('other') or '').strip()
        if text:return text
        audit.append({'card_id':cid,'cohort':cohort,'status':'selected_others_without_free_text_omitted','choices':sorted(choices)});return None
    return base.selected_reading(card,answer,audit,cohort)

def evidence(task,side,cohort,human,history,trace,fixed,audit,*,keep_auto=False):
    original=trace['input']['evidence'] or ''
    if side=='ours':
        prefix=original.split('User clarification:',1)[0].rstrip();items=copy.deepcopy(fixed[task['id']])
        ans=human['answers'].get(task['id']+'|system_a',{})
        for card in task['system_a']['ask']:
            value=reading(card,ans,history,side,cohort,audit)
            if value is not None:items.append({'nl_span':card['span'],'type':card['type'],'interpretation':' | '.join(value) if isinstance(value,list) else value})
        for card in task['system_a']['auto']:
            judgment=ans['auto'][card['card_id']]['judgment'] if cohort=='human_internal' else '同意'
            if keep_auto or judgment!='不同意':items.append({'nl_span':card['span'],'type':card['type'],'interpretation':card['reading']})
        assert items[:len(fixed[task['id']])]==fixed[task['id']]
        return prefix+'\nUser clarification: '+json.dumps(items,ensure_ascii=False)
    ans=human['answers'].get(task['id']+'|system_b',{});pairs=[]
    for card in task['system_b']['questions']:
        value=reading(card,ans,history,side,cohort,audit)
        if value is not None:pairs.append((card['question'],value))
    tree=render_repeated_tree(pairs,base.tree_paths(original))
    assert len(re.findall(r'(?m)^\s*Q: ',tree))==len(pairs)
    return (original_b_prefix(original)+'\n\n'+tree).strip()
