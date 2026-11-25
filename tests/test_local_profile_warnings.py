"""Local warnings use the visible profiles without needing a cluster."""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard' / 'backend'))
import app


class LocalWarningsTests(unittest.TestCase):
    def test_mixed_profile_descriptions_work_without_cluster_access(self):
        request = app.LocalProfileCheckRequest(endpoint='/v1/audio/speech', profiles={
            'mixed': ['queue-scorer (2) + token-load-scorer (1)'],
            'baseline': ['queue-scorer'],
        })
        with patch.object(app.cluster, 'fetch_config', side_effect=AssertionError('cluster called')):
            result = app.profiles_check_local(request)
        self.assertEqual(result['cluster_access'], 'not_checked')
        self.assertEqual(result['profiles']['mixed']['severity'], 'warning')
        self.assertIn('token-load-scorer', result['profiles']['mixed']['scorer_types'])
        self.assertEqual(result['profiles']['baseline']['severity'], 'ok')

    def test_frontend_index_is_revalidated_on_reload(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'index.html').write_text('dashboard')
            with patch.object(app, 'FRONTEND_DIST', root), patch.object(app, 'FRONTEND_ROOT', root):
                self.assertEqual(app.spa('').headers['cache-control'], 'no-cache')
                self.assertEqual(app.spa('index.html').headers['cache-control'], 'no-cache')


if __name__ == '__main__':
    unittest.main()
