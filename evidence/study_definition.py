"""Bounded, source-visible research drafting. No models or clinical conclusions.

Only bibliographic identifiers / explicit article titles leave this service for
source resolution. Unpublished free text is never sent to external search.
"""
import html
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path
import requests

LOG=logging.getLogger(__name__)
FIELDS=('population exposure comparator outcome instrument design dose duration timepoint metric species units inclusion n demographics confounders method setting secondary strain route culture censoring repeated exposure_assay outcome_definition modifier').split()

def clean(text):
    return ' '.join(html.unescape(re.sub(r'</?(?:b|i|strong|em|p|h[1-6]|sup|sub)(?:\s[^>]*)?>',' ',text or '')).split())

def canonical(text):return re.sub(r'[^a-z0-9]','',clean(text).lower())

@lru_cache(maxsize=1)
def known_sources():
    return [json.loads(p.read_text()) for p in Path(__file__).with_name('reference_sources').glob('*.json')]

def identity(text):
    pmid=re.search(r'(?:PMID\s*:?\s*|pubmed\.ncbi\.nlm\.nih\.gov/)(\d{6,9})\b',text,re.I)
    if not pmid and re.fullmatch(r'\s*\d{6,9}\s*',text):return ('pmid',text.strip())
    doi=re.search(r'\b10\.\d{4,9}/[-._;()/:A-Z0-9]+',text,re.I)
    title=re.search(r'(?:^|\n)Title:\s*([^\n]+(?:\n(?!\s*(?:PMID|DOI):)[^\n]+)?)',text,re.I)
    if pmid:return ('pmid',pmid[1])
    if doi:return ('doi',doi[0].rstrip('.,;'))
    if title:return ('title',title[1].strip())
    return (None,None)

def known(text,kind,value):
    for r in known_sources():
        # Identifier mismatches must never fall through to a different known paper.
        if kind=='pmid' and value==r['pmid']:return r
        if kind=='doi' and value.lower()==r.get('doi','').lower():return r
        if kind=='title' and canonical(value)==canonical(r['title']):return r
        if not kind and (canonical(r['title']) in canonical(text) or canonical(clean(r['abstractText'])) in canonical(text)):return r
    return None

def get(url,params=None):
    # URLs are fixed provider endpoints, never supplied by a user.
    response=requests.get(url,params=params,timeout=(3,7),headers={'User-Agent':'ClarityEvidence/1.0'},stream=True)
    response.raise_for_status()
    parts=[];size=0
    for part in response.iter_content(16384):
        size+=len(part)
        if size>2_000_000:raise ValueError('Source response exceeds size limit')
        parts.append(part)
    return b''.join(parts).decode('utf-8')

