"""The shared layer rule table must reproduce the previous classifier on every stored record."""
import json
import re
import unittest
from pathlib import Path
from evidence.profile import LAYER_RULES, layer_for

ROOT = Path(__file__).resolve().parent.parent


def legacy_layer_for(study):
    """Verbatim copy of evidence/profile.py::layer_for as of engine 2026.09-launch.2."""
    design = str(study.get('design') or study.get('study_type') or '').lower()
    population = str(study.get('population') or '').lower()
    if study.get('is_protocol') or re.search(r'\b(?:study protocol|trial protocol|protocol for (?:a|an|the) .{0,40}trial)\b', str(study.get('title', '')).lower()) or 'protocol' in design: return 'protocol'
    if re.search(r'guideline|practice recommendation|regulatory', design): return 'guidelines'
    if re.search(r'animal|mouse|mice|rat\b|preclinical', population) or 'animal' in design: return 'preclinical'
    if re.search(r'in.?vitro|cell[- ](?:line|culture|based)|mechanis', population + ' ' + design): return 'mechanism'
    if re.search(r'meta.analysis|systematic review', design): return 'synthesis'
    if 'human' not in population: return 'unclassified'
    if re.search(r'random|rct|clinical trial|intervention', design): return 'interventional'
    if re.search(r'observ|cohort|case.control|cross.section', design): return 'observational'
    return 'unclassified'


class LayerRuleTests(unittest.TestCase):
    def test_shared_cases(self):
        for case in LAYER_RULES['cases']:
            self.assertEqual(layer_for(case['study']), case['layer'], case)
            self.assertEqual(legacy_layer_for(case['study']), case['layer'], case)

    def test_matches_legacy_classifier_on_all_stored_records(self):
        seen = 0
        for path in (ROOT / 'cache').glob('*.json'):
            profile = json.loads(path.read_text())
            if not isinstance(profile, dict):
                continue
            for claim in profile.get('claims') or []:
                for study in claim.get('studies') or []:
                    seen += 1
                    self.assertEqual(layer_for(study), legacy_layer_for(study), (path.name, study.get('id')))
        catalog = json.loads((ROOT / 'evidence' / 'catalog.json').read_text())
        for entity in catalog['entities']:
            for study in entity['studies']:
                seen += 1
                self.assertEqual(layer_for(study), legacy_layer_for(study), study.get('id'))
        self.assertGreater(seen, 8000)

    def test_frontend_export_is_current(self):
        exported = ROOT.parent / 'clarity-web' / 'src' / 'platform' / 'layers.generated.js'
        if not exported.exists():
            self.skipTest('clarity-web checkout is not adjacent to clarity-engine')
        from evidence.export_layers import render
        self.assertEqual(exported.read_text(), render(), 'Run: python3 -m evidence.export_layers ../clarity-web/src/platform/layers.generated.js')


if __name__ == '__main__':
    unittest.main()
