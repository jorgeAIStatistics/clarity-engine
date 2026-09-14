"""Automated, source-bound release contract for visual evidence reports.

No grade, pooled effect, reconstructed curve or model-written conclusion is emitted.
Every released magnitude is tied to an immutable abstract and exact source span.
"""
import copy
import hashlib
import json
import math
import re
from pathlib import Path

VERSION = 'visual-evidence-v1'
ROOT = Path(__file__).parent
MEASURES = {
    'hazard ratio': ('HR', 'log', 1), 'risk ratio': ('RR', 'log', 1),
    'relative risk': ('RR', 'log', 1), 'odds ratio': ('OR', 'log', 1),
    'rate ratio': ('IRR', 'log', 1), 'mean difference': ('MD', 'linear', 0),
    'standardized mean difference': ('SMD', 'linear', 0),
    'risk difference': ('RD', 'linear', 0), 'partial eta squared': ('Partial η²', 'linear', None),
    'sensitivity': ('Sensitivity', 'linear', None), 'specificity': ('Specificity', 'linear', None),
    'C-index change': ('Δ C-index', 'linear', 0), 'c-index change': ('Δ C-index', 'linear', 0),
    'hazard_ratio': ('HR', 'log', 1), 'hr': ('HR', 'log', 1),
}

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()

def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)

def numbers(text):
    text = text.replace('−', '-').replace('·', '.')
    return [float(x) for x in re.findall(r'(?<![\w.])[-+]?(?:\d*\.\d+|\d+)(?![\w.])', text)]

def span_ok(span, text, pmid):
    return isinstance(span, dict) and span.get('source_id') == 'pmid:'+pmid and \
        type(span.get('start')) is int and type(span.get('end')) is int and \
        0 <= span['start'] < span['end'] <= len(text) and text[span['start']:span['end']] == span.get('text')

def classify(study):
    value = (study.get('design') or study.get('study_type') or '').lower()
    if 'protocol' in value: return 'protocol'
    system=(study.get('population') or '').lower()+' '+value
    if re.search(r'\b(?:animal|mouse|mice|rat|rats|preclinical)\b',system): return 'preclinical'
    if re.search(r'in.?vitro|cell[- ](?:line|culture)',system): return 'mechanism'
    if any(x in value for x in ('meta-analysis', 'systematic review')): return 'synthesis'
    if any(x in value for x in ('guideline', 'regulatory')): return 'guidelines'
    if any(x in value for x in ('randomized', 'randomised', 'controlled trial')): return 'interventional'
    if any(x in value for x in ('cohort', 'observational', 'case-control', 'diagnostic')): return 'observational'
    if any(x in value for x in ('animal', 'mouse', 'rat ')): return 'preclinical'
    if any(x in value for x in ('in vitro', 'in-vitro', 'mechanism')): return 'mechanism'
    return 'unclassified'

def mode(study, finding):
    if finding.get('effect', {}).get('measure') in ('sensitivity', 'specificity'): return 'Diagnostic performance'
    if any(x in finding.get('outcome', '').lower() for x in ('discrimination', 'c-index', 'prediction')): return 'Prediction'
    if classify(study) == 'observational' or (classify(study) == 'synthesis' and re.search(r'prospective|cohort|association|baseline.*levels', (study.get('design') or '')+' '+(study.get('title') or ''), re.I)): return 'Association'
    if classify(study) in ('mechanism','preclinical','unclassified'): return 'Source findings'
    return 'Treatment outcomes'

