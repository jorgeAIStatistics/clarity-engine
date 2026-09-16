"""Question fields → explicit entities → constrained graph records → map."""
import hashlib
import json
import os
import re
import time
from .intent import parse_intent,alias_present
from . import store
from evidence.matcher import tokens,match,research_input_error

ANCHOR_TYPES=('biomarker','compound','test','gene','protein','variant','metabolite','assay')

def plain(text):
    # Lower-case ordinary capitalized words from titles; acronyms such as IL-18, ALS or HbA1c keep their case.
    return re.sub(r'\b[A-Z][a-z]+\b',lambda m:m.group().lower(),text)

def restate(intent,nodes):
    """Panel A sentence built only from parsed fields; unknown fields are named as unspecified."""
    names=[n['name'] for n in nodes if n['type']!='precision_context']
    outcomes=[plain(o) for o in intent.outcomes]
    # A setting already inside an outcome phrase (radiotherapy-related pain) is not repeated.
    settings=[plain(s) for s in intent.setting_exposure if not any(s.casefold() in o.casefold() for o in intent.outcomes)]
    core=' × '.join([*names,' / '.join(outcomes)] if outcomes else names) or 'No named entity recognized'
    return core+(' (setting: '+', '.join(settings)+')' if settings else '')+('' if outcomes else ' · outcome not specified')+'. '+('Population: '+intent.population if intent.population else 'Population not specified')+'.'

def graph_records(nodes):
    ids=[n['id'] for n in nodes]
    with store.session() as s:
        records=s.run('MATCH (e:Entity)<-[:MENTIONS_ENTITY]-(s:Study)-[:HAS_MATCHER_RECORD]->(r:MatcherRecord) WHERE e.id IN $ids RETURN r.payload_json AS payload,collect(DISTINCT e.id) AS entities LIMIT 1500',ids=ids).data()
        temporary=[n for n in nodes if n.get('ephemeral')]
        if temporary:
            candidates=s.run('MATCH (r:MatcherRecord) WHERE any(term IN $terms WHERE toLower(r.source_text) CONTAINS toLower(term)) RETURN r.payload_json AS payload LIMIT 300',terms=[a for n in temporary for a in n['aliases']]).data()
            by_payload={r['payload']:r for r in records}
            for candidate in candidates:
                data=json.loads(candidate['payload'])
                matches=[n['id'] for n in temporary if any(alias_present(a,data.get('_text','')) for a in n['aliases'])]
                if not matches:continue
                if candidate['payload'] in by_payload:by_payload[candidate['payload']]['entities'].extend(matches)
                else:records.append(dict(payload=candidate['payload'],entities=matches))
    result=[]
    for row in records:
        doc=json.loads(row['payload']);doc['entity_ids']=row['entities'];doc['_tokens']=tokens(doc.get('title','')+' '+doc.get('_text',''))
        for finding in doc.get('findings',[]):
            # A typed finding keeps the entities named in its own marker span; legacy findings follow the record.
            finding['entity_ids']=[i for i in finding.get('entity_ids',[]) if i in row['entities']] if finding.get('finding_id') else row['entities']
        result.append(doc)
    return result

def constrained(text,intent,nodes,records):
    anchors=[n for n in nodes if n['type'] in ANCHOR_TYPES]
    conditions=[n for n in nodes if n['type']=='condition']
    def mentioned(n,source):return any(alias_present(a,source) for a in n['aliases'])
    keep=[]
    for record in records:
        source=record.get('title','')+' '+record.get('_text','')
        if anchors and not any(mentioned(n,source) for n in anchors):continue
        if conditions and not all(mentioned(n,source) for n in conditions):continue
        # Outcomes and treatment contexts are retrieval constraints, not graph neighbors.
        if intent.setting_exposure and not any(alias_present(a,source) for a in intent.setting_exposure):continue
        context_words=set().union(*(tokens(x) for x in intent.setting_exposure))
        entity_words=set().union(*(tokens(n['name']) for n in nodes))
        outcome_groups=[tokens(x)-context_words-entity_words-{'related','management','personalized','potential','trial'} for x in intent.outcomes]
        outcome_groups=[g for g in outcome_groups if g]
        if outcome_groups and not any(g <= tokens(source) for g in outcome_groups):continue
        keep.append(record)
    entities=[]
    for n in nodes:
        spans=[e.question_span for e in intent.entities if store.resolve_alias(e,[n])]
        aliases=list(dict.fromkeys(n['aliases']+spans))
        # Curated identity travels with the entity so the briefing can speak the profile's language.
        from .cypher import IDENTITY_FIELDS
        entities.append(dict(id=n['id'],name=n['name'],entity_type=n['type'],kind=n.get('kind'),path=None,
            identity={k:n[k] for k in IDENTITY_FIELDS if n.get(k)},
            aliases=aliases,outcomes=intent.outcomes,_tokens=tokens(' '.join(aliases)),_text=' '.join(aliases),
            related_ids=[],study_count=sum(n['id'] in r['entity_ids'] for r in keep),review_status='automated',maturity='Graph coverage',ephemeral=n.get('ephemeral',False)))
    result=match(text,(entities,keep),limit=16,study_limit=48)
    # Every parsed entity remains a row, including GAP rows and temporary concepts.
    visible={e['id']:e for e in result['entities']}
    result['entities']=[visible.get(e['id'],{k:v for k,v in e.items() if not k.startswith('_')}) for e in entities]
    for e in result['entities']:e['matched_aliases']=e['aliases']
    from evidence.matcher import layer_coverage
    result['layer_coverage']=layer_coverage([e['id'] for e in entities],keep,examples=48)
    result['layer_coverage']['basis']='Neo4j records constrained to the parsed entities, outcome and setting for this question. GAP means no matching indexed records, not no literature.'
    restatement=restate(intent,nodes)
    focusmap={'clinical_utility':'utility','guideline':'guidelines','prediction':'association','enrichment':'incremental'}
    result['copilot']['question'].update(dict(
        restatement=restatement,population=[intent.population] if intent.population else [],outcomes=intent.outcomes,
        context=intent.setting_exposure,primary_concepts=[dict(id=n['id'],name=n['name'],path=None) for n in nodes],secondary_concepts=[],
        focus=[dict(id=focusmap.get(i,i),label=i.replace('_',' ')) for i in intent.intents],
        note='Claude parsed the question. Exact source-linked graph records determine coverage; no clinical agreement is inferred.'))
    result['intent']=intent.model_dump()
    result['method']='Claude structured intent; question-span alias resolution; Neo4j entity/outcome/setting constraints.'
    result['query_stored']=False
    return result

