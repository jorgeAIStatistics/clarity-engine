"""Bounded scheduling signals, separate from evidence strength.
Traffic is operator-supplied aggregate count; no visitor identifiers are stored.
"""
import math

def bounded(value, maximum):
    try:value=float(value)
    except (ValueError,TypeError):return 0
    return min(maximum,max(0,value)) if math.isfinite(value) else 0

def priority_score(target, now):
    age_days=max(0,(now-target.get('next_due',now))/86400) if target.get('next_due') else 30
    traffic=min(20,math.log1p(bounded(target.get('monthly_views'),10000000))*2)
    volatility=min(20,math.log1p(bounded(target.get('recent_publications'),10000))*3)
    return bounded(target.get('priority'),100)+traffic+volatility+min(365,age_days)+bounded(target.get('feedback_priority_boost'),20)
