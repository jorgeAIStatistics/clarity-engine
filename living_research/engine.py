import json
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from evidence.service import CATALOG, assessment_framework
from .providers import PubMed, EuropePMC, ClinicalTrials, IncompleteSearch, digest, identities
from .extraction import Extractor, VERSION, source_text
from .triage import classify
from .synthesis import build_synthesis

DEFAULTS={'initial_lookback_days':30,'overlap_days':7,'interval_days':7,'max_targets':25,'max_records':300,'max_llm_calls':20,'max_llm_calls_per_day':100,'sources':['pubmed','europe_pmc','clinical_trials']}
PROVIDERS={'pubmed':PubMed,'europe_pmc':EuropePMC,'clinical_trials':ClinicalTrials}

def now_iso():return datetime.now(timezone.utc).isoformat()
def slug(value):return re.sub(r'[^a-z0-9]+','-',value.lower()).strip('-')

def discover_targets(include_compounds=True):
    targets=[]
    for entity in CATALOG['entities']:
        target={k:entity[k] for k in ('id','name','entity_type','aliases')}
        target.update({k:entity[k] for k in ('population','evidence_question','disease_context','category') if k in entity})
        target['id']='entity:'+target['id']
        if entity['entity_type']=='precision_oncology':
            ctx=entity['disease_context']
            target['term_groups']=[[ctx['therapy']],[ctx['cancer_type'],'NSCLC'] if 'lung' in ctx['cancer_type'].lower() else [ctx['cancer_type']]]
        elif entity['id'] in ('psa-screening','mammography','fit','colonoscopy','hba1c-diagnosis','cac'):
            target['term_groups']={'psa-screening':[['PSA','prostate specific antigen'],['screening']], 'mammography':[['mammography','mammogram'],['screening']], 'fit':[['fecal immunochemical test','faecal immunochemical test','FIT'],['colorectal']], 'colonoscopy':[['colonoscopy'],['screening']], 'hba1c-diagnosis':[['HbA1c','glycated hemoglobin'],['diagnosis','diagnostic']], 'cac':[['coronary artery calcium','coronary calcium score']]}[entity['id']]
        targets.append(target)
    if include_compounds:
        import cache
        for key in cache.list_cached():
            p=cache.get(key,max_age_days=100000)
            if not isinstance(p,dict) or not p.get('name') or not p.get('claims'):continue
            name=p['name'];target={'id':'compound:'+slug(name),'name':name,'entity_type':'intervention','category':p.get('category'),'aliases':[]}
            # Existing PubMed synonyms/MeSH clauses remain available to human
            # editors; explicit aliases in configuration extend the monitor query.
            targets.append(target)
    return list({target['id']:target for target in targets}.values())

def sync_targets(store,targets,config):
    overrides=config.get('targets',{})
    for target in targets:
        current=store.get('target',target['id'],{})
        override=overrides.get(target['id'],{})
        merged={**current,**target,'next_due':current.get('next_due',0),'enabled':override.get('enabled',True),'priority':override.get('priority',0),'interval_days':override.get('interval_days',config['interval_days']),**{k:v for k,v in override.items() if k in ('aliases','term_groups')}}
        scope=digest({k:merged.get(k) for k in ('name','entity_type','population','disease_context','aliases','term_groups')})
        if current.get('scope_hash')!=scope:merged['next_due']=0
        merged['scope_hash']=scope
        store.put('target',target['id'],merged)

def deduplicate(records):
    """Union overlapping PMID/PMCID/DOI aliases, including bridge records."""
    groups=[]
    for record in records:
        keys=set(identities(record))
        if not keys:raise ValueError('Publication has no stable identifier')
        matches=[group for group in groups if group['ids']&keys]
        merged={'ids':keys,'records':[record]}
        for group in matches:
            merged['ids']|=group['ids'];merged['records']+=group['records'];groups.remove(group)
        groups.append(merged)
    return groups

def flags_for(paper):
    text=' '.join([paper.get('title',''),paper.get('abstract',''),*paper.get('publication_types',[])]).lower()
    flags=[]
    if paper.get('is_preprint'):flags.append('preprint')
    if paper.get('nct_id'):flags.append('trial_registry_update')
    if any(word in text for word in ('retract','expression of concern','erratum','correction')) or paper.get('corrections'):flags.append('correction_or_retraction_review')
    if any(word in text for word in ('adverse','toxicity','safety','mortality','harm')):flags.append('safety_or_mortality_review')
    if any(word in text for word in ('randomized','randomised','meta-analysis')):flags.append('potentially_practice_relevant')
    return flags

def retrieve_window(provider,target,since,until,limit):
    try:
        return provider.search(target,since,until,limit)
    except IncompleteSearch:
        start,end=date.fromisoformat(since),date.fromisoformat(until)
        if start>=end:raise
        middle=start+(end-start)//2
        left,a=retrieve_window(provider,target,since,middle.isoformat(),limit)
        right,b=retrieve_window(provider,target,(middle+timedelta(days=1)).isoformat(),until,limit)
        return left+right,{'complete':True,'since':since,'until':until,'count':len(left)+len(right),'windows':[a,b]}