def release(study, finding):
    """Return a display-safe record or an internal reason. Never coerce numbers."""
    pmid = str(study.get('pmid') or '')
    text = study.get('abstract') or ''
    quote = finding.get('quote')
    effect = finding.get('effect') or {}
    measure = MEASURES.get(effect.get('measure'))
    if not pmid.isdigit() or study.get('url') != f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/': return None, 'source_identity'
    if re.search(r'retract|expression of concern', study.get('title', ''), re.I): return None, 'source_integrity_notice'
    if classify(study) == 'protocol': return None, 'protocol_not_results'
    if hashlib.sha256(text.encode()).hexdigest() != study.get('extraction', {}).get('source_sha256'): return None, 'source_hash'
    if not quote or quote != finding.get('source_span', {}).get('text') or not span_ok(finding.get('source_span'), text, pmid): return None, 'source_span'
    if not all(span_ok(study.get(k), text, pmid) for k in ('population_span', 'scope_passage')): return None, 'context_span'
    if not all(study.get(k) for k in ('population', 'exposure', 'comparator')) or not finding.get('outcome'): return None, 'context_missing'
    if effect.get('origin') != 'reported' or not measure: return None, 'unsupported_measure'
    point, lower, upper = (effect.get(k) for k in ('estimate', 'lower', 'upper'))
    if not finite(point): return None, 'invalid_number'
    interval = lower is not None or upper is not None
    if interval and (not all(finite(v) for v in (lower, upper)) or not lower <= point <= upper): return None, 'invalid_interval'
    values = [point, lower, upper] if interval else [point]
    if measure[1] == 'log' and min(values) <= 0: return None, 'nonpositive_ratio'
    if measure[0] in ('Sensitivity', 'Specificity', 'Partial η²'):
        maximum = 100 if effect.get('units') == 'percent' else 1
        if min(values) < 0 or max(values) > maximum: return None, 'measure_bounds'
    if measure[0] in ('Δ C-index', 'RD') and (min(values) < -1 or max(values) > 1): return None, 'measure_bounds'
    # Recognize signed numbers and interval dashes without losing genuine negatives.
    reported = numbers(quote)
    tokens = [float(x) for x in re.findall(r'\d*\.\d+|\d+', quote.replace('·','.'))]
    if any(v not in (reported if v < 0 else tokens) for v in values): return None, 'number_not_reported'
    level = effect.get('confidence_level')
    if interval and (not finite(level) or not 0 < level < 100 or level not in tokens): return None, 'interval_level'
    if interval:
        # A point and its interval must be one contiguous numerical tuple. This
        # rejects mixing endpoints from different results in the same passage.
        tuples = ([point, level, lower, upper], [point, lower, upper])
        normalized = quote.replace('·', '.').replace('−', '-')
        normalized = re.sub(r'(?<=\d)[–-](?=\d)', ' to ', normalized)
        sequence = numbers(normalized)
        if not any(sequence[i:i+len(t)] == t for t in tuples for i in range(len(sequence))):
            return None, 'interval_tuple'

    if study.get('n') is not None and (type(study['n']) is not int or study['n'] <= 0): return None, 'sample_size'
    identity = digest([pmid, finding['outcome'], effect, study['exposure'], study['comparator']])[:24]
    cohort = study.get('cohort_id')
    context = {k: study.get(k) for k in ('population', 'exposure', 'comparator', 'duration', 'timepoint', 'instrument', 'baseline')}
    checks = ['Source hash', 'Exact passage', 'Reported numbers', 'Measure bounds', 'Population passage']
    flags = ['Abstract-derived context']
    if classify(study) == 'observational': flags.append('Observational association')
    if classify(study) == 'synthesis': flags.append('Published synthesis · overlap possible')
    if not interval: flags.append('Point estimate · interval unreported')
    if not cohort: flags.append('Cohort identity unspecified')
    record = {'id': identity, 'pmid': pmid, 'title': study.get('title'), 'url': study['url'],
        'year': study.get('year'), 'cohort': cohort, 'layer': classify(study), 'design': study.get('design'),
        'outcome': finding['outcome'], 'mode': mode(study, finding), 'metric': measure[0],
        'scale': measure[1], 'nullValue': measure[2], 'unit': effect.get('units') or '',
        'point': point, 'lower': lower, 'upper': upper, 'intervalLevel': level if interval else None,
        'n': study.get('n'), 'context': context, 'quote': quote, 'span': finding['source_span'],
        'populationPassage': study['population_span'], 'scopePassage': study['scope_passage'],
        'sourceHash': study['extraction']['source_sha256'], 'sourceText': text,
        'extractedAt': study['extraction'].get('extracted_at'), 'checks': checks, 'flags': flags,
        'method': VERSION, 'origin': 'reported', 'assessment': 'Automated source validation',
        'compatibilityKey': digest([finding['outcome'], effect.get('measure'), effect.get('units'), context])}
    record['hash'] = digest(record)
    return record, None

