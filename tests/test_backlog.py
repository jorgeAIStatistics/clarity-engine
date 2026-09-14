import unittest
from datetime import datetime, timezone
from living_research.store import Store
from living_research.backlog import assign_bin, triage_backlog, restore_deferred, queue_sort_key, summarize, BIN_LABELS


def proposal(pid, target_id='entity:apob', entity_type='biomarker', status='awaiting_extraction', created='2026-09-01T00:00:00+00:00', **paper):
    base = {'title': 'A study', 'abstract': '', 'publication_types': ['Journal Article'], 'url': f'https://pubmed.ncbi.nlm.nih.gov/{pid}/'}
    return {'id': pid, 'target_id': target_id, 'target': {'id': target_id, 'entity_type': entity_type}, 'paper_id': 'pmid:' + pid,
            'paper': {**base, **paper}, 'status': status, 'created_at': created, 'flags': []}


class AssignBinTests(unittest.TestCase):
    def test_integrity_notice_ranks_first_for_any_target(self):
        p = proposal('1', target_id='compound:bpc-157', entity_type='intervention', title='Retraction Note: BPC-157 and tendon healing')
        self.assertEqual(assign_bin(p)['bin'], 1)
        p = proposal('2', target_id='compound:bpc-157', entity_type='intervention', corrections=[{'type': 'ErratumIn', 'pmid': '9'}])
        self.assertEqual(assign_bin(p)['bin'], 1)

    def test_comment_links_and_adjustment_wording_are_not_integrity_events(self):
        p = proposal('3', target_id='compound:bpc-157', entity_type='intervention', corrections=[{'type': 'CommentIn', 'pmid': '9'}],
                     abstract='Estimates were corrected for age and sex.')
        self.assertEqual(assign_bin(p)['bin'], 4)

    def test_flagship_priority_designs_by_domain(self):
        rct = proposal('4', target_id='compound:creatine-monohydrate', entity_type='intervention', publication_types=['Randomized Controlled Trial'])
        self.assertEqual(assign_bin(rct)['bin'], 2)
        untagged = proposal('5', target_id='compound:creatine-monohydrate', entity_type='intervention', abstract='In this randomised, placebo-controlled trial of 80 adults')
        queue = assign_bin(untagged)
        self.assertEqual((queue['bin'], queue['design_basis']), (2, 'title/abstract wording'))
        cohort_biomarker = proposal('6', abstract='In a prospective cohort of 12,000 adults, ApoB predicted events.')
        self.assertEqual(assign_bin(cohort_biomarker)['bin'], 2)
        cohort_intervention = proposal('7', target_id='compound:creatine-monohydrate', entity_type='intervention', abstract='In a cohort of athletes, creatine use was recorded.')
        self.assertEqual(assign_bin(cohort_intervention)['bin'], 3)

    def test_flagship_safety_content_is_priority_even_without_design(self):
        p = proposal('8', target_id='compound:creatine-monohydrate', entity_type='intervention', title='Adverse events reported with creatine')
        self.assertEqual(assign_bin(p)['bin'], 2)

    def test_registrations_and_out_of_scope_records(self):
        reg = proposal('9', target_id='entity:psa-screening', entity_type='screening', nct_id='NCT01234567', publication_types=['Trial registration'])
        self.assertEqual(assign_bin(reg)['bin'], 3)
        other = proposal('10', target_id='compound:bpc-157', entity_type='intervention', publication_types=['Randomized Controlled Trial'])
        self.assertEqual(assign_bin(other)['bin'], 4)

    def test_queue_order_prefers_lower_bin_then_impact_and_age(self):
        now = datetime(2026, 9, 14, tzinfo=timezone.utc)
        integrity = proposal('11', target_id='compound:bpc-157', entity_type='intervention', title='Expression of concern: peptide study')
        old_out_of_scope = proposal('12', target_id='compound:bpc-157', entity_type='intervention', created='2025-01-01T00:00:00+00:00')
        flagship = proposal('13', target_id='compound:creatine-monohydrate', entity_type='intervention', publication_types=['Meta-Analysis'])
        ordered = sorted([old_out_of_scope, flagship, integrity], key=lambda p: queue_sort_key(p, now))
        self.assertEqual([p['id'] for p in ordered], ['11', '13', '12'])


class TriageBacklogTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(':memory:')
        rows = [
            proposal('20', target_id='compound:creatine-monohydrate', entity_type='intervention', publication_types=['Randomized Controlled Trial']),
            proposal('21', target_id='compound:bpc-157', entity_type='intervention'),
            proposal('22', target_id='compound:bpc-157', entity_type='intervention', status='review_ready'),
            proposal('23', target_id='compound:bpc-157', entity_type='intervention', status='approved'),
            proposal('24', target_id='compound:bpc-157', entity_type='intervention', title='Retraction: peptide study'),
        ]
        for row in rows:
            self.store.put('proposal', row['id'], row)

    def tearDown(self):
        self.store.close()

    def test_report_is_read_only(self):
        report = triage_backlog(self.store)
        self.assertEqual(report['pending'], 4)
        self.assertEqual(report['bins'], {'integrity': 1, 'flagship_priority': 1, 'flagship_other': 0, 'out_of_scope': 2})
        self.assertFalse(any('queue' in p for p in self.store.all('proposal')))
        self.assertEqual(self.store.all('audit'), [])

    def test_apply_labels_without_changing_status(self):
        triage_backlog(self.store, apply=True)
        by_id = {p['id']: p for p in self.store.all('proposal')}
        self.assertEqual(by_id['20']['queue']['label'], 'flagship_priority')
        self.assertEqual(by_id['21']['status'], 'awaiting_extraction')
        self.assertNotIn('queue', by_id['23'], 'approved proposals are not re-triaged')
        self.assertEqual(len(self.store.all('audit')), 1)

    def test_deferral_requires_reviewer_and_note(self):
        with self.assertRaises(ValueError):
            triage_backlog(self.store, apply=True, defer=True)
        with self.assertRaises(ValueError):
            triage_backlog(self.store, defer=True, actor='A. Reviewer', note='scope')

    def test_defer_only_out_of_scope_and_restore(self):
        report = triage_backlog(self.store, apply=True, defer=True, actor='A. Reviewer', note='Outside Phase 1 flagship scope; retained.')
        self.assertEqual(report['deferred'], 2)
        by_id = {p['id']: p for p in self.store.all('proposal')}
        self.assertEqual((by_id['21']['status'], by_id['22']['status']), ('deferred', 'deferred'))
        self.assertEqual(by_id['24']['status'], 'awaiting_extraction', 'integrity items are never deferred')
        # Still pending: the integrity item and the approved proposal awaiting publication.
        self.assertEqual(self.store.pending_count('compound:bpc-157'), 2)
        self.assertEqual(self.store.deferred_count('compound:bpc-157'), 2)
        result = restore_deferred(self.store, 'A. Reviewer', 'Flagship scope expanded.', target_id='compound:bpc-157')
        self.assertEqual(result['restored'], 2)
        by_id = {p['id']: p for p in self.store.all('proposal')}
        self.assertEqual((by_id['21']['status'], by_id['22']['status']), ('awaiting_extraction', 'review_ready'))
        self.assertEqual(by_id['22']['deferral_history'][0]['restored_by'], 'A. Reviewer')
        self.assertEqual(self.store.deferred_count('compound:bpc-157'), 0)

    def test_apply_waits_for_running_monitor(self):
        self.assertTrue(self.store.acquire('monitor-run'))
        with self.assertRaises(RuntimeError):
            triage_backlog(self.store, apply=True)
        report = triage_backlog(self.store)
        self.assertEqual(report['pending'], 4, 'read-only report does not need the lease')

    def test_summary_ranks_targets(self):
        summary = summarize(triage_backlog(self.store), top=1)
        self.assertEqual(list(summary['top_targets']), ['compound:bpc-157'])
        self.assertEqual(summary['targets_with_pending'], 2)
        self.assertEqual(set(summary['bins']), set(BIN_LABELS.values()))


if __name__ == '__main__':
    unittest.main()
