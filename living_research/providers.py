"""Strict source adapters: incomplete retrieval never advances a watermark."""
import hashlib
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import requests

class RetrievalError(RuntimeError): pass
class IncompleteSearch(RetrievalError): pass

def text(node): return ''.join(node.itertext()).strip() if node is not None else ''
def digest(value): return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def normalize_doi(value): return re.sub(r'^(https?://(?:dx\.)?doi.org/|doi:\s*)','',str(value or '').strip(),flags=re.I).lower().rstrip('.')
def identities(record):
    ids=[]
    for field in ('pmid','pmcid','doi','nct_id'):
        value=record.get(field)
        if value: ids.append(f'{field}:{normalize_doi(value) if field=="doi" else str(value).strip()}')
    if not ids and record.get('source_id'): ids.append(f'{record["source"]}:{record["source_id"]}')
    return ids

def _quote(term): return '"'+re.sub(r'["\[\]{}()]',' ',term).strip()+'"'
def _term_groups(target): return target.get('term_groups') or [[target['name'],*target.get('aliases',[])]]

def query_for(target):
    return ' AND '.join('('+' OR '.join(_quote(term) for term in group if term)+')' for group in _term_groups(target))

def europe_pmc_query_for(target):
    """Title/abstract only. Europe PMC's default search also matches full text, e.g. "creatine kinase"
    in methods sections, which returned 11,923 creatine records in 30 days versus 1,340 in titles/abstracts."""
    return ' AND '.join('('+' OR '.join(f'TITLE:{_quote(term)} OR ABSTRACT:{_quote(term)}' for term in group if term)+')' for group in _term_groups(target))

class HTTP:
    def __init__(self): self.session=requests.Session();self.last=0
    def get(self,url,params):
        if getattr(self,'heartbeat',None):self.heartbeat()
        for attempt in range(3):
            time.sleep(max(0,.36-(time.monotonic()-self.last)))
            self.last=time.monotonic()
            try:
                response=self.session.get(url,params=params,timeout=30,headers={'User-Agent':'ClarityLivingResearch/1.0'})
                if response.status_code==429 or response.status_code>=500:
                    if attempt<2: time.sleep(2**attempt);continue
                response.raise_for_status();return response
            except requests.RequestException:
                if attempt==2: raise RetrievalError('Source request failed after retries') from None
                time.sleep(2**attempt)

