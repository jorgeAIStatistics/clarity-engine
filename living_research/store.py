import json
import os
import sqlite3
import time
from pathlib import Path

class Store:
    """Same durable state model on local SQLite and deployed PostgreSQL."""
    def __init__(self, location=None):
        location=location or os.getenv('CLARITY_RESEARCH_DATABASE_URL') or os.getenv('DATABASE_URL') or 'research_state/living.sqlite3'
        self.pg=location.startswith(('postgres://','postgresql://'))
        if self.pg:
            import psycopg
            from psycopg.rows import dict_row
            self.db=psycopg.connect(location,autocommit=True,row_factory=dict_row)
        else:
            if location!=':memory:': Path(location).parent.mkdir(parents=True,exist_ok=True)
            self.db=sqlite3.connect(location,isolation_level=None,timeout=30)
            self.db.row_factory=sqlite3.Row
            self.db.execute('PRAGMA journal_mode=WAL')
        self.execute('CREATE TABLE IF NOT EXISTS clarity_research_records (kind TEXT NOT NULL, id TEXT NOT NULL, payload TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL, PRIMARY KEY(kind,id))')
        for field in ('paper_id','target_id','status'):
            expression=f"(payload::jsonb->>'{field}')" if self.pg else f"json_extract(payload, '$.{field}')"
            self.execute(f'CREATE INDEX IF NOT EXISTS clarity_research_{field}_idx ON clarity_research_records(kind,{expression})')
        self.execute('CREATE TABLE IF NOT EXISTS clarity_research_leases (id TEXT PRIMARY KEY, owner TEXT NOT NULL, expires DOUBLE PRECISION NOT NULL)')
    def execute(self, sql, args=()):
        return self.db.execute(sql.replace('?', '%s') if self.pg else sql,args)
    def get(self, kind, key, default=None):
        row=self.execute('SELECT payload FROM clarity_research_records WHERE kind=? AND id=?',(kind,key)).fetchone()
        return json.loads(row['payload']) if row else default
    def put(self, kind, key, value):
        self.execute('INSERT INTO clarity_research_records(kind,id,payload,updated) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated',(kind,key,json.dumps(value,sort_keys=True,allow_nan=False),time.time()))
    def all(self, kind):
        return [json.loads(r['payload']) for r in self.execute('SELECT payload FROM clarity_research_records WHERE kind=? ORDER BY updated DESC',(kind,)).fetchall()]
    def find(self, kind, limit=None, oldest=False, **fields):
        allowed={'target_id','paper_id','status'}
        if set(fields)-allowed:raise ValueError('Unsupported research filter')
        clauses=['kind=?'];args=[kind]
        for key,value in fields.items():
            expression=f"payload::jsonb->>'{key}'" if self.pg else f"json_extract(payload, '$.{key}')"
            clauses.append(expression+'=?');args.append(value)
        sql='SELECT payload FROM clarity_research_records WHERE '+' AND '.join(clauses)+' ORDER BY updated '+('ASC' if oldest else 'DESC')
        if limit is not None:sql+=' LIMIT ?';args.append(limit)
        return [json.loads(row['payload']) for row in self.execute(sql,args).fetchall()]
    def pending_count(self,target_id):
        target="payload::jsonb->>'target_id'" if self.pg else "json_extract(payload, '$.target_id')"
        state="payload::jsonb->>'status'" if self.pg else "json_extract(payload, '$.status')"
        row=self.execute(f"SELECT COUNT(*) AS n FROM clarity_research_records WHERE kind='proposal' AND {target}=? AND {state} IN ('awaiting_extraction','review_ready','approved','extraction_failed')",(target_id,)).fetchone()
        return row['n']
    def acquire(self, owner):
        now=time.time()
        return self.execute("INSERT INTO clarity_research_leases(id,owner,expires) VALUES('monitor',?,?) ON CONFLICT(id) DO UPDATE SET owner=excluded.owner,expires=excluded.expires WHERE clarity_research_leases.expires<?",(owner,now+600,now)).rowcount==1
    def renew(self, owner):
        changed=self.execute("UPDATE clarity_research_leases SET expires=? WHERE id='monitor' AND owner=? AND expires>?",(time.time()+600,owner,time.time())).rowcount
        if changed!=1: raise RuntimeError('Research worker lease was lost')
    def release(self, owner):
        self.execute("DELETE FROM clarity_research_leases WHERE id='monitor' AND owner=?",(owner,))
    def close(self): self.db.close()