def attach_graph(result,qid):
    """Layer rollups and cell findings from the question's MENTIONS subgraph, never from graph neighbours."""
    coverage,found=store.question_payload(qid)
    cells=result['layer_coverage']['entities']
    for row in coverage:
        cell=cells.get(row['entity_id'],{}).get('cells',{}).get(row['layer'])
        if cell is not None:
            cell.update(n_findings=row['n_findings'],graph_direction=row['direction'],graph_review_state=row['review_state'],sentences=json.loads(row['sentences']) if row['sentences'] else [])
    result['graph_findings']=[dict(r['finding'],entity_id=r['entity_id'],layer=r['layer'],quote=r['quote'],study_id=r['study_id'],pmid=r['pmid'],title=r['title']) for r in found]
    result['question_id']=qid
    result['question_storage']=dict(parsed_fields_days=7,raw_text=os.getenv('CLARITY_STORE_QUESTION_TEXT')=='1')
    return result

def run(text):
    if research_input_error(text):raise ValueError(research_input_error(text))
    try:
        # Check configuration before reserving budget so an unconfigured host records no calls.
        if not os.environ.get('ANTHROPIC_API_KEY'):raise RuntimeError('intent_provider_not_configured')
        from .budget import reserve
        reserve()
        intent=parse_intent(text)
        nodes,qid=store.resolve(intent,text,store_question_text=os.getenv('CLARITY_STORE_QUESTION_TEXT')=='1')
        result=attach_graph(constrained(text,intent,nodes,graph_records(nodes)),qid)
        result['parse']=dict(mode='claude',graph='neo4j')
        return result
    except Exception as error:
        reason=str(error) if isinstance(error,RuntimeError) and re.fullmatch(r'[a-z0-9_]+',str(error)) else type(error).__name__
        return run_local(text,reason)

def local_nodes(intent,text):
    from pathlib import Path
    from .intent import resolve_alias
    registry=json.loads(Path(__file__).with_name('registry.json').read_text())
    nodes=[]
    for entity in intent.entities:
        node=resolve_alias(entity,registry)
        if node is None:
            identifier='temporary:'+hashlib.sha256((entity.type+'|'+entity.question_span.casefold()).encode()).hexdigest()[:24]
            node=dict(id=identifier,name=entity.question_span,aliases=[entity.question_span],type=entity.type,ephemeral=True)
        if node['id'] not in {n['id'] for n in nodes}:nodes.append(node)
    return nodes

def local_records(nodes):
    from evidence.matcher import library_index
    _,studies=library_index(int(time.time()//3600))
    records=[]
    for study in studies:
        source=(study.get('title') or '')+' '+(study.get('_text') or '')
        ids=[n['id'] for n in nodes if any(alias_present(a,source) for a in n['aliases'])]
        if nodes and not ids:continue
        # Only quote-backed reported values in the retained text are plot eligible.
        findings=[{**f,'entity_ids':ids,'plot_eligible':bool(f.get('quote') and f['quote'] in (study.get('_text') or '') and (f.get('effect') or {}).get('origin','reported')=='reported')} for f in study.get('findings',[])]
        records.append({**study,'entity_ids':ids,'findings':findings})
    return records

def run_local(text,reason):
    from pathlib import Path
    from .intent import rule_intent
    registry=json.loads(Path(__file__).with_name('registry.json').read_text())
    intent=rule_intent(text,registry)
    nodes=local_nodes(intent,text)
    result=constrained(text,intent,nodes,local_records(nodes))
    result['layer_coverage']['basis']='Retained library records that name the entities, outcome and setting written in your question. GAP means no matching indexed records, not no literature.'
    result['copilot']['question']['note']='The automatic question parser was unavailable, so this reading uses only names and phrases written in your text. Check the entities and outcome, and edit them if needed.'
    result['method']='Rule-based question fields from literal spans; registry alias resolution; retained library records constrained to those entities, outcome and setting.'
    result['parse']=dict(mode='rules',graph='retained_library',reason=reason)
    return result
