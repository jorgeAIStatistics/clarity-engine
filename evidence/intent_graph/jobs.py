"""Graph enrichment as explicit, resumable stages.

ingest → extract → validate → link → upsert → synthesize → publish

Each stage records its outcome on the job. A failed job keeps the stage it failed at, so a retry
resumes there instead of re-spending extraction calls on work that already succeeded. The gap
ranker decides what to enqueue: entities researchers ask about whose utility layers are empty,
and question spans the registry could not resolve (matcher misses).
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

STAGES = ('ingest', 'extract', 'validate', 'link', 'upsert', 'synthesize', 'publish')
UTILITY_LAYERS = ['interventional', 'guidelines']

# Questions and temporary entities expire after seven days, so "asked" means asked recently.
GAP_QUERY = """
MATCH (e:Entity) WHERE coalesce(e.ephemeral,false)=false
OPTIONAL MATCH (e)-[:HAS_LAYER]->(l:LayerAssessment)
WITH e, sum(CASE WHEN l.layer IN $utility THEN coalesce(l.n_findings,0) ELSE 0 END) AS utility_findings,
     sum(coalesce(l.n_findings,0)) AS findings
OPTIONAL MATCH (q:Question)-[:MENTIONS]->(e)
WITH e, utility_findings, findings, count(DISTINCT q) AS asked
OPTIONAL MATCH (d:DeadLetter)-[:ABOUT]->(e)
OPTIONAL MATCH (e)<-[:MENTIONS_ENTITY]-(st:Study)
RETURN e.id AS id, e.name AS name, coalesce(e.kind, e.type) AS kind, utility_findings, findings, asked, count(DISTINCT d) AS dead_letters, count(DISTINCT st) AS studies
"""
MISSES_QUERY = """
MATCH (q:Question)-[:MENTIONS]->(t:Entity {ephemeral:true})
RETURN t.name AS name, t.type AS type, count(DISTINCT q) AS asked
ORDER BY asked DESC, name LIMIT $limit
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _plural(n, word):
    return f"{n} recent {word if n == 1 else word + 's'}"


def rank_gaps(rows, misses=(), limit=20):
    """Transparent priority, not a model: 2 per recent question, +1.5 when the interventional and
    guideline layers are empty, +1 when no layer has a typed finding, and −0.5 per rejected extraction
    beyond two so a marker that keeps failing yields to others. Matcher misses need aliases first."""
    ranked = []
    for r in rows:
        # Conditions and drugs are context for a finding, never the marker a finding is about.
        if r['kind'] in ('Condition', 'Compound'):
            continue
        score, reasons = 2.0 * r['asked'], []
        # Precision pairs and tests are the thin domains; an empty one is worth more than another empty marker.
        if r['kind'] in ('PrecisionContext', 'Test', 'Assay') and not r['findings']:
            score += 2.0
            reasons.append('thin domain: ' + ('precision pair' if r['kind'] == 'PrecisionContext' else 'test'))
        elif r['kind'] == 'Biomarker' and not r['findings'] and r.get('studies'):
            score += 0.75
            reasons.append(f"{r['studies']} linked publications but no typed finding")
        if r['asked']:
            reasons.append('asked in ' + _plural(r['asked'], 'question'))
        if not r['utility_findings']:
            score += 1.5
            reasons.append('no interventional or guideline findings')
        if not r['findings']:
            score += 1.0
            reasons.append('no typed findings in any layer')
        if r['dead_letters'] > 2:
            score -= 0.5 * (r['dead_letters'] - 2)
            reasons.append(f"{r['dead_letters']} extraction attempts rejected")
        ranked.append(dict(kind='entity', id=r['id'], name=r['name'], entity_kind=r['kind'], score=round(score, 2), reasons=reasons))
    for m in misses:
        ranked.append(dict(kind='matcher_miss', id=None, name=m['name'], entity_kind=m['type'], score=round(2.0 * m['asked'] + 1.0, 2),
                           reasons=['not in the registry; asked in ' + _plural(m['asked'], 'question'), 'add the entity and its aliases before enrichment']))
    return sorted(ranked, key=lambda x: (-x['score'], x['name'].casefold()))[:limit]


def gaps(session, limit=20):
    rows = session.run(GAP_QUERY, utility=UTILITY_LAYERS).data()
    misses = session.run(MISSES_QUERY, limit=limit).data()
    return rank_gaps(rows, misses, limit)


def enqueue(state, entity_id, reason, priority=0.0):
    job_id = 'graph-job:' + entity_id
    job = state.get('graph_job', job_id)
    if job and job['status'] in ('queued', 'running', 'failed'):
        # A failed job is re-queued at the stage it failed, keeping the work already done.
        job.update(status='queued', priority=max(job['priority'], priority), reasons=sorted(set(job['reasons']) | {reason}))
    else:
        job = dict(id=job_id, entity_id=entity_id, reasons=[reason], priority=priority, stage=STAGES[0], status='queued', history=[], context={}, created_at=_now())
    state.put('graph_job', job_id, job)
    return job


def pending(state, limit=5):
    jobs = [j for j in state.all('graph_job') if j['status'] == 'queued']
    return sorted(jobs, key=lambda j: (-j['priority'], j['created_at']))[:limit]


def run_job(state, job, handlers):
    """Advance one job through its remaining stages and stop at the first failure."""
    job['status'] = 'running'
    for stage in STAGES[STAGES.index(job['stage']):]:
        job['stage'] = stage
        try:
            detail = handlers[stage](job['context'], job) or {}
        except Exception as error:
            code = str(error) if re.fullmatch(r'[a-z0-9_]{3,80}', str(error)) else type(error).__name__
            job.update(status='failed', error=code)
            job['history'].append(dict(stage=stage, ok=False, code=code, at=_now()))
            state.put('graph_job', job['id'], job)
            return job
        job['history'].append(dict(stage=stage, ok=True, at=_now(), **{k: v for k, v in detail.items() if isinstance(v, (bool, int, float, str))}))
        state.put('graph_job', job['id'], job)
    job.update(status='done', error=None, finished_at=_now())
    state.put('graph_job', job['id'], job)
    return job


