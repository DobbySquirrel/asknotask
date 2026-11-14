"""Offline paired analysis of A-round exports. No model calls or SQL scoring.

Official Condition A numbers live in outputs/user_study_wo_nl/analysis_results/round_a/summary.json.
Raw response exports are not in the repository; pass --a1 and --a2 to regenerate.
Raw exports are never modified. Output is descriptive agreement, not gold accuracy.
"""
import argparse
import collections
import csv
import hashlib
import json
from pathlib import Path


def load(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f'Duplicate JSON key in {path}: {key}')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate(sheet, cases):
    require(sheet.get('group') == 'A', 'Expected an A-round export')
    answers = sheet['answers']
    require(set(answers) == {c['case_id'] for c in cases}, 'Case IDs differ from reference')
    for case in cases:
        answer = answers[case['case_id']]
        require(answer['case_id'] == case['case_id'] and answer['question_id'] == case['question_id'], 'Answer identity mismatch')
        require(answer.get('completion_status') == 'complete', 'Incomplete answer')
        require(answer.get('stage1_interpretation', '').strip() or answer.get('stage1_unable'), 'Missing initial interpretation')
        selected = list(map(str, answer['selected_option_ids']))
        valid = {str(o['option_id']) for o in case['stage2']['options']}
        require(len(selected) == len(set(selected)), 'Duplicate selected option')
        status = answer['answer_status']
        require(status in ('options', 'others', 'unsure'), 'Invalid status')
        require(set(selected) <= valid, 'Invalid option ID')
        require(bool(selected) if status == 'options' else not selected, 'Invalid response-mode combination')
        require(status != 'others' or answer.get('others_text', '').strip(), 'Empty Others text')
        require(answer.get('interpretation_changed') in ('yes', 'no'), 'Missing change diagnosis')
        require(answer['interpretation_changed'] != 'yes' or answer.get('interpretation_changed_note', '').strip(), 'Missing change explanation')
    return answers


def summarize(rows):
    eligible = [r for r in rows if r['a1_status'] == r['a2_status'] == 'options']
    matches = sum(r['exact_selected_set_match'] for r in eligible)
    return {
        'n_cases': len(rows),
        'exact_agreement_all': {'matches': matches, 'denominator': len(rows), 'percent': 100 * matches / len(rows)},
        'conditional_exact_agreement_both_options': {'matches': matches, 'denominator': len(eligible), 'percent': 100 * matches / len(eligible) if eligible else None},
        'mean_jaccard_both_options': sum(r['jaccard'] for r in eligible) / len(eligible) if eligible else None,
        'scorer_support': {key: sum(r['scorer_support'] == key for r in rows) for key in ('both_selected', 'one_selected', 'neither_selected', 'unsure')},
        'scorer_supported_by_each': {p: sum(r['scorer_' + p + '_selected'] for r in rows) for p in ('a1', 'a2')},
        'response_status_counts': {p: dict(collections.Counter(r[p + '_status'] for r in rows)) for p in ('a1', 'a2')},
        'interpretation_changed_counts': {p: dict(collections.Counter(r[p + '_changed'] for r in rows)) for p in ('a1', 'a2')},
        'difference_classes': dict(collections.Counter(r['difference_class'] for r in rows)),
    }


