import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest
from unittest.mock import patch

WORKFLOW = (Path(__file__).resolve().parents[1] / 'workflows/verify-v044-topics.yml').read_text()
GUARD = textwrap.dedent(WORKFLOW.split("python3 - <<'PY_GUARD'\n", 1)[1].split('          PY_GUARD', 1)[0])
REPO = 'repos/daiksud/test-gh-settings-public'
ENVIRONMENT = REPO + '/environments/gh-settings-probe'
SOURCE = 'a' * 40

class GuardTests(unittest.TestCase):
    def fixture(self):
        return {
            REPO: {'id': 1444211116, 'full_name': 'daiksud/test-gh-settings-public',
                   'private': False, 'archived': False, 'default_branch': 'main',
                   'owner': {'id': 155234749, 'type': 'User'}},
            REPO + '/git/ref/heads/main': {'object': {'sha': SOURCE}},
            ENVIRONMENT: {'name': 'gh-settings-probe', 'id': 123,
                          'can_admins_bypass': False,
                          'deployment_branch_policy': {'protected_branches': False,
                                                       'custom_branch_policies': True},
                          'protection_rules': [{'type': 'branch_policy'},
                              {'type': 'required_reviewers', 'prevent_self_review': False,
                               'reviewers': [{'type': 'User', 'reviewer': {'id': 155234749}}]}]},
            ENVIRONMENT + '/deployment-branch-policies?per_page=100': {
                'total_count': 1, 'branch_policies': [{'type': 'branch', 'name': 'main'}]},
        }

    def evaluate(self, data, valid):
        calls = []
        def invoke(args, **kwargs):
            calls.append(args)
            self.assertEqual(args[:4], ['gh', 'api', '--hostname', 'github.com'])
            self.assertEqual(len(args), 5)  # No mutating method or body accepted.
            payload = data.get(args[4])
            return subprocess.CompletedProcess(args, 0 if payload is not None else 1,
                                               json.dumps(payload), '')
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / 'output'
            with patch.dict(os.environ, {'EXPECTED_SOURCE': SOURCE, 'GITHUB_OUTPUT': str(output)}), \
                 patch('subprocess.run', side_effect=invoke), contextlib.redirect_stdout(io.StringIO()):
                if valid:
                    exec(compile(GUARD, 'preflight_guard.py', 'exec'), {})
                    self.assertEqual(output.read_text(), 'environment-id=123\n')
                else:
                    with self.assertRaises((AssertionError, SystemExit)):
                        exec(compile(GUARD, 'preflight_guard.py', 'exec'), {})
                    self.assertFalse(output.exists())
        return calls

    def test_existing_protected_environment_succeeds(self):
        self.assertEqual(len(self.evaluate(self.fixture(), True)), 4)

    def test_missing_environment_stops_without_output(self):
        data = self.fixture()
        del data[ENVIRONMENT]
        self.evaluate(data, False)

    def test_unsafe_target_and_moved_main_stop(self):
        changes = [('private', True), ('archived', True), ('id', 1), ('default_branch', 'other')]
        for name, value in changes:
            with self.subTest(name=name):
                data = self.fixture()
                data[REPO][name] = value
                self.evaluate(data, False)
        data = self.fixture()
        data[REPO + '/git/ref/heads/main']['object']['sha'] = 'b' * 40
        self.evaluate(data, False)

    def test_missing_approval_and_bypass_stop(self):
        for change in ({'protection_rules': []}, {'can_admins_bypass': True},
                       {'deployment_branch_policy': None}, {'id': 0}):
            with self.subTest(change=change):
                data = self.fixture()
                data[ENVIRONMENT].update(copy.deepcopy(change))
                self.evaluate(data, False)

    def test_unexpected_reviewer_and_unknown_rules_stop(self):
        data = self.fixture()
        data[ENVIRONMENT]['protection_rules'][1]['reviewers'][0]['reviewer']['id'] = 1
        self.evaluate(data, False)
        data = self.fixture()
        data[ENVIRONMENT]['protection_rules'].append({'type': 'unknown'})
        self.evaluate(data, False)

    def test_tag_wildcard_and_extra_branches_stop(self):
        key = ENVIRONMENT + '/deployment-branch-policies?per_page=100'
        for change in ({'type': 'tag', 'name': 'main'}, {'type': 'branch', 'name': '*'}):
            with self.subTest(change=change):
                data = self.fixture()
                data[key]['branch_policies'] = [change]
                self.evaluate(data, False)
        data = self.fixture()
        data[key]['total_count'] = 2
        self.evaluate(data, False)

if __name__ == '__main__':
    unittest.main()
