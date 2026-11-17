"""Profile refresh uses one cluster snapshot and reports local write failures."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard' / 'backend'))
import app
import builder


CONFIG = '''
apiVersion: llm-d.ai/v1
plugins:
  - name: queue
    type: queue-scorer
  - name: active
    type: active-request-scorer
  - name: picker
    type: max-score-picker
schedulingProfiles:
  - name: mixed
    plugins:
      - pluginRef: queue
        weight: 2
      - pluginRef: active
        weight: 1
      - pluginRef: picker
'''


def snapshot(text=CONFIG):
    return {'text': text, 'configmap': {'metadata': {'resourceVersion': '42'}}, 'configmap_name': 'epp-config',
            'config_key': 'epp.yaml', 'resource_version': '42'}


class ProfileRefreshTests(unittest.TestCase):
    def setUp(self):
        self.request = builder.SyncMapRequest(namespace='test', epp_deployment='epp', epp_container='epp')

    def test_one_snapshot_produces_both_views_and_the_saved_map(self):
        with tempfile.TemporaryDirectory() as directory:
            map_file = Path(directory) / 'profiles.json'
            with patch.object(app.cluster, 'fetch_config', return_value=snapshot()) as fetch, \
                 patch.object(builder, 'SCRIPT_MAP_LOCAL', map_file):
                result = app.refresh_profiles(self.request)
            fetch.assert_called_once()
            saved = json.loads(map_file.read_text())
        self.assertEqual(result['profiles']['resource_version'], '42')
        self.assertEqual(result['builder']['resource_version'], '42')
        self.assertEqual(result['profiles']['profiles'][0]['scorers'][0]['weight'], 2)
        self.assertEqual(saved['profiles'], {'mixed': 'queue-scorer (2) + active-request-scorer (1)'})
        self.assertIn('resourceVersion 42', saved['source'])
        self.assertTrue(result['sync']['ok'])

    def test_save_failure_keeps_loaded_profiles_and_reports_warning(self):
        with patch.object(app.cluster, 'fetch_config', return_value=snapshot()), \
             patch.object(builder, 'sync_profile_map', side_effect=OSError('disk full')):
            result = app.refresh_profiles(self.request)
        self.assertEqual(result['profiles']['profiles'][0]['name'], 'mixed')
        self.assertEqual(result['builder']['profiles'][0]['name'], 'mixed')
        self.assertFalse(result['sync']['ok'])
        self.assertIn('disk full', result['sync']['error'])

    def test_implicit_default_profile_is_in_both_list_and_map(self):
        implicit = CONFIG.split('schedulingProfiles:')[0]
        with tempfile.TemporaryDirectory() as directory:
            map_file = Path(directory) / 'profiles.json'
            with patch.object(app.cluster, 'fetch_config', return_value=snapshot(implicit)), \
                 patch.object(builder, 'SCRIPT_MAP_LOCAL', map_file):
                result = app.refresh_profiles(self.request)
            saved = json.loads(map_file.read_text())
        self.assertEqual(result['profiles']['profiles'][0]['name'], 'default')
        self.assertEqual(saved['profiles'], {'default': 'queue-scorer (1) + active-request-scorer (1)'})


if __name__ == '__main__':
    unittest.main()
