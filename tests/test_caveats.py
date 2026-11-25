"""Scorer warnings remain informative without claiming deployment health."""

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

    def test_missing_or_unavailable_predictor_containers_warn(self):
        for cluster in (None, deployment('epp')):
            with self.subTest(cluster=cluster):
                result = caveats.evaluate_scorer(self.latency, '/v1/audio/speech', cluster)
                self.assertEqual(result['severity'], 'warning')
                self.assertTrue(any('predictor' in reason.lower() for reason in result['reasons']))

    def test_predictor_containers_do_not_prove_health_or_training(self):
        result = caveats.evaluate_scorer(self.latency, '/v1/chat/completions', deployment(
            'llm-d-latency-predictor-training-server',
            'llm-d-latency-predictor-prediction-server',
        ))
        self.assertEqual(result['severity'], 'warning')
        self.assertTrue(any('trained' in reason for reason in result['reasons']))

    def test_mixed_profile_names_only_scorers_that_need_attention(self):
        result = caveats.evaluate_types(
            ['queue-scorer', 'mm-embeddings-cache-scorer'],
            '/v1/images/generations', self.data, deployment('epp'),
        )
        self.assertEqual(result['severity'], 'warning')
        self.assertEqual(len(result['reasons']), 1)
        self.assertIn('mm-embeddings-cache-scorer', result['reasons'][0])
        self.assertIn('no input media', result['reasons'][0])
        self.assertTrue(result['details'])

    def test_token_load_has_short_message_and_version_details(self):
        result = caveats.evaluate_types(['token-load-scorer'], '/v1/audio/speech', self.data, None)
        self.assertEqual(result['severity'], 'warning')
        self.assertTrue(any('first response' in reason for reason in result['reasons']))
        self.assertTrue(any('v1.0.0' in detail for detail in result['details']))

    def test_no_warning_does_not_add_unrelated_reasons(self):
        result = caveats.evaluate_types(['queue-scorer'], '/v1/audio/speech', self.data, None)
        self.assertEqual(result['severity'], 'ok')
        self.assertEqual(result['reasons'], [])
        self.assertEqual(result['details'], [])

    def test_builder_deduplicates_summaries_but_keeps_endpoint_details(self):
        result = caveats.evaluate_scorer_across_endpoints(
            self.data['scorers']['mm-embeddings-cache-scorer'],
            ['/v1/chat/completions', '/v1/audio/speech'], None,
        )
        self.assertEqual(result['severity'], 'warning')
        self.assertEqual(len(result['reasons']), 1)
        self.assertEqual(len(result['details']), 2)

    def test_data_covers_only_warning_status_with_concise_messages(self):
        for scorer in self.data['scorers'].values():
            for item in scorer['caveats']:
                self.assertEqual(item['status'], 'warning')
                self.assertLess(len(item['reason']), 160)
                self.assertTrue(item['details'])


if __name__ == '__main__':
    unittest.main()