def default_handlers(state, registry, attempts=2, search=False):
    """Stages composed from the existing extractor, decoder and graph writers."""
    from evidence_pipeline.common import now
    from evidence_pipeline.schemas.pico import SourceDocument
    from evidence_pipeline.extraction.observations import ObservationProvider, ObservationExtractor
    from . import store, findings
    from .enrich import search_sources, tried_sources
    by_id = {n['id']: n for n in registry}

    def ingest(ctx, job):
        node = by_id[job['entity_id']]
        sources = (search_sources(node) if search else tried_sources(state, node)) or search_sources(node)
        ctx['sources'] = [dict(identity=i, source=s.model_dump(mode='json'), year=m.get('pubYear')) for i, s, m in sources[:max(1, attempts)]]
        if not ctx['sources']:
            raise RuntimeError('no_sources_found')
        return dict(sources=len(ctx['sources']))

    def extract(ctx, job):
        provider = ObservationProvider('anthropic', os.getenv('CLARITY_ENRICH_MODEL', 'claude-sonnet-5'), os.environ['ANTHROPIC_API_KEY'], max_output_tokens=14000)
        extractor = ObservationExtractor(provider, state, daily_calls=120)
        ctx['records'], ctx['failures'] = [], []
        try:
            for item in ctx['sources']:
                source = SourceDocument.model_validate(item['source'])
                try:
                    key, record = extractor.extract(source, run_id='graph-job-v1')
                    record = dict(record, study_id=item['identity'], year=item['year'], target_ids=[job['entity_id']])
                    state.put('observation_extraction', key, record)
                    ctx['records'].append(record)
                except Exception as error:
                    ctx['failures'].append(dict(pmid=source.pmid, study_id=item['identity'], code=str(error)[:80], dead_letters=getattr(provider, 'dead_letters', {}) or {}, excluded=getattr(provider, 'decode_audit', [])[:50]))
        finally:
            provider.close()
        return dict(records=len(ctx['records']), failures=len(ctx['failures']))

    def validate(ctx, job):
        # The decoder already rejected unsupported findings; a record with none left is a dead-letter.
        ctx['records'] = [r for r in ctx['records'] if r['findings']]
        if not ctx['records'] and not ctx['failures']:
            raise RuntimeError('no_supported_observations')
        return dict(records=len(ctx['records']), dead_letters=len(ctx['failures']))

    def link(ctx, job):
        ctx['linked'] = sorted({i for r in ctx['records'] for i in findings.statements(r, registry)[1]})
        return dict(linked=len(ctx['linked']), target_linked=job['entity_id'] in ctx['linked'])

    def upsert(ctx, job):
        with store.session() as s:
            for r in ctx['records']:
                for query, parameters in findings.statements(r, registry)[0]:
                    s.run(query, **parameters).consume()
            for f in ctx['failures']:
                findings.dead_letter(s, job['entity_id'], f['pmid'], f['study_id'], f['code'], f['dead_letters'], f['excluded'], now().isoformat())
        return dict(findings=sum(len(r['findings']) for r in ctx['records']), dead_letters=len(ctx['failures']))

    def synthesize(ctx, job):
        entities = sorted(set(ctx['linked']) | {job['entity_id']})
        with store.session() as s:
            for entity_id in entities:
                findings.refresh_layers(s, entity_id)
        return dict(entities=len(entities))

    def publish(ctx, job):
        with store.session() as s:
            for r in ctx['records']:
                findings.matcher_record(r, registry, s)
        return dict(matcher_records=len(ctx['records']))

    return dict(ingest=ingest, extract=extract, validate=validate, link=link, upsert=upsert, synthesize=synthesize, publish=publish)


def main(argv=None):
    import argparse
    from evidence_pipeline.config import Settings
    from evidence_pipeline.state import State
    from . import store
    parser = argparse.ArgumentParser(description='Graph enrichment job queue and gap ranker')
    parser.add_argument('--gaps', type=int, metavar='N', help='Print the top N gaps')
    parser.add_argument('--enqueue', type=int, metavar='N', help='Enqueue the top N registry gaps')
    parser.add_argument('--run', type=int, metavar='N', help='Run up to N queued jobs (spends extraction calls)')
    parser.add_argument('--search', action='store_true', help='Search new abstracts instead of re-reading tried ones')
    args = parser.parse_args(argv)
    registry = json.loads(Path(__file__).with_name('registry.json').read_text())
    state = State(Settings.from_env().state_path)
    try:
        if args.gaps or args.enqueue:
            with store.session() as s:
                ranked = gaps(s, limit=max(args.gaps or 0, args.enqueue or 0))
            print(json.dumps(ranked, ensure_ascii=False, indent=1))
            known = {n['id'] for n in registry}
            for gap in [g for g in ranked if g['kind'] == 'entity' and g['id'] in known][:args.enqueue or 0]:
                enqueue(state, gap['id'], '; '.join(gap['reasons']), gap['score'])
        if args.run:
            handlers = default_handlers(state, registry, search=args.search)
            for job in pending(state, args.run):
                job = run_job(state, job, handlers)
                print(json.dumps({k: job.get(k) for k in ('id', 'status', 'stage', 'error', 'history')}, ensure_ascii=False))
    finally:
        state.close()


if __name__ == '__main__':
    main()
