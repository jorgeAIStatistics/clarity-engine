"""Publish source-bound biomarker observations to the graph the map reads.

A Finding is linked to an Entity only when an exact alias of that entity is written in the
observation's own marker span or passage. Findings are listed with their passages; they are
not plotted until the visual release checks accept a comparable measure.
"""
import hashlib
import json
import re
from .intent import alias_present

LAYERS = ('mechanism', 'preclinical', 'observational', 'interventional', 'guidelines')
LAYER_BY_DESIGN = {'rct_parallel': 'interventional', 'rct_crossover': 'interventional', 'rct_cluster': 'interventional', 'meta_analysis': 'synthesis', 'systematic_review': 'synthesis', 'observational': 'observational', 'diagnostic_accuracy': 'observational'}
DESIGN_LABEL = {'rct_parallel': 'Randomized controlled trial', 'rct_crossover': 'Randomized crossover trial', 'rct_cluster': 'Cluster randomized trial', 'meta_analysis': 'Meta-analysis', 'systematic_review': 'Systematic review', 'observational': 'Observational study', 'diagnostic_accuracy': 'Diagnostic accuracy study', 'other': 'Other design', 'not_determined': 'Design not determined'}
MEASURE_LABEL = {'hazard_ratio': 'hazard ratio', 'odds_ratio': 'odds ratio', 'risk_ratio': 'risk ratio', 'correlation': 'correlation', 'mean_difference': 'mean difference', 'auc': 'AUC', 'c_index': 'C-index', 'sensitivity': 'sensitivity', 'specificity': 'specificity', 'ppv': 'positive predictive value', 'npv': 'negative predictive value', 'accuracy': 'accuracy', 'cutoff': 'cut-off', 'median': 'median', 'mean': 'mean', 'proportion': 'proportion', 'percent': 'percent', 'p_value': 'p value', 'recommendation': 'recommendation', 'other': 'reported measure'}
ANIMAL = re.compile(r'\b(?:mice|mouse|murine|rats?|rodents?|xenografts?|animal models?)\b', re.I)
CELL = re.compile(r'\b(?:cell lines?|in vitro|cultured cells|organoids?)\b', re.I)


def observation_layer(design, findings):
    """Layer from a written design; otherwise from what the observations themselves report."""
    if design in LAYER_BY_DESIGN:
        return LAYER_BY_DESIGN[design]
    if any(f['observation_type'] == 'guideline' for f in findings):
        return 'guidelines'
    context = ' '.join(filter(None, [*(f.get('population') for f in findings), *(f['passage']['text'] for f in findings)]))
    if CELL.search(context):
        return 'mechanism'
    if ANIMAL.search(context):
        return 'preclinical'
    return 'observational'


def linked_entities(finding, nodes):
    marker = finding.get('marker') or ''
    hits = [n for n in nodes if any(alias_present(a, marker) for a in n['aliases'])]
    return hits or [n for n in nodes if n['type'] == 'biomarker' and any(alias_present(a, finding['passage']['text']) for a in n['aliases'])]


def matcher_finding(finding):
    return {
        'finding_id': finding['id'], 'observation_type': finding['observation_type'],
        'outcome': finding.get('target') or finding.get('statement') or finding['marker'],
        'effect': {'measure': MEASURE_LABEL[finding['measure']], 'estimate': finding['value'], 'lower': finding['lower'], 'upper': finding['upper'], 'confidence_level': finding['level'], 'units': finding['unit'], 'origin': 'reported'},
        'threshold': finding['threshold'], 'threshold_unit': finding['threshold_unit'], 'n': finding['n'],
        'p_value': finding['p_value'], 'p_operator': finding['p_operator'], 'statement': finding['statement'],
        'population': finding['population'], 'comparator': finding['comparator'], 'marker': finding['marker'],
        'quote': finding['passage']['text'],
        'source_span': {'start': finding['passage']['start'], 'end': finding['passage']['end'], 'text': finding['passage']['text'], 'basis': 'source-bound biomarker observation'},
        'plot_eligible': False, 'review_status': 'automated_appraisal', 'entity_ids': [],
    }


def matcher_document(record):
    source, findings = record['source'], record['findings']
    design = record['design']['study_design']
    pmid = source.get('pmid')
    return {
        'id': record['study_id'], 'pmid': pmid, 'title': source['text'].split('\n')[0], 'url': source.get('source_url') or (f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else None),
        'year': record.get('year'), 'design': DESIGN_LABEL.get(design, 'Design not determined'), 'population': next((f['population'] for f in findings if f.get('population')), None),
        'n': None, 'layer': observation_layer(design, findings), 'layer_basis': 'study_design' if design in LAYER_BY_DESIGN else 'observation_type',
        'findings': [matcher_finding(f) for f in findings], 'exposure': None, 'comparator': None, 'cohort_id': None, 'entity_ids': [],
        '_passages': [f['passage']['text'] for f in findings], '_text': source['text'], 'agreement': 'not_assessed', 'review_status': 'automated',
    }


