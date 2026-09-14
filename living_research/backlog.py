"""Backlog triage for the living-research review queue.

Bins order human attention and AI extraction. They never approve, publish or regrade anything.
  1 integrity          possible retraction, erratum or expression of concern (any target)
  2 flagship_priority  flagship question with a design that can move the answer, or safety/mortality content
  3 flagship_other     flagship question, lower review priority (protocols, registrations, unclear design)
  4 out_of_scope       outside the current flagship review scope; retained unchanged

`report` is read-only. `apply` stores labels. Deferral (bin 4 only) is explicit, needs a named reviewer
and a note, is written to the audit trail, and is undone by `restore_deferred`.
"""
import re
import time
import uuid
from datetime import datetime, timezone
from .triage import classify

VERSION = 'backlog-triage-v1'

# Phase 1 flagship questions (see the v2 blueprint, section E.1).
FLAGSHIP_TARGETS = frozenset({
    'compound:creatine-monohydrate', 'compound:vitamin-d3', 'entity:vitamin-d',
    'entity:ldl-c', 'entity:apob', 'entity:non-hdl-c', 'entity:lpa',
    'entity:hba1c-diagnosis', 'entity:fit', 'entity:psa-screening', 'entity:colonoscopy',
    'entity:her2-trastuzumab',
})

PENDING = ('awaiting_extraction', 'review_ready', 'extraction_failed')
BIN_LABELS = {1: 'integrity', 2: 'flagship_priority', 3: 'flagship_other', 4: 'out_of_scope'}

# CommentsCorrections RefTypes that signal an integrity event. CommentIn/Cites/UpdateIn do not.
INTEGRITY_REFS = {'RetractionIn', 'RetractionOf', 'RetractedandRepublishedIn', 'ErratumIn', 'ErratumFor',
                  'ExpressionOfConcernIn', 'ExpressionOfConcernFor', 'CorrectedandRepublishedIn'}
INTEGRITY_TYPES = {'retracted publication', 'retraction of publication', 'published erratum', 'expression of concern'}
INTEGRITY_TITLE = re.compile(r'\b(?:retraction|retracted|expression of concern|erratum|correction to)\b', re.I)

