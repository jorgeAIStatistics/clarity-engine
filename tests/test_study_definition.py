import unittest
from unittest.mock import patch
from flask import Flask
from evidence.routes import blueprint
from evidence.study_definition import draft,known_sources,clean,identity,extract

class StudyDefinitionTests(unittest.TestCase):
    def test_il18_identifiers_and_exact_title_resolve_same_source(self):
        r=known_sources()[0]
        for text in ['41976322','PMID: 41976322','https://pubmed.ncbi.nlm.nih.gov/41976322/','10.3390/cancers18071100',r['title'],'Title:\n'+r['title']+'\n\nPMID:\n41976322\n\nDOI:\n10.3390/cancers18071100']:
            with self.subTest(text=text):
                x=draft(text);self.assertEqual(x['paper']['pmid'],'41976322');self.assertTrue(x['paper']['full_text_used']);self.assertTrue(x['requires_confirmation'])
    def test_exact_abstract_gets_full_text_supported_definition(self):
        r=known_sources()[0];x=draft(clean(r['abstractText']));d=x['definition']
        for key,term in {'design':'prospective cohort','population':'stage 0–III breast cancer','species':'human','exposure':'pre-radiotherapy plasma IL-18','exposure_assay':'Ella SimplePlex','outcome':'radiotherapy-related pain','outcome_definition':'<4 pre-RT','instrument':'Brief Pain Inventory','secondary':'post-RT','metric':'adjusted odds ratio','method':'logistic regression','modifier':'BMI','timepoint':'post-radiotherapy'}.items():self.assertIn(term,d[key])
        self.assertEqual(x['provenance']['population']['origin'],'source_full_text_methods')
        for field,provenance in x['provenance'].items():
            text=clean(r['abstractText']) if provenance['origin']=='source_abstract' else clean('\n'.join(r['methods_paragraphs']))
            self.assertIn(provenance['quote'],text,field)
    def test_free_text_has_no_external_search_and_no_false_success(self):
        with patch('evidence.study_definition.resolve_remote') as remote:
            x=draft('My research is about an idea that I have not defined yet.');self.assertEqual(x['status'],'needs_input');remote.assert_not_called()
    def test_explicit_user_fields_remain_distinct_from_source(self):
        x=draft('PMID: 41976322\noutcome: post-RT pain')
        self.assertEqual(x['definition']['outcome'],'post-RT pain');self.assertEqual(x['provenance']['outcome']['origin'],'user_text');self.assertIn('outcome',x['conflicts'])
    def test_sparse_text_does_not_borrow_known_paper_fields(self):
        x=draft('Our study examines plasma IL-18 for inflammation in adults.');self.assertIsNone(x['paper']);self.assertNotIn('instrument',x['definition']);self.assertNotIn('design',x['definition'])
    def test_source_outage_preserves_explicit_user_text(self):
        import requests
        with patch('evidence.study_definition.resolve_remote',side_effect=requests.Timeout):
            x=draft('PMID: 12345678\nexposure: ApoB\noutcome: cardiovascular events');self.assertEqual(x['definition']['exposure'],'ApoB');self.assertTrue(x['warnings'])
    def test_endpoint_bounds_and_patient_guard_before_resolution(self):
        app=Flask(__name__);app.register_blueprint(blueprint);client=app.test_client()
        with patch('evidence.study_definition.resolve_remote') as remote:
            for body in [{'text':'x'*12001},{'text':'patient_id: 12345\nPMID: 12345678'},{'text':42},{'text':'test','url':'https://example.com'}]:self.assertEqual(client.post('/api/research/definition',json=body).status_code,400)
            remote.assert_not_called()
        response=client.post('/api/research/definition',json={'text':'41976322'});self.assertEqual(response.status_code,200);self.assertEqual(response.headers['Cache-Control'],'no-store')
    def test_generic_design_and_question_patterns(self):
        d,_=extract('Our study examines creatine for muscle strength in adults. It is a randomized controlled trial compared with placebo.')
        self.assertEqual(d['exposure'],'creatine');self.assertEqual(d['comparator'],'placebo');self.assertEqual(d['design'],'randomized controlled trial')

    def test_free_research_questions_are_not_misidentified_as_article_titles(self):
        with patch('evidence.study_definition.resolve_remote') as remote:
            draft('Does ApoB predict cardiovascular events in older adults with diabetes?')
            remote.assert_not_called()
    def test_pubmed_reference_identifiers_cannot_replace_article_identifiers(self):
        from evidence.study_definition import resolve_remote
        xml='<PubmedArticleSet><PubmedArticle><MedlineCitation><PMID>12345678</PMID><Article><ArticleTitle>Test paper</ArticleTitle><Abstract><AbstractText>Our study examines ApoB for events in adults.</AbstractText></Abstract></Article></MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10.1000/original</ArticleId></ArticleIdList><ReferenceList><Reference><ArticleIdList><ArticleId IdType="doi">10.1000/reference</ArticleId></ArticleIdList></Reference></ReferenceList></PubmedData></PubmedArticle></PubmedArticleSet>'
        with patch('evidence.study_definition.get',return_value=xml),patch('pubmed._throttle'):
            r,_=resolve_remote.__wrapped__('pmid','12345678',0)
        self.assertEqual(r['doi'],'10.1000/original')
