"""Retrospective ranking diagnosis; selection on a fixed subset of official train.

All profiles are declared before execution. Gold labels only score outputs.
Previously seen official test data must not be described as an untouched holdout.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from evaluation.evaluate_rag_tool import gold_spans, QUESTIONS
from rag_core.index import covered_chars
from rag_core.ranking import POLICIES, select_candidates
from tools.rag_tool import RAGTool


def hit(span, chunks):
    start, end, _ = span
    return covered_chars(start, end, [(c['start'], c['end']) for c in chunks]) / (end-start) >= .8


def run(path, split, selected_policy=None):
    raw = path.read_bytes()
    docs = json.loads(raw)['data']
    if split == 'development':
        # Stable 20% of train; selection rule depends on title hash, not labels.
        docs = [d for d in docs if int(hashlib.sha256(d['title'].encode()).hexdigest(), 16) % 5 == 0]
    policies = list(POLICIES) if split == 'development' else ['protected', selected_policy]
    policies = list(dict.fromkeys(policies))
    names = ['bm25', 'dense_raw', *policies]
    stats = {name: defaultdict(lambda: {'n': 0, 'r1': 0, 'r5': 0, 'exact5': 0}) for name in names}
    diag = defaultdict(int)
    failures = []
    misses = []
    tool = RAGTool({'semantic': False, 'embedding_local_files_only': True})
    started = time.perf_counter()
    for number, doc in enumerate(docs, 1):
        title = doc['title']
        para = doc['paragraphs'][0]
        context = para['context']
        prep = tool.prepare_text(title, context)
        if prep['status'] != 'SUCCESS':
            failures.append({'document': title, 'reason': prep['reason']})
        index = tool._indexes.get(title, {}).get('index')
        for category, question in QUESTIONS.items():
            spans = gold_spans(para['qas'], category, context)
            if not spans:
                continue
            profile = tool._category_queries(category)
            if index is not None:
                lexical = profile['lexical'] + ' ' + question
                semantic = question + '\nRetrieval intent: ' + profile['semantic']
                dense = index.dense_index.search(semantic, 20)
                sparse = index.sparse_index.search(lexical, 20)
                raw_dense = index.dense_index.search(question, 20)
                outputs = {'bm25': sparse[:5], 'dense_raw': raw_dense[:5]}
                for policy in policies:
                    outputs[policy] = select_candidates(dense, sparse, index.chunks, category, 5, policy=policy)
                if tool.config['ranking_policy'] in outputs:
                    actual = tool.retrieve(title, question, 5)['text']
                    expected = outputs[tool.config['ranking_policy']]
                    assert [(c['start'], c['end']) for c in actual] == [(c['start'], c['end']) for c in expected], 'Tool/experiment ranking drift'
            else:
                dense, sparse = [], []
                outputs = {name: [] for name in names}
            for span in spans:
                diag['gold_spans'] += 1
                b, d, union = hit(span, sparse), hit(span, dense), hit(span, sparse+dense)
                diag['bm25_candidate20_hits'] += b
                diag['dense_candidate20_hits'] += d
                diag['union_candidate40_hits'] += union
                diag['dense_rescues_bm25_at20'] += d and not b
                diag['union_hits_lost_by_protected_top5'] += union and not hit(span, outputs['protected'])
                if index is not None:
                    max_five = sorted(index.chunks, key=lambda c: covered_chars(span[0], span[1], [(c['start'], c['end'])]), reverse=True)[:5]
                    diag['oracle_chunk_top5_hits'] += hit(span, max_five)
                for name in names:
                    row = stats[name][category]
                    result = outputs[name]
                    row['n'] += 1
                    row['r1'] += hit(span, result[:1])
                    row['r5'] += hit(span, result)
                    # Position-aware: a repeated phrase elsewhere is not this gold occurrence.
                    row['exact5'] += any(c['start'] <= span[0] and span[1] <= c['end'] for c in result)
                if not hit(span, outputs['protected']) and len(misses) < 30:
                    misses.append({'document': title, 'category': category, 'gold_start': span[0],
                                   'gold_end': span[1], 'in_candidate_union': union,
                                   'dense_only_rescue': d and not b})
        if number % 20 == 0:
            print(f'{split}: {number}/{len(docs)}', flush=True)
    reports = {}
    for name, categories in stats.items():
        n = sum(r['n'] for r in categories.values())
        reports[name] = {
            'gold_spans': n,
            'recall@1': sum(r['r1'] for r in categories.values()) / n,
            'recall@5': sum(r['r5'] for r in categories.values()) / n,
            'position_exact@5': sum(r['exact5'] for r in categories.values()) / n,
            'macro_recall@5': sum(r['r5']/r['n'] for r in categories.values()) / len(categories),
            'categories': {c: {**r, 'recall@5': r['r5']/r['n']} for c,r in categories.items()},
        }
    choice = max(policies, key=lambda p: (reports[p]['recall@5'], reports[p]['macro_recall@5'], reports[p]['recall@1'])) if split == 'development' else selected_policy
    return {'split': split, 'dataset_sha256': hashlib.sha256(raw).hexdigest(),
            'dataset_file': path.name,
            'config': {k:tool.config[k] for k in ('embedding_model','embedding_revision',
                      'chunk_size','chunk_overlap','chunk_strategy','search_unit',
                      'hybrid_rrf_k','hybrid_dense_weight','hybrid_bm25_weight',
                      'hybrid_dense_admission_threshold')},
            'candidate_k_per_channel': 20, 'returned_k': 5,
            'documents': len(docs), 'document_titles': [d['title'] for d in docs],
            'selected_policy': choice, 'profiles': reports, 'diagnostics': dict(diag),
            'failures': failures, 'miss_examples': misses,
            'tool_output_parity_checked': True,
            'elapsed_seconds': round(time.perf_counter()-started, 3),
            'limitations': 'Retrospective: all official splits were previously inspected. No fresh holdout claim.',
            'selection_rule': 'max development micro Recall@5, macro Recall@5, Recall@1; fixed 20% hash split of train'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--split', choices=['development', 'test_replay'], default='development')
    parser.add_argument('--selection', type=Path, default=ROOT/'results/v14_development.json')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    filename = 'train_separate_questions.json' if args.split == 'development' else 'test.json'
    policy = None if args.split == 'development' else json.loads(args.selection.read_text())['selected_policy']
    result = run(ROOT.parent/'data/cuad/source'/filename, args.split, policy)
    out = args.out or ROOT/f'results/v14_{args.split}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in ('selected_policy','documents','diagnostics')}, indent=2))
    for name, row in result['profiles'].items():
        print(name, {k: round(v, 4) for k,v in row.items() if k not in ('categories', 'gold_spans')})

if __name__ == '__main__':
    main()