class Monitor:
    def __init__(self,store,config=None,providers=None,extractor=None):
        self.store=store;self.config={**DEFAULTS,**(config or {})}
        self.providers=providers or {name:PROVIDERS[name]() for name in self.config['sources']}
        self.extractor=extractor or Extractor(False,self.config['max_llm_calls'])
        self.extractor.reserve_call=self.reserve_call
    def reserve_call(self):
        key=datetime.now(timezone.utc).date().isoformat()
        budget=self.store.get('budget',key,{'calls':0})
        if budget['calls']>=self.config['max_llm_calls_per_day']:return False
        budget['calls']+=1
        self.store.put('budget',key,budget)
        return True
    def run(self,targets=None,only=None):
        run_id=str(uuid.uuid4())
        if not self.store.acquire(run_id):raise RuntimeError('Another research monitor is running')
        run={'id':run_id,'started_at':now_iso(),'status':'running','targets':[],'errors':[],'proposals':0}
        self.store.put('run',run_id,run)
        try:
            sync_targets(self.store,targets if targets is not None else discover_targets(),self.config)
            due=[t for t in self.store.all('target') if t['enabled'] and (t['id'] in only if only else t['next_due']<=time.time())]
            due.sort(key=lambda t:(t['next_due'],-t['priority'],t['id']))
            for target in due[:self.config['max_targets']]:
                self.store.renew(run_id)
                records=[];searches=[];failed=False
                until=date.today().isoformat()
                for source,provider in self.providers.items():
                    self.store.renew(run_id)
                    cursor_key=target['id']+'|'+source
                    cursor=self.store.get('cursor',cursor_key)
                    if cursor and cursor.get('scope_hash')!=target['scope_hash']:cursor=None
                    start=(date.fromisoformat(cursor['until'])-timedelta(days=self.config['overlap_days'])) if cursor else date.today()-timedelta(days=self.config['initial_lookback_days'])
                    try:
                        if hasattr(provider,'http'):provider.http.heartbeat=lambda:self.store.renew(run_id)
                        found,audit=retrieve_window(provider,target,start.isoformat(),until,self.config['max_records'])
                        if not audit.get('complete'):raise RuntimeError('Incomplete source retrieval')
                        records.extend(found);searches.append({'source':source,**audit})
                    except Exception as error:
                        failed=True
                        run['errors'].append({'target_id':target['id'],'source':source,'type':type(error).__name__})
                        searches.append({'source':source,'since':start.isoformat(),'until':until,'complete':False,'error':type(error).__name__})
                # Retrieval failures retain old checkpoints and old public evidence.
                for group in deduplicate(records):
                    self.store.renew(run_id)
                    proposals=self.ingest(target,group,searches)
                    run['proposals']+=proposals
                for audit in searches:
                    if audit['complete']:self.store.put('cursor',target['id']+'|'+audit['source'],{'until':until,'scope_hash':target['scope_hash']})
                target.update(last_attempt=now_iso(),last_status='partial_failure' if failed else 'checked',next_due=time.time()+(3600 if failed else target['interval_days']*86400))
                if not failed:target['last_checked']=now_iso()
                self.store.put('target',target['id'],target)
                self.store.put('search',run_id+'|'+target['id'],{'run_id':run_id,'target_id':target['id'],'executed_at':now_iso(),'searches':searches,'retrieved':len(records),'unique':len(deduplicate(records))})
                run['targets'].append(target['id'])
            # Retry unfinished LLM work independently of retrieval checkpoints.
            queue=self.store.find('proposal',status='awaiting_extraction',oldest=True) if getattr(self.extractor,'enabled',True) else []
            # Aging adds one point per day, so lower-impact work eventually rises.
            queue.sort(key=lambda p:-(p.get('triage',{}).get('impact_score',0)+max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(p['created_at'])).total_seconds()/86400)))
            for proposal in queue:
                current_target=self.store.get('target',proposal['target_id'],{})
                if not current_target.get('enabled',False):continue
                if current_target.get('scope_hash')!=proposal['scope_hash']:
                    proposal['status']='superseded';self.store.put('proposal',proposal['id'],proposal);continue
                if proposal.get('next_extraction_at',0)<=time.time() and proposal['status']=='awaiting_extraction' and (not only or proposal['target_id'] in only):
                    self.store.renew(run_id)
                    self.extract(proposal)
                    if self.extractor.calls>=self.extractor.max_calls or proposal.get('extraction',{}).get('reason') in ('Daily AI call budget reached','ANTHROPIC_API_KEY is not configured'):break
            run['status']='partial_failure' if run['errors'] else 'completed'
        except Exception as error:
            run['status']='failed';run['errors'].append({'type':type(error).__name__})
            raise
        finally:
            run.update(finished_at=now_iso(),llm_calls=self.extractor.calls)
            self.store.put('run',run_id,run);self.store.release(run_id)
        return run
    def ingest(self,target,group,searches):
        existing=sorted({self.store.get('alias',alias,{}).get('paper_id') for alias in group['ids']} - {None})
        paper_id=existing[0] if existing else sorted(group['ids'])[0]
        versions={}
        for key in existing:
            versions.update(self.store.get('paper',key,{}).get('versions',{}))
        for record in group['records']:versions[record['source']+':'+str(record['source_id'])]=record
        # Prefer indexed PubMed records, then Europe PMC, then registry records.
        ordered=sorted(versions.values(),key=lambda r:({'pubmed':0,'europe_pmc':1,'clinical_trials':2}.get(r['source'],3),str(r['source_id'])))
        paper=dict(ordered[0])
        for record in ordered[1:]:
            for field,value in record.items():
                if not paper.get(field) and value:paper[field]=value
        paper['id']=paper_id
        fingerprint=digest(versions)
        self.store.put('paper',paper_id,{'id':paper_id,'versions':versions,'paper':paper,'fingerprint':fingerprint})
        all_aliases=group['ids']|{alias for r in versions.values() for alias in identities(r)}
        for alias in all_aliases:self.store.put('alias',alias,{'paper_id':paper_id})
        proposal_id=digest([target['id'],target['scope_hash'],paper_id,fingerprint,VERSION])[:32]
        if self.store.get('proposal',proposal_id):return 0
        baseline=self.store.get('published',target['id'],{'version':0,'updates':[]})
        old_proposals=[p for key in set(existing+[paper_id]) for p in self.store.find('proposal',paper_id=key,target_id=target['id'])]
        for old in old_proposals:
            if old['target_id']==target['id'] and old['paper_id'] in set(existing+[paper_id]) and old['status'] in ('awaiting_extraction','review_ready','approved'):
                old['status']='superseded';self.store.put('proposal',old['id'],old)
        proposal={'id':proposal_id,'target_id':target['id'],'target':target,'paper_id':paper_id,'paper':paper,'source_versions':versions,'fingerprint':fingerprint,'scope_hash':target['scope_hash'],'status':'awaiting_extraction','created_at':now_iso(),'baseline_version':baseline['version'],'flags':flags_for(paper),'affected_dimensions':assessment_framework(target['entity_type'])['dimensions'],'diff':{'operation':'add_or_update_publication','before':next((u for u in baseline['updates'] if u['paper_id']==paper_id),None),'after':paper},'clinical_grade_change':None,'review_required':True}
        proposal['triage']=classify(paper,target)
        self.store.put('proposal',proposal_id,proposal)
        return 1
    def extract(self,proposal):
        try:
            triage=proposal.get('triage') or classify(proposal['paper'],proposal['target'])
            proposal['triage']=triage
            if hasattr(self.extractor,'select_tier'):self.extractor.select_tier(triage['model_tier'])
            # Reuse only within the same entity question, source text, schema,
            # URL and model. Metadata-only updates need not incur another call.
            cache_key=digest([proposal['scope_hash'],source_text(proposal['paper']),proposal['paper'].get('url'),VERSION,getattr(self.extractor,'model','test')])
            cached=self.store.get('extraction_cache',cache_key)
            result=cached or self.extractor.extract(proposal['target'],proposal['paper'])
            if not cached and result['status']=='review_ready':self.store.put('extraction_cache',cache_key,result)
            result={**result,'cache_hit':bool(cached),'cache_key':cache_key}
            proposal.update(status=result['status'],extraction=result)
            facts=result.get('facts',{})
            if facts.get('relevance',{}).get('value')=='unrelated':proposal['status']='excluded'
            proposal['synthesis']=build_synthesis(proposal,self.store.get('published',proposal['target_id'],{'version':0,'updates':[]}),self.config.get('synthesis_threshold',40))
            self.store.put('audit',str(uuid.uuid4()),{'action':'extraction_and_synthesis','proposal_id':proposal['id'],'target_id':proposal['target_id'],'at':now_iso(),'extraction_status':proposal['status'],'synthesis_status':proposal['synthesis']['status']})
            proposal['proposed_evidence_note']='; '.join(facts[field]['value'] for field in ('population','outcomes','effect_sizes','direction','limitations') if field in facts)
        except Exception as error:
            proposal['extraction_attempts']=proposal.get('extraction_attempts',0)+1
            proposal['next_extraction_at']=time.time()+3600*2**proposal['extraction_attempts']
            if proposal['extraction_attempts']>=3:proposal['status']='extraction_failed'
            proposal['extraction']={'status':proposal['status'],'error':type(error).__name__}
        self.store.put('proposal',proposal['id'],proposal)
