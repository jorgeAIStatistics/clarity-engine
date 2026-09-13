"""Validate selected-source enrichment before publication or frontend export."""
import hashlib
import math
import re


def validate_enrichment(catalog, snapshot):
    sources=snapshot['sources']
    for entity in catalog['entities']:
        seen=set()
        for study in entity['studies']:
            if not study.get('extraction'):continue
            pmid=study['pmid']
            if pmid in seen:raise ValueError('Duplicate publication within profile')
            seen.add(pmid)
            source=sources[pmid];text=source['abstract']
            if study.get('doi')!=source.get('doi') or study['url']!=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/':raise ValueError('Source identity mismatch')
            if study['extraction'].get('source_sha256')!=source['sha256']:raise ValueError('Extraction source hash mismatch')
            if study['abstract']!=text or hashlib.sha256(text.encode()).hexdigest()!=source['sha256']:raise ValueError('Source integrity mismatch')
            if study['review_status']!='automated_appraisal' or study['extraction']['human_verified']:raise ValueError('Enrichment cannot claim human verification')
            if study.get('n') is not None and (isinstance(study['n'],bool) or study['n']<=0):raise ValueError('Invalid sample size')
            spans=[study['population_span'],study['scope_passage']]
            for finding in study.get('findings',[]):
                if finding['quote']!=finding['source_span']['text']:raise ValueError('Quote mismatch')
                effect=finding['effect'];values=[effect['estimate']]+[effect[k] for k in ('lower','upper') if effect.get(k) is not None]
                if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):raise ValueError('Invalid numeric estimate')
                if effect.get('lower') is not None and not effect['lower']<=effect['estimate']<=effect['upper']:raise ValueError('Invalid interval')
                if effect['measure'] in ('sensitivity','specificity'):
                    maximum=100 if effect['units']=='percent' else 1
                    if any(v<0 or v>maximum for v in values):raise ValueError('Invalid accuracy probability')
                # Deterministic check that each reported number actually appears in the retained passage.
                quote=finding['quote'].replace('·','.').replace('−','-')
                numbers={float(n) for n in re.findall(r'(?<![\d.])(?:\d*\.\d+|\d+)(?![\d.])',quote)}
                if not all(v in numbers for v in values):raise ValueError('Estimate absent from source passage')
                spans.append(finding['source_span'])
            for span in spans:
                if span['source_id']!='pmid:'+pmid or not 0<=span['start']<span['end']<=len(text) or text[span['start']:span['end']]!=span['text']:raise ValueError('Invalid source span')
    return True
