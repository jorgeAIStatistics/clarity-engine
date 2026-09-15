"""Live Claude gold-set evaluation; aggregate metrics and sanitized parses only."""
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from .intent import parse_intent,resolve_alias,complete_entities

def main():
    root=Path(__file__).parent
    cases=json.loads((root/'gold.json').read_text());nodes=json.loads((root/'registry.json').read_text())
    def evaluate(case):
        try:
            parsed=complete_entities(parse_intent(case['question']),case['question'],nodes)
            matched={n['id'] for e in parsed.entities if (n:=resolve_alias(e,nodes))}
            expected=set(case['expected'])
            # Only assess known-registry entities; free-span entities are reported separately.
            return dict(question=case['question'],expected=sorted(expected),matched=sorted(matched),tp=len(matched&expected),fp=len(matched-expected),fn=len(expected-matched),forbidden=sorted(matched&set(case['forbidden'])),intent=parsed.model_dump())
        except Exception as e:return dict(question=case['question'],error=type(e).__name__,tp=0,fp=0,fn=len(case['expected']),forbidden=[])
    with ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(evaluate,cases))
    tp,fp,fn=[sum(r[k] for r in results) for k in ('tp','fp','fn')]
    report=dict(version='question-intent-v1',cases=20,precision=tp/(tp+fp) if tp+fp else 0,recall=tp/(tp+fn) if tp+fn else 0,true_positives=tp,false_positives=fp,false_negatives=fn,results=results)
    (root/'eval-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='results'}),flush=True)
    for r in results:
        if r['fp'] or r['fn'] or r.get('error'): print(json.dumps(r),flush=True)
if __name__=='__main__':main()
