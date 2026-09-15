"""Gold-set evaluation: deterministic MENTIONS linking (CI, no keys) and the live Claude parse.
Aggregate metrics and sanitized parses only."""
import argparse
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from .intent import parse_intent,resolve_alias,complete_entities,ResearchIntent

ROOT=Path(__file__).parent

def load():
    return json.loads((ROOT/'gold.json').read_text()),json.loads((ROOT/'registry.json').read_text())

def score(results):
    tp,fp,fn=[sum(r[k] for r in results) for k in ('tp','fp','fn')]
    return dict(precision=tp/(tp+fp) if tp+fp else 0,recall=tp/(tp+fn) if tp+fn else 0,true_positives=tp,false_positives=fp,false_negatives=fn)

def compare(case,matched):
    expected=set(case['expected'])
    return dict(question=case['question'],expected=sorted(expected),matched=sorted(matched),tp=len(matched&expected),fp=len(matched-expected),fn=len(expected-matched),forbidden=sorted(matched&set(case['forbidden'])))

def mentions(cases,nodes):
    """Question MENTIONS from exact question spans resolved by registry aliases: the path CI runs."""
    results=[]
    for case in cases:
        blank=ResearchIntent.model_construct(entities=[],outcomes=[],population=None,setting_exposure=[],intents=[],explicitly_not_in_question=[])
        results.append(compare(case,{n['id'] for e in complete_entities(blank,case['question'],nodes).entities if (n:=resolve_alias(e,nodes))}))
    return dict(method='rules: exact question spans resolved by registry aliases',cases=len(cases),**score(results),
                forbidden=[r for r in results if r['forbidden']],mismatches=[r for r in results if r['fp'] or r['fn']])

def live(cases,nodes):
    def evaluate(case):
        try:
            parsed=complete_entities(parse_intent(case['question']),case['question'],nodes)
            row=compare(case,{n['id'] for e in parsed.entities if (n:=resolve_alias(e,nodes))})
            if case.get('intents'):row['intents_missing']=sorted(set(case['intents'])-set(parsed.intents))
            return dict(row,intent=parsed.model_dump())
        except Exception as e:return dict(question=case['question'],error=type(e).__name__,tp=0,fp=0,fn=len(case['expected']),forbidden=[])
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(evaluate,cases))
    return dict(method='claude structured parse, then registry aliases',cases=len(cases),**score(results),results=results)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules',action='store_true',help='Deterministic MENTIONS evaluation only; no API calls')
    args=parser.parse_args(argv)
    cases,nodes=load()
    report=dict(version='question-intent-v2',mentions=mentions(cases,nodes))
    if not args.rules:report['live']=live(cases,nodes)
    print(json.dumps({k:({x:y for x,y in v.items() if x not in ('results',)} if isinstance(v,dict) else v) for k,v in report.items()},ensure_ascii=False),flush=True)
    if not args.rules:(ROOT/'eval-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report
if __name__=='__main__':main()
