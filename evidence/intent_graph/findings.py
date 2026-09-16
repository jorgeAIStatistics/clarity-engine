"""Publish source-bound biomarker findings to the graph the website reads.

A Finding is linked to an Entity only when an alias of that entity is written in the
finding's own marker span; the most specific entity wins (a variant over its gene). Findings
connect to layers, passages and outcomes; each entity×layer gets an automated meaning
sentence or an honest gap sentence. Findings are listed with passages and are not plotted
until the visual release checks accept a comparable measure.
"""
import hashlib
import json
import re
from collections import defaultdict
from .intent import alias_present, norm
from .cypher import LAYERS, KEEP_REVIEWED

LAYER_BY_DESIGN = {'rct_parallel': 'interventional', 'rct_crossover': 'interventional', 'rct_cluster': 'interventional', 'meta_analysis': 'synthesis', 'systematic_review': 'synthesis', 'observational': 'observational', 'diagnostic_accuracy': 'observational'}
DESIGN_LABEL = {'rct_parallel': 'Randomized controlled trial', 'rct_crossover': 'Randomized crossover trial', 'rct_cluster': 'Cluster randomized trial', 'meta_analysis': 'Meta-analysis', 'systematic_review': 'Systematic review', 'observational': 'Observational study', 'diagnostic_accuracy': 'Diagnostic accuracy study', 'other': 'Other design', 'not_determined': 'Design not determined'}
MEASURE_LABEL = {'hazard_ratio': 'hazard ratio', 'odds_ratio': 'odds ratio', 'risk_ratio': 'risk ratio', 'rate_ratio': 'rate ratio', 'mean_difference': 'mean difference', 'standardized_mean_difference': 'standardized mean difference', 'risk_difference': 'risk difference', 'correlation': 'correlation', 'auc': 'AUC', 'c_index': 'C-index', 'delta_c_index': 'C-index change', 'sensitivity': 'sensitivity', 'specificity': 'specificity', 'ppv': 'positive predictive value', 'npv': 'negative predictive value', 'accuracy': 'accuracy', 'likelihood_ratio_positive': 'positive likelihood ratio', 'likelihood_ratio_negative': 'negative likelihood ratio', 'cutoff': 'cut-off', 'median': 'median', 'mean': 'mean', 'proportion': 'proportion', 'percent': 'percent', 'p_value': 'p value', 'recommendation': 'recommendation', 'other': 'reported measure'}
LAYER_WORDS = {'mechanism': 'mechanism or cell', 'preclinical': 'animal or laboratory', 'observational': 'human observational', 'interventional': 'human trial', 'guidelines': 'guideline'}
KIND_WORDS = {'effect': 'effect', 'association': 'association', 'discrimination': 'discrimination', 'classification': 'classification', 'prognosis': 'prognostic', 'utility': 'clinical-utility', 'guideline': 'guideline'}
RATIO = {'hazard_ratio', 'odds_ratio', 'risk_ratio', 'rate_ratio'}
DIFFERENCE = {'mean_difference', 'standardized_mean_difference', 'risk_difference', 'delta_c_index'}
ANIMAL = re.compile(r'\b(?:mice|mouse|murine|rats?|rodents?|xenografts?|animal models?)\b', re.I)
CELL = re.compile(r'\b(?:cell lines?|in vitro|cultured cells|organoids?)\b', re.I)


def finding_kind(f):
    return f.get('kind') or f.get('observation_type')


def finding_layer(design, finding):
    """Layer from a written design; otherwise from what the finding itself reports."""
    if design in LAYER_BY_DESIGN:
        return LAYER_BY_DESIGN[design]
    if finding_kind(finding) == 'guideline':
        return 'guidelines'
    context = ' '.join(filter(None, [finding.get('population'), finding['passage']['text']]))
    if CELL.search(context):
        return 'mechanism'
    if ANIMAL.search(context):
        return 'preclinical'
    return 'observational'


def observation_layer(design, findings):
    layers = [finding_layer(design, f) for f in findings]
    return max(set(layers), key=layers.count) if layers else 'unclassified'