# Recent PubMed records often lack MEDLINE publication types, so wording is a fallback design signal.
DESIGN_WORDING = (
    ('evidence_synthesis', re.compile(r'meta-?analys|systematic review', re.I)),
    ('guideline', re.compile(r'\bguideline|consensus statement|position statement', re.I)),
    ('randomized_trial', re.compile(r'\brandomi[sz]ed\b|placebo[- ]controlled', re.I)),
    ('observational', re.compile(r'\bcohort\b|case[- ]control|cross[- ]sectional|prospective study', re.I)),
)
CORE = {'randomized_trial', 'evidence_synthesis', 'guideline'}
PRIORITY_DESIGNS = {
    'intervention': CORE,
    'biomarker': CORE | {'observational'},
    'diagnostic': CORE | {'observational'},
    'screening': CORE,
    'precision_oncology': CORE,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def integrity_notice(paper):
    refs = {c.get('type') for c in paper.get('corrections') or [] if isinstance(c, dict)}
    types = {str(t).lower() for t in paper.get('publication_types') or []}
    return bool(refs & INTEGRITY_REFS or types & INTEGRITY_TYPES or INTEGRITY_TITLE.search(paper.get('title') or ''))


def design_signal(paper, triage):
    kind = triage['study_type_candidate']
    if kind != 'unclassified':
        return kind, 'publication type'
    text = f"{paper.get('title') or ''} {paper.get('abstract') or ''}"
    for candidate, pattern in DESIGN_WORDING:
        if pattern.search(text):
            return candidate, 'title/abstract wording'
    return 'unclassified', None


def assign_bin(proposal, flagship=FLAGSHIP_TARGETS):
    paper = proposal['paper']
    target = proposal.get('target') or {'id': proposal['target_id'], 'entity_type': 'intervention'}
    triage = classify(paper, target)
    kind, basis = design_signal(paper, triage)
    safety = 'Possible safety or mortality content' in triage['reasons']
    in_flagship = proposal['target_id'] in flagship
    priority_design = kind in PRIORITY_DESIGNS.get(target.get('entity_type'), CORE)
    if integrity_notice(paper):
        number, reason = 1, 'Possible retraction, erratum or expression of concern'
    elif in_flagship and (priority_design or safety):
        number, reason = 2, 'Flagship question · ' + (kind.replace('_', ' ') if priority_design else 'safety or mortality content')
    elif in_flagship:
        number, reason = 3, f"Flagship question · {kind.replace('_', ' ')} · lower review priority"
    else:
        number, reason = 4, 'Outside the current flagship review scope'
    return {'version': VERSION, 'bin': number, 'label': BIN_LABELS[number], 'reason': reason,
            'design_signal': kind, 'design_basis': basis, 'flagship': in_flagship, 'impact_score': triage['impact_score']}


def queue_sort_key(proposal, now=None):
    """Extraction order: lower bin first, then impact plus one point per day of age."""
    now = now or datetime.now(timezone.utc)
    queue = proposal.get('queue') or assign_bin(proposal)
    try:
        age = max(0.0, (now - datetime.fromisoformat(proposal['created_at'])).total_seconds() / 86400)
    except (KeyError, TypeError, ValueError):
        age = 0.0
    return (queue['bin'], -((proposal.get('triage') or {}).get('impact_score', queue['impact_score']) + age))


def _lease(store):
    owner = f'backlog-{uuid.uuid4()}'
    if not store.acquire(owner):
        raise RuntimeError('Research state is busy (a monitoring run holds the lease); retry after it finishes')
    return owner


def triage_backlog(store, apply=False, defer=False, actor=None, note=None, flagship=FLAGSHIP_TARGETS):
    if defer and not (apply and actor and actor.strip() and note and note.strip()):
        raise ValueError('Deferral requires apply, a named reviewer and a note')
    owner = _lease(store) if apply else None
    try:
        at = _now()
        report = {'version': VERSION, 'applied': apply, 'pending': 0, 'deferred': 0,
                  'bins': {label: 0 for label in BIN_LABELS.values()}, 'by_target': {}}
        for status in PENDING:
            for proposal in store.find('proposal', status=status):
                report['pending'] += 1
                queue = assign_bin(proposal, flagship)
                report['bins'][queue['label']] += 1
                per_target = report['by_target'].setdefault(proposal['target_id'], {label: 0 for label in BIN_LABELS.values()})
                per_target[queue['label']] += 1
                if not apply:
                    continue
                store.renew(owner)
                proposal['queue'] = {**queue, 'assigned_at': at}
                if defer and queue['bin'] == 4:
                    proposal['deferral'] = {'from_status': proposal['status'], 'by': actor, 'note': note, 'at': at, 'version': VERSION}
                    proposal['status'] = 'deferred'
                    report['deferred'] += 1
                store.put('proposal', proposal['id'], proposal)
        if apply:
            store.put('audit', str(uuid.uuid4()), {'action': 'backlog_triage', 'at': at, 'actor': actor or 'backlog-cli',
                                                   'note': note, 'bins': report['bins'], 'deferred': report['deferred'], 'version': VERSION})
        return report
    finally:
        if owner:
            store.release(owner)


def restore_deferred(store, actor, note, target_id=None):
    if not actor or not actor.strip() or not note or not note.strip():
        raise ValueError('Restoring deferred proposals requires a named reviewer and a note')
    owner = _lease(store)
    try:
        at = _now()
        filters = {'target_id': target_id} if target_id else {}
        restored = 0
        for proposal in store.find('proposal', status='deferred', **filters):
            store.renew(owner)
            deferral = proposal.pop('deferral', {}) or {}
            proposal['status'] = deferral.get('from_status', 'awaiting_extraction')
            proposal.setdefault('deferral_history', []).append({**deferral, 'restored_by': actor, 'restored_at': at, 'restore_note': note})
            store.put('proposal', proposal['id'], proposal)
            restored += 1
        store.put('audit', str(uuid.uuid4()), {'action': 'backlog_restore', 'at': at, 'actor': actor, 'note': note,
                                               'target_id': target_id, 'restored': restored, 'version': VERSION})
        return {'version': VERSION, 'restored': restored, 'target_id': target_id}
    finally:
        store.release(owner)


def summarize(report, top=15):
    ranked = sorted(report['by_target'].items(), key=lambda item: (-sum(item[1].values()), item[0]))
    return {**{k: v for k, v in report.items() if k != 'by_target'},
            'targets_with_pending': len(ranked), 'top_targets': dict(ranked[:top])}