class PubMed:
    name='pubmed'
    def __init__(self,http=None):self.http=http or HTTP()
    def search(self,target,since,until,limit=300):
        query=query_for(target)
        auth={k:v for k,v in {'api_key':os.getenv('NCBI_API_KEY'),'email':os.getenv('CLARITY_CONTACT_EMAIL'),'tool':'clarity_living_research'}.items() if v}
        params=dict(db='pubmed',term=query,datetype='mdat',mindate=since.replace('-','/'),maxdate=until.replace('-','/'),retmode='json',retmax=min(limit,9999),**auth)
        result=self.http.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi',params).json()
        if 'error' in result or 'esearchresult' not in result: raise RetrievalError('Invalid PubMed search response')
        result=result['esearchresult']
        if result.get('errorlist'): raise RetrievalError('PubMed rejected the query')
        count=int(result['count']);ids=result['idlist']
        if count>limit or len(ids)!=count:raise IncompleteSearch('PubMed window exceeds the configured record cap; narrow the date window')
        records=[];books=set()
        for offset in range(0,len(ids),100):
            batch=ids[offset:offset+100]
            xml=self.http.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi',dict(db='pubmed',id=','.join(batch),retmode='xml',**auth)).text
            records.extend(self.parse(xml));books|=self.book_pmids(xml)
        # Every PMID must be accounted for: parsed as a study record or identified as a Bookshelf chapter.
        if {r['pmid'] for r in records}|books!=set(ids):raise RetrievalError('PubMed fetch omitted records')
        return records,{'query':query,'date_field':'mdat','since':since,'until':until,'count':count,'book_chapters_excluded':len(books),'complete':True}
    @staticmethod
    def book_pmids(xml):
        """Bookshelf chapters (GeneReviews, LiverTox, StatPearls) are reference texts, not study reports."""
        return {n.findtext('./BookDocument/PMID') for n in ET.fromstring(xml).findall('.//PubmedBookArticle')}-{None}
    @staticmethod
    def parse(xml):
        root=ET.fromstring(xml);out=[]
        for article in root.findall('.//PubmedArticle'):
            pmid=article.findtext('./MedlineCitation/PMID')
            identifiers={n.get('IdType'):text(n) for n in article.findall('.//ArticleId')}
            types=[text(n) for n in article.findall('.//PublicationType')]
            corrections=[{'type':n.get('RefType'),'pmid':n.findtext('PMID')} for n in article.findall('.//CommentsCorrections')]
            out.append(dict(source='pubmed',source_id=pmid,pmid=pmid,doi=normalize_doi(identifiers.get('doi')),pmcid=identifiers.get('pmc'),title=text(article.find('.//ArticleTitle')),abstract='\n'.join(text(n) for n in article.findall('.//AbstractText')),conflicts=text(article.find('.//CoiStatement')),journal=text(article.find('.//Journal/Title')),publication_types=types,publication_date='-'.join(filter(None,[article.findtext('.//PubDate/Year'),article.findtext('.//PubDate/Month'),article.findtext('.//PubDate/Day')])),corrections=corrections,is_preprint=any('preprint' in t.lower() for t in types),url=f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'))
        return out

class EuropePMC:
    name='europe_pmc'
    def __init__(self,http=None):self.http=http or HTTP()
    def search(self,target,since,until,limit=300):
        # First index date, not UPDATE_DATE: bulk re-stamping put 4,458 creatine records on a single day,
        # above any per-day cap, so the window could never complete. Changes to MEDLINE records, including
        # retractions and corrections, are still caught by PubMed's modification-date search.
        query=f'{europe_pmc_query_for(target)} AND FIRST_IDATE:[{since} TO {until}]'
        cursor='*';records=[];seen=set()
        while True:
            data=self.http.get('https://www.ebi.ac.uk/europepmc/webservices/rest/search',dict(query=query,format='json',resultType='core',pageSize=min(100,limit),cursorMark=cursor)).json()
            if 'hitCount' not in data:raise RetrievalError('Invalid Europe PMC response')
            count=int(data['hitCount'])
            if count>limit:raise IncompleteSearch('Europe PMC window exceeds the record cap')
            page=data.get('resultList',{}).get('result',[])
            for r in page:
                key=f'{r.get("source")}:{r.get("id")}'
                if key in seen:continue
                seen.add(key)
                types=r.get('pubTypeList',{}).get('pubType',[])
                if isinstance(types,str):types=[types]
                records.append(dict(source=self.name,source_id=key,pmid=r.get('pmid'),pmcid=r.get('pmcid'),doi=normalize_doi(r.get('doi')),title=r.get('title',''),abstract=r.get('abstractText',''),publication_types=types,publication_date=r.get('firstPublicationDate'),journal=r.get('journalInfo',{}).get('journal',{}).get('title'),is_preprint=r.get('source')=='PPR' or any('preprint' in t.lower() for t in types),url=f'https://europepmc.org/article/{r.get("source")}/{r.get("id")}'))
            if len(records)>=count:break
            next_cursor=data.get('nextCursorMark')
            if not page or not next_cursor or next_cursor==cursor:raise RetrievalError('Europe PMC pagination incomplete')
            cursor=next_cursor
        return records,dict(query=query,date_field='FIRST_IDATE',since=since,until=until,count=count,complete=True)

class ClinicalTrials:
    name='clinical_trials'
    def __init__(self,http=None):self.http=http or HTTP()
    def search(self,target,since,until,limit=300):
        query=f'{query_for(target)} AND AREA[LastUpdatePostDate]RANGE[{since}, {until}]'
        params={'query.term':query,'pageSize':min(100,limit),'countTotal':'true','format':'json'}
        records=[];tokens=set()
        while True:
            data=self.http.get('https://clinicaltrials.gov/api/v2/studies',params).json()
            if 'studies' not in data:raise RetrievalError('Invalid ClinicalTrials.gov response')
            if data.get('totalCount',0)>limit:raise IncompleteSearch('Trial registry window exceeds the record cap')
            for study in data['studies']:
                p=study['protocolSection'];ident=p['identificationModule'];nct=ident['nctId']
                evidence={key:p.get(key,{}) for key in ('descriptionModule','designModule','armsInterventionsModule','outcomesModule','eligibilityModule','statusModule','sponsorCollaboratorsModule')}
                evidence['resultsSection']=study.get('resultsSection')
                records.append(dict(source=self.name,source_id=nct,nct_id=nct,title=ident.get('briefTitle',''),abstract=json.dumps(evidence,sort_keys=True),publication_types=['Trial registration'],is_preprint=False,has_results=study.get('hasResults',False),publication_date=p.get('statusModule',{}).get('lastUpdatePostDateStruct',{}).get('date'),url=f'https://clinicaltrials.gov/study/{nct}'))
            if len(records)>limit:raise IncompleteSearch('Trial registry record cap reached')
            token=data.get('nextPageToken')
            if not token:break
            if token in tokens:raise RetrievalError('Repeated trial registry page token')
            tokens.add(token);params['pageToken']=token
        return records,dict(query=query,date_field='LastUpdatePostDate',since=since,until=until,count=len(records),complete=True)