# A drug class built on a marker name (EGFR-TKI, anti-HER2 therapy) is a treatment, not the marker.
THERAPY_AFTER = re.compile(r'[-\s]*(?:TKIs?\b|tyrosine[-\s]kinase[-\s]inhibitors?|inhibitors?\b|inhibition\b|antagonists?\b|blockers?\b|blockade\b|targeted\b|directed\b|antibod(?:y|ies)\b|therap(?:y|ies)\b)', re.I)
PANEL = re.compile(r',|\+|\band\b|\bplus\b', re.I)
ANTI_BEFORE = re.compile(r'\banti[-\s]?$', re.I)


def names_marker(alias, marker):
    spans = list(re.finditer(re.escape(alias), marker, re.I))
    if not spans:
        return True  # matched only after normalization (e.g. IL18 for IL-18); nothing to qualify
    return any(not THERAPY_AFTER.match(marker[m.end():]) and not ANTI_BEFORE.search(marker[:m.start()]) for m in spans)


def linked_entities(finding, nodes):
    """Entities named in the finding's own marker span. The longest alias wins, so 'EGFR mutation'
    links the variant rather than the gene, and a sentence that merely mentions EGFR-TKI links nothing."""
    marker = finding.get('marker') or ''
    # A panel (synaptophysin and chromogranin A, CgA + INSM1) is not attributed to any single marker.
    if PANEL.search(marker):
        return []
    hits = []
    for n in nodes:
        matched = [a for a in n['aliases'] if alias_present(a, marker) and names_marker(a, marker)]
        if matched:
            hits.append((max(len(norm(a)) for a in matched), n))
    if not hits:
        return []
    best = max(length for length, _ in hits)
    return [n for length, n in hits if length == best]


def matcher_finding(finding, entity_ids):
    kind = finding_kind(finding)
    return {
        'finding_id': finding['id'], 'kind': kind, 'observation_type': kind, 'measure': finding['measure'],
        'outcome': finding.get('target') or finding.get('statement') or finding['marker'],
        'effect': {'measure': MEASURE_LABEL[finding['measure']], 'estimate': finding['value'], 'lower': finding['lower'], 'upper': finding['upper'], 'confidence_level': finding['level'], 'units': finding['unit'], 'origin': 'reported'},
        'threshold': finding['threshold'], 'threshold_unit': finding['threshold_unit'], 'n': finding['n'],
        'p_value': finding['p_value'], 'p_operator': finding['p_operator'], 'statement': finding['statement'],
        'population': finding['population'], 'setting': finding.get('setting'), 'assay': finding.get('assay'),
        'comparator': finding['comparator'], 'marker': finding['marker'],
        'quote': finding['passage']['text'],
        'source_span': {'start': finding['passage']['start'], 'end': finding['passage']['end'], 'text': finding['passage']['text'], 'basis': 'source-bound biomarker finding'},
        'plot_eligible': False, 'review_status': 'automated_appraisal', 'entity_ids': entity_ids,
    }


