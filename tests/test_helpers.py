import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_source import prepare
from finalize_coverage import finalize


class HelpersTest(unittest.TestCase):
    def setUp(self):
        target = ROOT / 'work' / 'test-runs'
        target.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix='case-', dir=target))

    def put(self, name, content):
        p = self.folder / name
        p.write_text(content, encoding='utf-8')
        return p

    def test_full_html_and_multiple_chunks(self):
        chunks = [
            [{'id': 'm1', 'text': '预览…', 'html': '<p>计划办工作坊，但必须等场地确认。</p><blockquote>转发：旧方案已取消。</blockquote><img src="resources/a.png">'}],
            [{'id': 'm2', 'html': '<p>第二条完整内容</p><script>never execute</script>'}],
        ]
        raw = '\n'.join('<script>window.__QCE_CHUNK__ && window.__QCE_CHUNK__({id:"c' + str(i) + '",messages:' + json.dumps(c, ensure_ascii=False) + '});</script>' for i, c in enumerate(chunks))
        doc = prepare(self.put('sample.html', raw))
        self.assertEqual(doc['unit_count'], 2)
        self.assertIn('必须等场地确认', doc['units'][0]['text'])
        self.assertIn('旧方案已取消', doc['units'][0]['text'])
        self.assertIn('resources/a.png', doc['units'][0]['resources'])
        self.assertNotIn('never execute', doc['units'][1]['text'])

    def test_unknown_html_is_not_empty_success(self):
        with self.assertRaises(ValueError):
            prepare(self.put('external.html', '<html><script src="messages.js"></script></html>'))

    def test_manifest_catches_missing_chunks_and_count_mismatch(self):
        embedded = 'window.__QCE_CHUNK__({id:"a",messages:[{"id":"x","text":"kept"}]});'
        for manifest in ({'stats': {'totalMessages': 2}}, {'chunks': [{'id': 'a', 'count': 1}, {'id': 'b', 'count': 1}]}, {'chunks': [{'id': 'a', 'count': 2}]}):
            with self.assertRaises(ValueError):
                prepare(self.put('incomplete.html', embedded + 'window.__QCE_MANIFEST__(' + json.dumps(manifest) + ');'))
        valid = {'stats': {'totalMessages': 1}, 'chunks': [{'id': 'a', 'count': 1}]}
        self.assertEqual(prepare(self.put('complete.html', embedded + 'window.__QCE_MANIFEST__(' + json.dumps(valid) + ');'))['unit_count'], 1)

    def test_duplicate_id_fails(self):
        with self.assertRaises(ValueError):
            prepare(self.put('duplicate.json', json.dumps([{'id': 'x', 'text': 'one'}, {'id': 'x', 'text': 'two'}])))

    def test_paragraphs_preserve_conditions(self):
        d = prepare(self.put('input.md', '计划A\n但要等确认。\n\n想法B暂不执行。'))
        self.assertEqual(len(d['units']), 2)
        self.assertEqual(d['units'][0]['text'], '计划A\n但要等确认。')

    def test_unmapped_and_false_evidence_are_preserved(self):
        source = {'units': [{'id': 'a', 'text': '先准备三组素材'}, {'id': 'b', 'text': '办展但预算未定'}, {'id': 'c', 'text': '旧磁带与空镜对照'}, {'id': 'd', 'text': '收到'}]}
        coverage = {'a': {'status': 'body', 'evidence': '先准备三组素材'}, 'b': {'status': 'body', 'evidence': '文中没有这句话'}, 'd': {'status': 'excluded', 'reason': '无新增信息的确认'}}
        output, report = finalize(source, '# 计划\n先准备三组素材', coverage)
        self.assertIn('办展但预算未定', output)
        self.assertIn('旧磁带与空镜对照', output)
        self.assertEqual(report['appended_units'], 2)
        self.assertFalse(report['semantic_completeness_verified'])
        self.assertEqual(output.count('先准备三组素材'), 1)

    def test_unknown_and_unjustified_exclusions_fail(self):
        source = {'units': [{'id': 'a', 'text': 'important'}]}
        for coverage in ({'unknown': {'status': 'body'}}, {'a': {'status': 'excluded', 'reason': ''}}, {'a': {'status': 'whatever'}}):
            with self.assertRaises(ValueError):
                finalize(source, '', coverage)

    def test_cli_never_overwrites_source(self):
        src = self.put('notes.md', '原文不可覆盖')
        before = src.read_bytes()
        r = subprocess.run([sys.executable, str(ROOT / 'scripts/prepare_source.py'), str(src), '--output', str(src)], capture_output=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(src.read_bytes(), before)

    def test_finalizer_refuses_existing_output(self):
        src = self.put('source.json', '{"units":[{"id":"x","text":"hello"}]}')
        draft = self.put('draft.md', 'draft')
        coverage = self.put('coverage.json', '{}')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/finalize_coverage.py'), str(src), str(draft), str(coverage), '--output', str(draft), '--report', str(self.folder/'report.json')], capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(draft.read_text(encoding='utf-8'), 'draft')
        self.assertFalse((self.folder/'report.json').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
