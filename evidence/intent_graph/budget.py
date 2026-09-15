"""Persistent daily provider cap; separate from research extraction budgets."""
import os
from datetime import datetime,timezone
from evidence_pipeline.state import State
from evidence_pipeline.config import Settings

def reserve():
    state=State(Settings.from_env().state_path)
    day=datetime.now(timezone.utc).date().isoformat()
    cap=max(0,min(1000,int(os.getenv('CLARITY_INTENT_DAILY_CALLS','100'))))
    try:
        with state.transaction():
            # PostgreSQL transaction advisory lock serializes API processes.
            if state.pg:state.execute('SELECT pg_advisory_xact_lock(72180419)')
            record=state.get('intent_budget',day) or {'calls':0}
            if record['calls']>=cap:raise RuntimeError('daily_intent_budget_exhausted')
            state.put('intent_budget',day,{'calls':record['calls']+1})
    finally:state.close()
