import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

spec = importlib.util.spec_from_file_location(
    'collector', Path(__file__).resolve().parents[1] / 'scripts' / 'collect.py')
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / 'repo'
        self.repo.mkdir()
        self.git('init', '-b', 'base')
        self.git('config', 'user.name', 'Audit Test')
        self.git('config', 'user.email', 'audit@example.invalid')
        self.write('base.txt', 'baseline\n')
        self.commit('baseline')

    def git(self, *args):
        env = dict(os.environ, GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.check_output(['git', '-C', str(self.repo), *args],
                                       env=env, stderr=subprocess.PIPE).decode().strip()

    def write(self, name, content):
        (self.repo / name).write_text(content)

    def commit(self, message):
        self.git('add', '.')
        self.git('commit', '-m', message)
        return self.git('rev-parse', 'HEAD')

    def audit(self):
        before = self.git('status', '--porcelain=v1', '--branch')
        result = collector.collect(self.repo, 'old', 'new', self.root / 'evidence')
        self.assertEqual(before, self.git('status', '--porcelain=v1', '--branch'))
        self.assertEqual(result['assessment'], 'review_required')
        return result

    def test_missing_commit(self):
        self.git('switch', '-c', 'old')
        self.write('feature.py', 'enabled = True\n')
        old = self.commit('feature')
        self.git('branch', 'new', 'base')
        result = self.audit()
        self.assertEqual([c['sha'] for c in result['old_only_commits']], [old])
        self.assertEqual(result['tip_changes'], [{'status': 'D', 'paths': ['feature.py']}])

    def test_ancestor_followed_by_revert(self):
        self.git('switch', '-c', 'old')
        self.write('feature.py', 'enabled = True\n')
        old = self.commit('feature')
        self.git('switch', '-c', 'new')
        self.git('revert', '--no-edit', old)
        result = self.audit()
        self.assertTrue(result['old_is_ancestor'])
        self.assertEqual(result['old_only_commits'], [])
        self.assertEqual(result['tip_changes'][0]['status'], 'D')
        self.assertIn('deleted file mode', (self.root / 'evidence/old-to-new.patch').read_text())

    def test_cherry_pick_different_sha(self):
        self.git('switch', '-c', 'old')
        self.write('feature.py', 'enabled = True\n')
        old = self.commit('feature')
        self.git('switch', '-c', 'new', 'base')
        self.write('other.txt', 'target-only\n')
        self.commit('other')
        self.git('cherry-pick', old)
        result = self.audit()
        self.assertEqual(len(result['old_only_commits']), 1)
        self.assertTrue((self.root / 'evidence/cherry.txt').read_text().startswith('- '))
        self.assertEqual(result['tip_changes'], [{'status': 'A', 'paths': ['other.txt']}])

    def test_squash_has_equal_trees_and_candidates(self):
        self.git('switch', '-c', 'old')
        self.write('one.txt', 'one\n')
        self.commit('one')
        self.write('two.txt', 'two\n')
        self.commit('two')
        self.git('switch', '-c', 'new', 'base')
        self.git('merge', '--squash', 'old')
        self.commit('squashed')
        result = self.audit()
        self.assertEqual(len(result['old_only_commits']), 2)
        self.assertEqual(result['tip_changes'], [])
        self.assertEqual(len((self.root / 'evidence/cherry.txt').read_text().splitlines()), 2)

    def test_merge_commits_are_included(self):
        self.git('switch', '-c', 'side')
        self.write('side.txt', 'side\n')
        self.commit('side')
        self.git('switch', '-c', 'old', 'base')
        self.git('merge', '--no-ff', '-m', 'merge side', 'side')
        self.git('branch', 'new', 'base')
        result = self.audit()
        self.assertEqual(len(result['old_only_commits']), 2)
        self.assertEqual(len(result['old_only_commits'][-1]['parents']), 2)

    def test_rename_with_unusual_filename(self):
        self.git('branch', 'old')
        self.git('switch', '-c', 'new')
        name = '中文\tname\n.txt'
        self.git('mv', 'base.txt', name)
        self.commit('rename')
        self.assertEqual(self.audit()['tip_changes'],
                         [{'status': 'R100', 'paths': ['base.txt', name]}])

    def test_invalid_ref_does_not_emit_success_summary(self):
        with self.assertRaises(RuntimeError):
            collector.collect(self.repo, 'missing', 'base', self.root / 'evidence')
        self.assertFalse((self.root / 'evidence/summary.json').exists())

    def test_refuse_output_in_checkout(self):
        with self.assertRaises(ValueError):
            collector.collect(self.repo, 'base', 'base', self.repo / 'evidence')
        self.assertFalse((self.repo / 'evidence').exists())


if __name__ == '__main__':
    unittest.main()