def main():
    repo = Path(__file__).resolve().parents[1]
    root = repo / 'outputs/user_study_wo_nl'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--a1', type=Path, required=True, help='Raw A1 answer sheet (archived off-tree)')
    parser.add_argument('--a2', type=Path, required=True, help='Raw A2 answer sheet (archived off-tree)')
    parser.add_argument('--cases', type=Path, default=root / 'reference/A_cases.json')
    parser.add_argument('--out', type=Path, default=root / 'analysis_results/round_a')
    args = parser.parse_args()
    inputs = [args.a1.resolve(), args.a2.resolve(), args.cases.resolve()]
    out = args.out.resolve()
    require(not any(p == out or out in p.parents for p in inputs), 'Output directory must not contain input files')
    cases = load(args.cases)
    require(bool(cases), 'Empty case list')
    require(len(cases) == len({c['case_id'] for c in cases}) == len({c['question_id'] for c in cases}), 'Duplicate case or question ID')
    a, b = load(args.a1), load(args.a2)
    require(a['participant_id'] != b['participant_id'], 'Two distinct source response IDs required')
    aa, bb = validate(a, cases), validate(b, cases)
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    rows = []
    for case in cases:
        cid = case['case_id']
        x, y = aa[cid], bb[cid]
        meta = case['organizer_only']
        valid = {str(o['option_id']) for o in case['stage2']['options']}
        top = str(meta['scorer_top1'])
        require(meta['auto_source'] == 'scorer' and top in valid, 'Invalid scorer reference')
        require(meta['entropy'] <= meta['theta'], 'Case is above frozen threshold')
        sx, sy = set(map(str, x['selected_option_ids'])), set(map(str, y['selected_option_ids']))
        both = x['answer_status'] == y['answer_status'] == 'options'
        support_n = int(top in sx) + int(top in sy)
        difference = ('same_option_set' if sx == sy else 'overlapping_option_sets' if sx & sy else 'disjoint_option_sets') if both else 'non_option_response_pair'
        rows.append({
            'case_id': cid, 'question_id': case['question_id'], 'dataset': case['dataset_label'],
            'supplement': meta['sampling_info']['supplement'], 'question': case['question'],
            'a1_status': x['answer_status'], 'a2_status': y['answer_status'],
            'a1_options': sorted(sx), 'a2_options': sorted(sy),
            'a1_initial': x['stage1_interpretation'], 'a2_initial': y['stage1_interpretation'],
            'a1_others': x['others_text'], 'a2_others': y['others_text'],
            'a1_changed': x['interpretation_changed'], 'a2_changed': y['interpretation_changed'],
            'exact_selected_set_match': sx == sy if both else False,
            'jaccard': len(sx & sy) / len(sx | sy) if both else None,
            'difference_class': difference, 'scorer_option': top,
            'scorer_a1_selected': top in sx, 'scorer_a2_selected': top in sy,
            'scorer_support': 'unsure' if 'unsure' in (x['answer_status'], y['answer_status']) else ('neither_selected', 'one_selected', 'both_selected')[support_n],
        })
    result = summarize(rows)
    result['by_dataset'] = {ds: summarize([r for r in rows if r['dataset'] == ds]) for ds in sorted({r['dataset'] for r in rows})}
    result['by_sampling_source'] = {k: summarize(rr) for k, rr in [('original', [r for r in rows if not r['supplement']]), ('supplement', [r for r in rows if r['supplement']])] if rr}
    result['response_ids'] = [a['participant_id'], b['participant_id']]
    out.mkdir(parents=True, exist_ok=True)
    for name, value in [('summary.json', result), ('paired_details.json', rows)]:
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    with (out / 'paired_details.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, list) else v for k, v in row.items()})
    (out / 'paper_results.txt').write_text(
        f"The two human annotations have identical selected option sets on {result['exact_agreement_all']['matches']} of the {len(rows)} questions ({result['exact_agreement_all']['percent']:.1f}%). "
        f"The scorer-selected interpretation is included in both annotations on {result['scorer_support']['both_selected']} questions ({100*result['scorer_support']['both_selected']/len(rows):.1f}%) "
        f"and in exactly one annotation on {result['scorer_support']['one_selected']} questions ({100*result['scorer_support']['one_selected']/len(rows):.1f}%).\n", encoding='utf-8')
    require(all(hashlib.sha256(p.read_bytes()).hexdigest() == before[str(p)] for p in inputs), 'Input file changed during analysis')
    print(json.dumps({k: result[k] for k in ('n_cases', 'exact_agreement_all', 'scorer_support')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