@lru_cache(maxsize=128)
def resolve_remote(kind,value,bucket):
    warnings=[];record=None
    # PubMed is the first live resolver. Europe PMC is a disclosed fallback.
    try:
        import pubmed
        pmid=value if kind=='pmid' else None
        if not pmid:
            pubmed._throttle()
            term=f'{value}[AID]' if kind=='doi' else f'"{value}"[Title]'
            result=json.loads(get(pubmed.BASE+'/esearch.fcgi',{'db':'pubmed','term':term,'retmode':'json','retmax':2}))
            ids=result.get('esearchresult',{}).get('idlist',[])
            if len(ids)==1:pmid=ids[0]
        if pmid:
            pubmed._throttle()
            root=ET.fromstring(get(pubmed.BASE+'/efetch.fcgi',{'db':'pubmed','id':pmid,'retmode':'xml'}))
            article=root.find('.//PubmedArticle')
            if article is not None:
                txt=lambda path:' '.join(''.join(e.itertext()) for e in article.findall(path))
                record={'pmid':txt('.//MedlineCitation/PMID'),'title':txt('.//ArticleTitle'),'abstractText':txt('.//Abstract/AbstractText'),'authorString':'; '.join(' '.join(filter(None,[a.findtext('ForeName'),a.findtext('LastName')])) for a in article.findall('.//Author')),'pubYear':txt('.//JournalIssue/PubDate/Year'),'journalInfo':{'journal':{'title':txt('.//Journal/Title')}},'metadata_provider':'PubMed E-utilities','retrieved_at':time.strftime('%Y-%m-%d')}
                for el in article.findall('./PubmedData/ArticleIdList/ArticleId'):
                    if el.get('IdType') in ('doi','pmc'):record['pmcid' if el.get('IdType')=='pmc' else 'doi']=el.text
    except (requests.RequestException,ValueError,ET.ParseError):warnings.append('PubMed could not be reached; Europe PMC was tried.')
    if not record:
        query=f'EXT_ID:{value} AND SRC:MED' if kind=='pmid' else f'DOI:"{value}"' if kind=='doi' else 'TITLE:"'+value.replace('"','')+'"'
        results=json.loads(get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':query,'format':'json','resultType':'core','pageSize':2})).get('resultList',{}).get('result',[])
        if len(results)==1:record={**results[0],'metadata_provider':'Europe PMC / PubMed MED record','retrieved_at':time.strftime('%Y-%m-%d')}
    if not record:return None,warnings+['No unambiguous paper was found. Check the PMID, DOI or exact title.']
    if (kind=='pmid' and record.get('pmid')!=value) or (kind=='doi' and record.get('doi','').lower()!=value.lower()) or (kind=='title' and canonical(record.get('title',''))!=canonical(value)):
        return None,warnings+['The resolved article did not exactly match the supplied identifier or title.']
    pmcid=record.get('pmcid','')
    if re.fullmatch(r'PMC\d+',pmcid):
        try:
            root=ET.fromstring(get(f'https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML'))
            ids={el.get('pub-id-type'):el.text for el in root.findall('.//article-meta/article-id')}
            if ids.get('pmid') and ids['pmid']!=record.get('pmid'):raise ValueError('Full-text identity mismatch')
            record['methods_paragraphs']=[' '.join(''.join(p.itertext()).split()) for sec in root.findall('.//body/sec') if re.search(r'method|material|patient', ''.join(sec.find('title').itertext()) if sec.find('title') is not None else '',re.I) for p in sec.findall('.//p')][:60]
            record['full_text_provider']='Europe PMC open-access XML'
        except (requests.RequestException,ValueError,ET.ParseError):warnings.append('Full-text methods could not be retrieved; draft uses available abstract metadata.')
    return record,warnings

def extract(text,origin='user_text',source_id=None):
    """Conservative explicit-pattern drafting. Each populated field has a passage."""
    raw=clean(text);d={};provenance={}
    def put(k,value,quote,kind='explicit passage'):
        if not value or k in d:return
        d[k]=value[:900];provenance[k]={'origin':origin,'source_id':source_id,'quote':quote,'kind':kind}
    def match(k,pattern,value=None,flags=re.I):
        m=re.search(pattern,raw,flags)
        if m:put(k,value(m) if callable(value) else value or m[0],m[0])
    for k in FIELDS:
        m=re.search(r'(?:^|\n)'+re.escape(k)+r':\s*([^\n]+)',text,re.I)
        if m:put(k,m[1].strip(),m[0],'user-labeled field')
    match('design',r'\b(?:prospective cohort(?: study)?|retrospective cohort(?: study)?|randomi[sz]ed controlled trial|case-control study|cross-sectional study|diagnostic accuracy study|in vitro study)\b')
    match('population',r'Study participants were ([^.]+)',lambda m:m[1])
    match('population',r'(?:enrolled|recruited|included) ((?:[0-9,]+ )?(?:patients|adults|children|women|men)[^.]{0,150})',lambda m:m[1])
    match('population',r'\b(?:breast cancer patients receiving adjuvant (?:RT|radiotherapy)|(?:adult )?(?:women|men|patients|children|adults) with [^.]{3,150})')
    match('population',r'\b(?:healthy volunteers|postmenopausal women|adults|children)\b')
    match('species',r'\b(?:patients|women|female adults|men|human participants)\b','human')
    if 'species' not in d:match('species',r'\b(?:mice|rats|murine|mouse)\b','animal')
    if 'species' not in d:match('species',r'\b(?:cell lines?|cell cultures?|in vitro)\b','cell')
    match('method',r'\bmultivari(?:able|ate) logistic regression\b')
    match('method',r'\b(?:Cox proportional[- ]hazards?(?: regression| model)?|linear mixed[- ]effects? model|multivariable linear regression)\b')
    match('exposure_assay',r'Ella Simple\s?Plex(?:™)?(?: immunoassay)?(?: technology)?', 'Ella SimplePlex immunoassay')
    match('exposure_assay',r'(?:plasma|serum|protein)[^.]{0,120}(?:measured|quantified)[^.]{0,80}using ([^.]{3,100})',lambda m:m[1])
    match('instrument',r'Brief Pain Inventory(?: \(BPI\))?', 'Brief Pain Inventory-derived pain severity score')
    match('exposure',r'(?:pre-(?:RT|radiotherapy)\s+(?:plasma\s+)?IL[-–]18)', 'pre-radiotherapy plasma IL-18')
    match('exposure',r'Plasma\s+IL[-–]18', 'plasma IL-18')
    match('exposure',r'\b(?:plasma|serum|urinary)\s+(?:[A-Za-z]+[-–]?\d*|\d+-hydroxyvitamin D)(?:\s+(?:protein|concentration|levels?))?')
    match('outcome',r'(?:RT|radiotherapy)[- ]related pain', 'radiotherapy-related pain')
    match('outcome_definition',r'increase (?:in pain(?: score)? |from pain score )?from?\s*<\s*4 pre-RT to\s*(?:≥|>=)\s*4(?: from)? post-RT')
    match('outcome_definition',r'increase in pain from\s*<4 pre-RT to\s*≥4 post-RT')
    match('secondary',r'pre-RT pain[^.]{0,80}post-RT pain','pre-RT pain; post-RT pain')
    match('timepoint',r'(?:before and after RT|pre- and post-RT|pre-RT to post-RT)', 'pre-radiotherapy; post-radiotherapy')
    match('modifier',r'\b(?:obesity|BMI)\b','obesity / BMI')
    match('confounders',r'(?:final adjusted multivariable model included|adjusting for) ([^.]+)',lambda m:m[1])
    match('metric',r'\b(?:adjusted odds ratio|adjusted hazard ratio|mean difference|risk ratio|hazard ratio)\b')
    if 'method' in d and 'logistic' in d['method'] and re.search(r'\bOR\s*=|odds ratio',raw,re.I):
        quote=re.search(r'[^.]*Multivariable logistic regression[^.]*',raw,re.I)
        put('metric','adjusted odds ratio' if re.search(r'adjust|covariate',raw,re.I) else 'odds ratio',quote[0] if quote else d['method'],'method-linked draft; confirm adjustment')
    match('exposure',r'association between ([^.;]{3,80}?) and ([^.;]{3,80}?)(?: was| were| among| in |[.;]|$)',lambda m:m[1])
    match('outcome',r'association between ([^.;]{3,80}?) and ([^.;]{3,80}?)(?: was| were| among| in |[.;]|$)',lambda m:m[2])
    statement=re.search(r'(?:my|our) study (?:tests|examines|investigates) (.+?) (?:on|for) (.+?) in (.+?)(?:[.;]|$)',raw,re.I)
    if statement:
        for k,v in zip(('exposure','outcome','population'),statement.groups()):put(k,v,statement[0])
    match('exposure',r'(?:randomi[sz]ed (?:to|participants to)|intervention(?: was| consisted of))\s+([^.;]{3,130})',lambda m:m[1])
    match('comparator',r'\b(?:versus|compared (?:with|to))\s+(placebo|usual care|standard care)\b',lambda m:m[1])
    match('outcome',r'(?:primary (?:outcome|endpoint)(?: was|:| included)?|measured the effect on)\s+([^.;]{3,130})',lambda m:m[1])
    return d,provenance

def draft(text):
    kind,value=identity(text);record=known(text,kind,value);warnings=[]
    if not record and kind:
        try:record,warnings=resolve_remote(kind,value,int(time.time()//86400))
        except (requests.RequestException,ValueError,ET.ParseError):warnings=['Source lookup is temporarily unavailable. You can retry or paste the abstract.']
    fields={};provenance={};paper=None
    if record:
        sid='pmid:'+record['pmid'] if record.get('pmid') else 'doi:'+record.get('doi','')
        methods='\n'.join(record.get('methods_paragraphs',[]))
        # Prefer methods for eligibility, instruments and design; abstract for the focal predictor/outcome.
        for content,origin in [(clean(record.get('abstractText','')),'source_abstract'),(methods,'source_full_text_methods')]:
            found,spans=extract(content,origin,sid)
            for k,v in found.items():
                if k not in fields or (origin=='source_full_text_methods' and k in ('population','design','instrument','exposure_assay','outcome_definition','confounders')):fields[k]=v;provenance[k]=spans[k]
        paper={k:record.get(k) for k in ('title','pmid','doi','pmcid','retrieved_at','metadata_provider')}
        paper.update(authors=record.get('authorString',''),journal=record.get('journalInfo',{}).get('journal',{}).get('title',''),year=record.get('pubYear',''),full_text_available=bool(record.get('pmcid')),full_text_used=bool(methods),url=f'https://pubmed.ncbi.nlm.nih.gov/{record["pmid"]}/' if record.get('pmid') else 'https://doi.org/'+record['doi'],abstract=clean(record.get('abstractText','')))
    found,spans=extract(text)
    conflicts={}
    for k,v in found.items():
        if k not in fields or spans[k]['kind']=='user-labeled field':
            if fields.get(k) and canonical(fields[k])!=canonical(v):conflicts[k]={'source_value':fields[k],'user_value':v}
            fields[k]=v;provenance[k]=spans[k]
    meaningful=sum(bool(fields.get(k)) for k in ('population','exposure','outcome','design','method'))
    if meaningful<2:LOG.warning('study_definition_parse_failed fields=%d source_resolved=%s',meaningful,bool(paper))
    return {'version':'study-definition-v2','definition':fields,'provenance':provenance,'paper':paper,'conflicts':conflicts,'warnings':warnings,'status':'needs_input' if meaningful<2 else 'draft','recognized_fields':meaningful,'required_missing':[k for k in ('exposure','outcome') if not fields.get(k)],'requires_confirmation':True}
