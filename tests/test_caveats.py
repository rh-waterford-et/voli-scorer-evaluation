"""Caveat behavior for version-dependent scoring and predictor deployments."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard' / 'backend'))
import caveats


def deployment(*images):
    return {'spec': {'template': {'spec': {'containers': [
        {'name': f'container-{i}', 'image': image} for i, image in enumerate(images)
    ]}}}}


class CaveatTests(unittest.TestCase):
    def setUp(self):
        self.data = caveats.load_caveats()
        self.latency = self.data['scorers']['latency-scorer']

    def test_missing_predictor_sidecars_do_not_claim_external_services_are_broken(self):
        result = caveats.evaluate_scorer(self.latency, '/v1/audio/speech', deployment('epp'))
        self.assertEqual(result['severity'], 'unknown')
        self.assertTrue(any('services' in reason for reason in result['reasons']))

    def test_present_sidecars_do_not_prove_predictor_health(self):
        result = caveats.evaluate_scorer(self.latency, '/v1/chat/completions', deployment(
            'llm-d-latency-predictor-training-server',
            'llm-d-latency-predictor-prediction-server',
        ))
        self.assertEqual(result['severity'], 'unknown')
        self.assertTrue(any('readiness' in reason or 'health' in reason for reason in result['reasons']))

    def test_unavailable_cluster_reports_unknown(self):
        result = caveats.evaluate_scorer(self.latency, '/v1/audio/speech', None)
        self.assertEqual(result['severity'], 'unknown')
        self.assertTrue(any('cluster state unavailable' in reason for reason in result['reasons']))

    def test_unqualified_requirements_remain_blocking(self):
        entry = {'requirements': [{'components': [{'name': 'required', 'match': 'needed'}]}]}
        self.assertEqual(caveats.evaluate_scorer(entry, '/any', deployment('epp'))['severity'], 'bad')

    def test_old_tts_gap_is_qualified_and_structural_no_media_is_blocking(self):
        token = caveats.evaluate_types(['token-load-scorer'], '/v1/audio/speech', self.data, None)
        self.assertEqual(token['severity'], 'unknown')
        self.assertIn('v1.0.0', token['reasons'][0])
        mm = caveats.evaluate_types(['mm-embeddings-cache-scorer'], '/v1/embeddings', self.data, None)
        self.assertEqual(mm['severity'], 'bad')

    def test_general_scorer_design_does_not_trigger_caveats(self):
        scorers = ['active-request-scorer', 'queue-scorer', 'load-aware-scorer',
                   'running-requests-size-scorer', 'kv-cache-utilization-scorer',
                   'endpoint-attribute-weight-scorer']
        endpoints = ['/v1/chat/completions', '/v1/audio/speech', '/v1/embeddings',
                     '/v1/images/generations', '/v1/images/edits', '/v1/audio/transcriptions']
        for scorer in scorers:
            for endpoint in endpoints:
                with self.subTest(scorer=scorer, endpoint=endpoint):
                    result = caveats.evaluate_types([scorer], endpoint, self.data, None)
                    self.assertEqual(result['severity'], 'ok')
                    self.assertEqual(result['reasons'], [])

    def test_unverified_no_hit_lru_prerequisites_are_unknown(self):
        result = caveats.evaluate_types(['no-hit-lru-scorer'], '/v1/audio/speech', self.data, None)
        self.assertEqual(result['severity'], 'unknown')
        self.assertIn('treated as cold', result['reasons'][0])

    def test_combined_profile_inherits_worst_applicable_caveat(self):
        result = caveats.evaluate_types(
            ['no-hit-lru-scorer', 'mm-embeddings-cache-scorer'],
            '/v1/images/generations', self.data, deployment('epp'),
        )
        self.assertEqual(result['severity'], 'bad')
        self.assertEqual(len(result['reasons']), 2)


if __name__ == '__main__':
    unittest.main()