def matcher_document(record, nodes=()):
    source, findings = record['source'], record['findings']
    design = record['design']['study_design']
    pmid = source.get('pmid')
    return {
        'id': record['study_id'], 'pmid': pmid, 'title': source['text'].split('\n')[0], 'url': source.get('source_url') or (f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/' if pmid else None),
        'year': record.get('year'), 'design': DESIGN_LABEL.get(design, 'Design not determined'), 'population': next((f['population'] for f in findings if f.get('population')), None),
        'n': None, 'layer': observation_layer(design, findings), 'layer_basis': 'study_design' if design in LAYER_BY_DESIGN else 'finding_kind',
        'findings': [matcher_finding(f, [n['id'] for n in linked_entities(f, nodes)]) for f in findings], 'exposure': None, 'comparator': None, 'cohort_id': None, 'entity_ids': [],
        '_passages': [f['passage']['text'] for f in findings], '_text': source['text'], 'agreement': 'not_assessed', 'review_status': 'automated',
    }


def apply_observations(doc, record, nodes=()):
    """Replace this record's findings in an existing matcher document; other findings are kept."""
    fresh = matcher_document(record, nodes)
    doc['findings'] = [f for f in doc.get('findings', []) if not f.get('finding_id')] + fresh['findings']
    if doc.get('layer') not in LAYERS and fresh['layer'] in LAYERS:
        doc['layer'], doc['layer_basis'] = fresh['layer'], fresh['layer_basis']
    if not doc.get('design') or doc['design'] in ('', 'Journal Article'):
        doc['design'] = fresh['design']
    return doc


def side(f):
    null = 1 if f.get('measure') in RATIO else 0 if f.get('measure') in DIFFERENCE else None
    low, high = f.get('lower'), f.get('upper')
    if null is None or low is None or high is None:
        return None
    return 'below' if high < null else 'above' if low > null else 'includes'


def layer_direction(findings):
    sides = {s for s in (side(f) for f in findings) if s}
    if not sides:
        return None
    if {'below', 'above'} <= sides:
        return 'conflicting'
    return sides.pop() if len(sides) == 1 else 'mixed'


def amount(value, unit=None):
    """A number as a reader expects it: thousands grouped, and a unit spaced unless it is a percent sign."""
    text = f'{value:,.10g}' if abs(value) >= 10000 else f'{value:g}'
    unit = (unit or '').strip()
    return text + (unit if unit in ('%', '‰') else f' {unit}' if unit else '')


def value_words(f):
    label = MEASURE_LABEL.get(f.get('measure'), 'reported measure')
    if f.get('measure') == 'recommendation':
        return 'a recommendation'
    if f.get('estimate') is None and f.get('p_value') is not None:
        return f'a p value of {f["p_value"]:g}'
    if f.get('estimate') is None:
        return label
    text = f'{label} {amount(f["estimate"], f.get("unit"))}'
    if f.get('lower') is not None:
        text += f' ({amount(f["lower"])} to {amount(f["upper"])})'
    if f.get('cutoff') is not None:
        text += f' at a cut-off of {amount(f["cutoff"], f.get("cutoff_unit"))}'
    return text


def synthesize(name, layer, findings):
    """One automated sentence per outcome within an entity×layer, or a gap sentence."""
    if not findings:
        return [f'No indexed {LAYER_WORDS[layer]} findings for {name} yet. This is a gap in Clarity\'s library, not evidence that none exist.']
    by_outcome = defaultdict(list)
    for f in findings:
        by_outcome[f.get('target') or f.get('statement') or 'the reported outcome'].append(f)
    sentences = []
    for outcome, group in by_outcome.items():
        kinds = sorted({KIND_WORDS.get(f.get('kind'), 'reported') for f in group})
        count = len(group)
        values = '; '.join(value_words(f) for f in group[:3]) + ('; …' if count > 3 else '')
        sentences.append(f'Automated reading: {count} {"/".join(kinds)} {"finding" if count == 1 else "findings"} for {name} and {outcome} ({values}). Not expert-reviewed.')
    return sentences


def statements(record, nodes):
    """Cypher and parameters for one finding record. Pure, so linking rules are testable."""
    source = record['source']
    design = record['design']['study_design']
    ids = [f['id'] for f in record['findings']]
    out = [
        ('MERGE (s:Study {id:$study}) ON CREATE SET s.created_at=$at SET s.pmid=$pmid, s.doi=$doi, s.year=$year, s.title=$title, s.design=$design',
         dict(study=record['study_id'], at=record['extracted_at'], pmid=source.get('pmid'), doi=source.get('doi'), year=record.get('year'), title=source['text'].split('\n')[0], design=DESIGN_LABEL.get(design, 'Design not determined'))),
        # Re-publishing replaces automated findings and links for this study; reviewed findings are untouched.
        ("MATCH (s:Study {id:$study})-[:REPORTS|REPORTS_FINDING]->(f:Finding) WHERE coalesce(f.review_state,'automated')<>'reviewed' AND NOT f.id IN $ids DETACH DELETE f", dict(study=record['study_id'], ids=ids)),
        ("MATCH (s:Study {id:$study})-[old:REPORTS_FINDING]->(:Finding) DELETE old", dict(study=record['study_id'])),
        ("MATCH (s:Study {id:$study})-[:REPORTS]->(f:Finding)-[r:ABOUT|FOR_OUTCOME]->() WHERE coalesce(f.review_state,'automated')<>'reviewed' DELETE r", dict(study=record['study_id'])),
        ("MATCH (s:Study {id:$study})-[:REPORTS]->(f:Finding)<-[r:SUPPORTED_BY]-(:LayerAssessment) WHERE coalesce(f.review_state,'automated')<>'reviewed' DELETE r", dict(study=record['study_id'])),
    ]
    linked = defaultdict(list)
    for f in record['findings']:
        passage_id = 'passage:' + hashlib.sha256(f"{source['sha256']}|{f['passage']['start']}|{f['passage']['end']}".encode()).hexdigest()[:24]
        out.append((
            'MATCH (s:Study {id:$study}) MERGE (f:Finding {id:$id}) SET f.kind=$kind, f.observation_type=$kind, f.measure=$measure, f.estimate=$estimate, f.estimate_raw=$estimate_raw, '
            'f.lower=$lower, f.upper=$upper, f.level=$level, f.unit=$unit, f.cutoff=$cutoff, f.cutoff_unit=$cutoff_unit, f.assay=$assay, f.population=$population, f.setting=$setting, '
            'f.target=$target, f.comparator=$comparator, f.statement=$statement, f.marker=$marker, f.n=$n, f.p_value=$p_value, f.p_operator=$p_operator, f.source_id=$source, '
            'f.source_sha256=$hash, f.extraction_version=$version, f.extracted_at=$at, f.review_state=' + KEEP_REVIEWED.format(v='f') + ' MERGE (s)-[:REPORTS]->(f) '
            'MERGE (p:SourcePassage {id:$passage_id}) SET p.quote=$quote, p.locator=$locator MERGE (f)-[:EVIDENCED_BY]->(p)',
            dict(study=record['study_id'], id=f['id'], kind=finding_kind(f), measure=f['measure'], estimate=f['value'], estimate_raw=f['value_raw'], lower=f['lower'], upper=f['upper'],
                 level=f['level'], unit=f['unit'], cutoff=f['threshold'], cutoff_unit=f['threshold_unit'], assay=f.get('assay'), population=f['population'], setting=f.get('setting'),
                 target=f['target'], comparator=f['comparator'], statement=f['statement'], marker=f['marker'], n=f['n'], p_value=f['p_value'], p_operator=f['p_operator'],
                 source=source['id'], hash=source['sha256'], version=record['version'], at=record['extracted_at'], review='automated', passage_id=passage_id, quote=f['passage']['text'],
                 locator=json.dumps({'source_id': source['id'], 'start': f['passage']['start'], 'end': f['passage']['end'], 'unit': 'unicode_code_point'})),
        ))
        if f.get('target'):
            out.append(('MATCH (f:Finding {id:$id}) MERGE (o:Outcome {id:$outcome}) SET o.name=coalesce(o.name,$name) MERGE (f)-[:FOR_OUTCOME]->(o)', dict(id=f['id'], outcome='outcome:' + norm(f['target']), name=f['target'])))
        layer = finding_layer(design, f)
        for n in linked_entities(f, nodes):
            linked[n['id']].append(f)
            out.append(('MATCH (f:Finding {id:$finding}), (e:Entity {id:$entity}), (s:Study {id:$study}) MERGE (f)-[:ABOUT]->(e) MERGE (s)-[r:MENTIONS_ENTITY]->(e) SET r.review_state="automated", r.method="exact_alias_in_finding"',
                        dict(finding=f['id'], entity=n['id'], study=record['study_id'])))
            if layer in LAYERS:
                out.append(('MATCH (e:Entity {id:$entity})-[:HAS_LAYER]->(l:LayerAssessment {layer:$layer}), (f:Finding {id:$finding}) MERGE (l)-[:SUPPORTED_BY]->(f)', dict(entity=n['id'], layer=layer, finding=f['id'])))
    return out, sorted(linked)


def refresh_layers(session, entity_id):
    """Roll up n_findings, direction and meaning sentences for all five layers of one entity."""
    rows = session.run(
        'MATCH (e:Entity {id:$id})-[:HAS_LAYER]->(l:LayerAssessment) OPTIONAL MATCH (l)-[:SUPPORTED_BY]->(f:Finding) '
        'RETURN e.name AS name, l.id AS layer_id, l.layer AS layer, collect(f{.kind, .measure, .estimate, .lower, .upper, .unit, .cutoff, .cutoff_unit, .target, .statement, .p_value}) AS found',
        id=entity_id).data()
    for row in rows:
        found = [f for f in row['found'] if f.get('kind')]
        session.run(
            'MATCH (l:LayerAssessment {id:$id}) SET l.n_findings=$n, l.direction=$direction, l.sentences=$sentences, '
            "l.status=CASE WHEN $n>0 THEN 'INDEXED' ELSE coalesce(l.status,'GAP') END, l.review_state=" + KEEP_REVIEWED.format(v='l'),
            id=row['layer_id'], n=len(found), direction=layer_direction(found), sentences=json.dumps(synthesize(row['name'], row['layer'], found)), review='automated').consume()


def publish(record, nodes, session):
    """Write findings, links, layer rollups and the matcher record the website retrieves."""
    # Entities this study's findings used to name also get fresh rollups when a link is removed.
    previous = session.run('MATCH (:Study {id:$study})-[:REPORTS]->(:Finding)-[:ABOUT]->(e:Entity) RETURN collect(DISTINCT e.id) AS ids', study=record['study_id']).single()['ids']
    cypher, linked = statements(record, nodes)
    for query, parameters in cypher:
        session.run(query, **parameters).consume()
    for entity_id in sorted(set(linked) | set(previous)):
        refresh_layers(session, entity_id)
    matcher_record(record, nodes, session)
    return linked


def matcher_record(record, nodes, session):
    """Upsert the MatcherRecord the website retrieves, merging these findings into any existing source record."""
    existing = session.run('MATCH (r:MatcherRecord {id:$id}) RETURN r.payload_json AS payload', id='matcher:' + record['study_id']).single()
    doc = apply_observations(json.loads(existing['payload']), record, nodes) if existing and existing['payload'] else matcher_document(record, nodes)
    payload = json.dumps({k: v for k, v in doc.items() if k != '_tokens'}, ensure_ascii=False)
    session.run('MERGE (s:Study {id:$study}) MERGE (r:MatcherRecord {id:$record}) SET r.payload_json=$payload, r.source_hash=$hash, r.source_text=$text, r.review_state="automated" MERGE (s)-[:HAS_MATCHER_RECORD]->(r)',
                study=record['study_id'], record='matcher:' + record['study_id'], payload=payload, text=doc['_text'], hash=hashlib.sha256(doc['_text'].encode()).hexdigest()).consume()


def dead_letter(session, entity_id, pmid, study_id, code, dead_letters, excluded, at):
    """A typed record of why an extraction produced no findings, attached to the marker it targeted."""
    identifier = 'deadletter:' + hashlib.sha256(f'{entity_id}|{study_id}'.encode()).hexdigest()[:24]
    session.run('MATCH (e:Entity {id:$entity}) MERGE (d:DeadLetter {id:$id}) SET d.pmid=$pmid, d.study_id=$study, d.code=$code, d.reasons=$reasons, d.excluded=$excluded, d.at=$at, d.review_state="automated" MERGE (d)-[:ABOUT]->(e)',
                entity=entity_id, id=identifier, pmid=pmid, study=study_id, code=code, reasons=json.dumps(dead_letters), excluded=json.dumps(excluded)[:4000], at=at).consume()
    return identifier


def summary(finding, nodes=()):
    return {'kind': finding_kind(finding), 'measure': finding['measure'], 'value': finding['value_raw'], 'cutoff': finding['threshold'], 'interval': [finding['lower'], finding['upper']] if finding['lower'] is not None else None,
            'marker': finding['marker'], 'target': finding['target'], 'linked': [n['id'] for n in linked_entities(finding, nodes)], 'passage': finding['passage']['text']}