def report(target_id, name, studies, related=None):
    records, withheld, unique = {}, [], {}
    for study in studies:
        key = str(study.get('pmid') or study.get('id') or '')
        if key: unique[key] = {'id': key, 'title': study.get('title'), 'year': study.get('year'),
            'layer': classify(study), 'url': study.get('url'), 'cohort': study.get('cohort_id')}
        for finding in study.get('findings', []):
            row, error = release(study, finding)
            if row: records[row['id']] = row
            else: withheld.append({'pmid': key, 'outcome': finding.get('outcome'), 'reason': error})
    result = {'id': target_id, 'name': name, 'version': VERSION, 'records': list(records.values()),
        'studies': list(unique.values()), 'related': related or [],
        'sourceDate': max((r.get('extractedAt') or '' for r in records.values()), default=None),
        'audit': {'withheld': withheld, 'pooling': 'No new pooled model fitted',
            'coverage': 'Selected source set; not an exhaustive search', 'method': VERSION}}
    result['hash'] = digest(result)
    return result

def build_reports():
    catalog = json.loads((ROOT/'catalog.json').read_text())
    overlays = json.loads((ROOT/'intervention_enrichment.json').read_text())['profiles']
    contexts = json.loads((ROOT/'profile_report_context.json').read_text())['profiles']
    reports = {f"entity:{e['id']}": report('entity:'+e['id'], e['name'], e.get('studies', [])) for e in catalog['entities']}
    for key in set(overlays) | set(contexts):
        selected = overlays.get(key, {})
        reports['compound:'+key] = report('compound:'+key, selected.get('name') or key.replace('-', ' '),
            selected.get('studies', []) + contexts.get(key, {}).get('studies', []))
    molecules=json.loads((ROOT/'molecular_context.json').read_text())
    for molecule in molecules.values():
        text=molecule['sourceText']
        if hashlib.sha256(text.encode()).hexdigest()!=molecule['sourceHash']:raise ValueError('Molecular source hash')
        for f in molecule['features']:
            if text[f['start']:f['end']]!=f['quote']:raise ValueError('Molecular source span')
        for target in molecule['targets']:
            if target in reports:reports[target]['molecule']=molecule
    # Paired observations from one source: no invented regression or interpolation.
    source=next(s for e in catalog['entities'] for s in e.get('studies',[]) if s.get('pmid')=='38700053')
    text=source['abstract']
    quoted=next((s for s in re.split(r'(?<=[.!?])\s+(?=[A-Z])',text) if '7.3 vs. 4.0' in s),None)
    if quoted:
        # Splitting on vs. may split the sentence; retain the exact contiguous span.
        start=text.index('At these levels');end=text.index('(all P < .001)',start)+len('(all P < .001)')
        quote=text[start:end]
        groups=[{'label':'LDL-C 130 ±10 mg/dL','low':4.0,'high':7.3},
            {'label':'Non-HDL-C 160 ±10 mg/dL','low':4.6,'high':6.4},
            {'label':'Triglycerides 115 ±10 mg/dL','low':4.6,'high':7.0}]
        if all(g[k] in numbers(quote) for g in groups for k in ('low','high')):
            graphic={'kind':'paired_rates','title':'ApoB discordance at similar lipid levels',
                'unit':'Reported 10-year ASCVD rate','groups':groups,'population':source['population'],
                'lowLabel':'ApoB below mean −1 SD','highLabel':'ApoB above mean +1 SD',
                'quote':quote,'contextQuote':text[text.index('However, apoB ranges'):start],
                'sourceUrl':source['url'],'sourceHash':source['extraction']['source_sha256'],
                'note':'Reported group rates; intervals unavailable in this passage. No fitted curve or individual risk calculation.'}
            for target in ('entity:apob','entity:ldl-c','entity:non-hdl-c'):
                reports[target]['relationship']=graphic
    for value in reports.values():
        value.pop('hash',None);value['hash']=digest(value)
    result = {'version': VERSION, 'profiles': reports}
    result['hash'] = digest(result)
    return result

if __name__ == '__main__':
    import os
    import sys
    destination = Path(sys.argv[1])
    data = build_reports()
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':'), allow_nan=False)+'\n')
    os.replace(temporary, destination)
    print(json.dumps({'profiles': len(data['profiles']), 'released': sum(len(p['records']) for p in data['profiles'].values()),
        'distinct_estimates': len({r['id'] for p in data['profiles'].values() for r in p['records']}),
        'withheld': sum(len(p['audit']['withheld']) for p in data['profiles'].values())}))