def apply_observations(doc, record):
    """Merge observation findings into an existing matcher document without dropping other findings."""
    fresh = matcher_document(record)
    ids = {f['finding_id'] for f in fresh['findings']}
    doc['findings'] = [f for f in doc.get('findings', []) if f.get('finding_id') not in ids] + fresh['findings']
    if doc.get('layer') not in LAYERS and fresh['layer'] in LAYERS:
        doc['layer'], doc['layer_basis'] = fresh['layer'], fresh['layer_basis']
    if not doc.get('design') or doc['design'] in ('', 'Journal Article'):
        doc['design'] = fresh['design']
    return doc


def statements(record, nodes):
    """Cypher and parameters for one observation record. Pure, so linking rules are testable."""
    source = record['source']
    out = [('MERGE (s:Study {id:$study}) ON CREATE SET s.created_at=$at', dict(study=record['study_id'], at=record['extracted_at']))]
    links = {}
    for f in record['findings']:
        out.append(('MATCH (s:Study {id:$study}) MERGE (f:Finding {id:$id}) SET f.observation_type=$type,f.measure=$measure,f.value=$value,f.value_raw=$value_raw,f.lower=$lower,f.upper=$upper,f.level=$level,f.unit=$unit,f.threshold=$threshold,f.threshold_unit=$threshold_unit,f.n=$n,f.p_value=$p_value,f.p_operator=$p_operator,f.target=$target,f.population=$population,f.comparator=$comparator,f.statement=$statement,f.marker=$marker,f.passage=$passage,f.passage_start=$start,f.passage_end=$end,f.source_id=$source,f.source_sha256=$hash,f.review_state="automated",f.extraction_version=$version,f.extracted_at=$at MERGE (s)-[:REPORTS_FINDING]->(f)',
                    dict(study=record['study_id'], id=f['id'], type=f['observation_type'], measure=f['measure'], value=f['value'], value_raw=f['value_raw'], lower=f['lower'], upper=f['upper'], level=f['level'], unit=f['unit'], threshold=f['threshold'], threshold_unit=f['threshold_unit'], n=f['n'], p_value=f['p_value'], p_operator=f['p_operator'], target=f['target'], population=f['population'], comparator=f['comparator'], statement=f['statement'], marker=f['marker'], passage=f['passage']['text'], start=f['passage']['start'], end=f['passage']['end'], source=source['id'], hash=source['sha256'], version=record['version'], at=record['extracted_at'])))
        for n in linked_entities(f, nodes):
            links.setdefault(n['id'], []).append(f)
            out.append(('MATCH (f:Finding {id:$finding}),(e:Entity {id:$entity}),(s:Study {id:$study}) MERGE (f)-[:ABOUT]->(e) MERGE (s)-[r:MENTIONS_ENTITY]->(e) SET r.review_state="automated",r.method="exact_alias_in_source"',
                        dict(finding=f['id'], entity=n['id'], study=record['study_id'])))
    layer = observation_layer(record['design']['study_design'], record['findings'])
    for entity, found in links.items():
        if layer in LAYERS:
            out.append(('MATCH (e:Entity {id:$entity})-[:HAS_LAYER]->(l:LayerAssessment {layer:$layer}) SET l.status="INDEXED",l.review_state="automated"', dict(entity=entity, layer=layer)))
        first = found[0]
        out.append(('MATCH (e:Entity {id:$entity}) SET e.meaning=$meaning,e.meaning_type=$type,e.meaning_source_id=$source,e.meaning_source_hash=$hash,e.last_extracted_at=$at,e.extraction_state="source_validated"',
                    dict(entity=entity, meaning=first['passage']['text'], type=first['observation_type'], source=source['id'], hash=source['sha256'], at=record['extracted_at'])))
    return out, sorted(links)


def publish(record, nodes, session):
    """Write Finding nodes, links and the matcher record the website retrieves."""
    cypher, linked = statements(record, nodes)
    for query, parameters in cypher:
        session.run(query, **parameters).consume()
    existing = session.run('MATCH (r:MatcherRecord {id:$id}) RETURN r.payload_json AS payload', id='matcher:' + record['study_id']).single()
    doc = apply_observations(json.loads(existing['payload']), record) if existing and existing['payload'] else matcher_document(record)
    payload = json.dumps({k: v for k, v in doc.items() if k != '_tokens'}, ensure_ascii=False)
    session.run('MERGE (s:Study {id:$study}) MERGE (r:MatcherRecord {id:$record}) SET r.payload_json=$payload,r.source_hash=$hash,r.source_text=$text,r.review_state="automated" MERGE (s)-[:HAS_MATCHER_RECORD]->(r)',
                study=record['study_id'], record='matcher:' + record['study_id'], payload=payload, text=doc['_text'], hash=hashlib.sha256(doc['_text'].encode()).hexdigest()).consume()
    return linked


def summary(finding):
    return {'type': finding['observation_type'], 'measure': finding['measure'], 'value': finding['value_raw'], 'threshold': finding['threshold'], 'interval': [finding['lower'], finding['upper']] if finding['lower'] is not None else None, 'passage': finding['passage']['text']}
