#!/usr/bin/env python3
"""Portable, isolated hook tests. No real engine discovery or user data access."""
import json
import os
import re
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'sk-' + 'q7xkwm2vbnr8tzc41p9e'


def allowed_process(executable, argv, expected_argv, windows):
    """Match only the complete expected invocation, including all arguments.

    CPython's Windows audit event receives executable=None and the already
    list2cmdline-encoded string; POSIX receives an executable and an argv list.
    """
    if executable != expected_argv[0] and not (windows and executable is None):
        return False
    if isinstance(argv, (list, tuple)):
        return list(argv) == expected_argv
    return windows and isinstance(argv, str) and argv == subprocess.list2cmdline(expected_argv)


# Run the unmodified hook with a subprocess allowlist. A failure cannot silently
# fall through to a real rsrs executable, even on machines where one is installed.
# TEST_EXPECTED_ARGV is an ORDERED SEQUENCE of argv lists: every subprocess must
# match the next expected invocation exactly (store now legitimately chains
# remember -> show read-back / remember -> list verification).
LAUNCHER = r'''
import json, os, pathlib, runpy, sys
case = pathlib.Path(os.environ['RESPITE_CONFIG']).resolve().parent
expected = os.environ['TEST_ENGINE']
expected_argv = json.loads(os.environ['TEST_EXPECTED_ARGV'])
assert isinstance(expected_argv, list) and expected_argv
for argv in expected_argv:
    assert isinstance(argv, list) and argv[0] == expected
config = json.loads(pathlib.Path(os.environ['RESPITE_CONFIG']).read_text(encoding="utf-8"))
assert config['rsrs'] == expected and os.access(expected, os.X_OK)
sys.path.insert(0, str(pathlib.Path(os.environ['TEST_HOOK']).parents[1] / 'tests'))
from test_ci import allowed_process
state = {'next': 0}
def audit(event, args):
    if event == 'subprocess.Popen':
        executable, argv, cwd, env = args
        index = state['next']
        if index >= len(expected_argv) or not allowed_process(executable, argv, expected_argv[index], os.name == 'nt'):
            pathlib.Path(os.environ['TEST_DENIED']).write_text('unexpected subprocess')
            raise SystemExit(91)
        state['next'] += 1
    elif event.startswith('socket.') or event in ('os.system', 'os.posix_spawn', 'os.exec'):
        pathlib.Path(os.environ['TEST_DENIED']).write_text('unexpected external action')
        raise SystemExit(92)
sys.addaudithook(audit)
sys.argv = [os.environ['TEST_HOOK'], os.environ['TEST_EVENT']]
runpy.run_path(sys.argv[0], run_name='__main__')
'''


class CredentialGuard(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='zcode-guard-')
        self.addCleanup(self.temp.cleanup)
        self.case = Path(self.temp.name)
        self.spy = self.case / 'spy.py'
        self.calls = self.case / 'calls.jsonl'
        self.log = self.case / 'hook.log'
        self.denied = self.case / 'denied'
        self.spy.write_text(r'''import json, os, sys, datetime, time
with open(os.environ['TEST_CALLS'], 'a', encoding='utf-8') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
sub = sys.argv[1]
mode = os.environ.get('STUB_MODE', 'ok')
if mode == 'dead': sys.exit(7)
if mode == 'malformed': print('not json'); sys.exit(0)
if mode == 'hang': time.sleep(30)
if sub == 'recall':
    print(json.dumps({'status':'ok','details':[{'id':'cccccccccccccccc','title':'spy','score':0.9}]}))
elif sub == 'remember':
    if mode == 'warn':
        print(json.dumps({'status':'warn','summary':{'action':'created','id':'eeeeeeeeeeeeeeee'},
                          'errors':['parent (cause) cannot be resolved; stored independently']}))
        sys.exit(2)
    if mode == 'pending':
        print(json.dumps({'status':'pending','summary':{'state':'candidates','written':False},
                          'items':[{'name':'aaaabbbb','status':'pending',
                                    'value':'similarity=88% title=stub candidate',
                                    'action':'merge or attach'}],
                          'actions':['rsrs remember "<combined content>" --merge-ids "aaaabbbb"',
                                     'rsrs remember "<content>" --parent <candidate id>',
                                     'rsrs remember "<content>" --force to write as new entry']}))
        sys.exit(2)
    if mode == 'silent': sys.exit(0)
    print(json.dumps({'status':'ok','summary':{'action':'created','id':'dddddddddddddddd'}}))
elif sub == 'show':
    if mode == 'show_fail':
        print(json.dumps({'status':'fail','errors':['not found']}))
        sys.exit(2)
    title, content = 'stub', 'stub'
    try:
        for line in open(os.environ['TEST_CALLS'], encoding='utf-8').read().splitlines():
            call = json.loads(line)
            if call and call[0] == 'remember':
                content, title = call[1], call[3]
    except Exception:
        pass
    if mode == 'show_mismatch':
        title = title + ' (drifted)'
    print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':title},
                      'details':{'entry':{'id':sys.argv[2],'title':title,'content':content}}}))
elif sub == 'status':
    print(json.dumps({'status':'ok','summary':{'session':{'has_token':True,'user':'stub'},'local_total':42}}))
elif sub == 'list':
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() if mode == 'recent' else '2020-01-01T00:00:00Z'
    print(json.dumps({'status':'fail'} if mode == 'failed' else {'status':'ok','details':[{'id':'record','updated_at':ts}]}))
else: sys.exit(1)
''', encoding="utf-8")
        if os.name == 'nt':
            self.engine = self.case / 'rsrs-spy.cmd'
            self.engine.write_text(f'@echo off\n"{sys.executable}" "{self.spy}" %*\n', encoding="utf-8")
        else:
            self.engine = self.case / 'rsrs-spy'
            self.engine.write_text(f'#!{sys.executable}\n' + self.spy.read_text(encoding="utf-8"), encoding="utf-8")
        self.engine.chmod(0o700)
        self.config = self.case / 'config.json'
        self.config.write_text(json.dumps({'rsrs': str(self.engine), 'session_rules': True}), encoding="utf-8")
        self.launcher = self.case / 'launcher.py'
        self.launcher.write_text(LAUNCHER, encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items()
                    if k.upper() in {'PATH', 'SYSTEMROOT', 'WINDIR', 'PATHEXT', 'TEMP', 'TMP', 'COMSPEC'}}
        self.env.update(RESPITE_CONFIG=str(self.config), RESPITE_LOG=str(self.log),
                        HOME=str(self.case / 'home'), USERPROFILE=str(self.case / 'home'),
                        XDG_CONFIG_HOME=str(self.case / 'config'),
                        XDG_DATA_HOME=str(self.case / 'data'),
                        XDG_CACHE_HOME=str(self.case / 'cache'),
                        RESPITE_NUDGE_STATE=str(self.case / 'nudge'),
                        RESPITE_DATA=str(self.case / 'plugin-data'),
                        ZCODE_PLUGIN_DATA=str(self.case / 'plugin-data'),
                        TEST_ENGINE=str(self.engine), TEST_CALLS=str(self.calls),
                        TEST_DENIED=str(self.denied), TEST_HOOK=str(ROOT / 'hooks/respire.py'),
                        PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')

    def call(self, prompt='', event='UserPromptSubmit', mode='ok', active=False, every=1,
             session='s1', fast=False):
        self.config.write_text(json.dumps({'rsrs':str(self.engine), 'session_rules':True,
                                          'store_nudge_every':every}), encoding="utf-8")
        if event == 'Stop':
            args_seq = [['list','--limit','3','--json']]
        elif event == 'SessionStart':
            args_seq = [['status','--json']]
        elif prompt.startswith(('记：','store:')):
            content = prompt.replace('：',':',1).split(':',1)[1].strip()
            argv = ['remember',content,'--title',content,'--importance','important','--json']
            if mode in ('ok','show_fail','show_mismatch'):
                args_seq = [argv, ['show','dddddddddddddddd','--json']]
            elif mode == 'warn':
                args_seq = [argv, ['show','eeeeeeeeeeeeeeee','--json']]
            elif mode == 'silent':   # 未知回执 → 只读核实 list
                args_seq = [argv, ['list','--limit','3','--json']]
            else:                    # pending / hang：不再有后续引擎调用
                args_seq = [argv]
        else:
            args_seq = [['recall',prompt,'--limit','5','--titles','--json']]
        env = dict(self.env, TEST_EXPECTED_ARGV=json.dumps([[str(self.engine)] + a for a in args_seq]),
                   TEST_EVENT=event, STUB_MODE=mode)
        if fast:
            env['RESPITE_TEST_FAST'] = '1'
        payload = {'prompt':prompt,'hook_event_name':event,'stop_hook_active':active}
        if session is not None:
            payload['session_id'] = session
        result = subprocess.run([sys.executable, str(self.launcher)],
                                input=json.dumps(payload), text=True,
                                encoding='utf-8', capture_output=True, env=env,
                                cwd=self.case, timeout=40)
        self.assertFalse(self.denied.exists(), 'Isolation denied an external action')
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def recorded(self):
        return [json.loads(line) for line in self.calls.read_text(encoding="utf-8").splitlines()] if self.calls.exists() else []

    def positive_control(self):
        before = len(self.recorded())
        output = self.call('rsrs envelope structure recall')
        self.assertEqual(len(self.recorded()), before + 1, 'Live spy must record normal input')
        self.assertEqual(self.recorded()[-1][0], 'recall')
        self.assertIn('auto-recall', output)
        self.assertIn('matched 1 item(s)', output)
        self.assertIn('[0.90] spy', output)
        return output

    def test_normal_input_requires_live_spy(self):
        output = self.positive_control()
        self.assertNotIn('\n', output)
        self.assertIn('[0.90] spy', json.loads(output)['additionalContext'])

    def test_credential_has_zero_calls_and_no_disclosure(self):
        self.positive_control()
        before = self.recorded()
        output = self.call('api_key = ' + SECRET + ' store this')
        self.assertIn('contains a credential', output)
        self.assertEqual(self.recorded(), before)
        self.assertNotIn(SECRET, output)
        self.assertNotIn(SECRET, self.log.read_text(encoding="utf-8"))
        entries = [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]
        skipped = [entry for entry in entries if entry['out'] == 'secret_skip']
        self.assertEqual(len(skipped), 1)
        self.assertNotIn('d', skipped[0])

    def test_store_prefix_credential_is_blocked(self):
        self.positive_control()
        before = self.recorded()
        output = self.call('记：数据库密码 = hunter2u')
        self.assertIn('contains a credential', output)
        self.assertEqual(self.recorded(), before)
        self.assertNotIn('hunter2u', output + self.log.read_text(encoding="utf-8"))

    def test_dead_spy_must_fail_positive_control(self):
        # A valid executable that does not record/return JSON must never count as
        # proof of a zero-call guard. This explicitly exercises that failure.
        if os.name == 'nt':
            self.spy.write_text('import sys\nsys.exit(7)\n', encoding="utf-8")
        else:
            self.engine.write_text(f'#!{sys.executable}\nimport sys\nsys.exit(7)\n', encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, 'Live spy must record normal input'):
            self.positive_control()

    def test_session_uses_only_stub_status(self):
        out = self.call(event='SessionStart')
        self.assertIn('respire memory layer', json.loads(out)['additionalContext'])
        self.assertIn('respire memory layer', out)
        self.assertNotIn('not signed in', out)
        self.assertEqual([args[0] for args in self.recorded()], ['status'])

    def test_explicit_store_receipt_comes_from_stub(self):
        out = self.call('store: durable fixture fact')
        self.assertIn('respire · stored', out)
        self.assertIn('retitle dddddddd', out)
        self.assertIn('verified by read-back', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_warn_is_written_not_refused(self):
        # CLI 契约：status=warn + 有效 id = 已提交但有警告（parent 未解析等）——
        # 不得误报「未接受」，更不得引导重发（重复写风险）
        out = self.call('store: durable fixture fact', mode='warn')
        self.assertIn('Saved with warnings', out)
        self.assertIn('parent (cause) cannot be resolved', out)
        self.assertIn('retitle eeeeeeee', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_pending_relays_candidates_and_actions(self):
        # §7.2：pending 保留候选（含短 id）与引擎建议动作（改＞并＞挂＞存），不得缩成 parent/force 两项
        out = self.call('store: durable fixture fact', mode='pending')
        self.assertIn('store pending', out)
        self.assertIn('nothing was written', out)
        self.assertIn('[aaaabbbb]', out)
        self.assertIn('similarity=88% title=stub candidate', out)
        self.assertIn('merge or attach', out)
        self.assertIn('--merge-ids', out)
        self.assertIn('--force', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember'])

    def test_store_readback_states(self):
        # R11 写后核验：verified / mismatch / unavailable 三态都如实进回执
        self.assertIn('verified by read-back', self.call('store: durable fixture fact'))
        self.assertIn('DIFFERENT title/content',
                      self.call('store: durable fixture fact', mode='show_mismatch'))
        self.assertIn('Read-back unavailable',
                      self.call('store: durable fixture fact', mode='show_fail'))

    def test_store_unknown_receipt_never_demands_resend(self):
        # R10：坏回执 = 结果未知 → 只读核实；绝不当确定失败、绝不引导重发 remember
        out = self.call('store: durable fixture fact', mode='silent')
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertIn('rsrs list --limit 3', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'list'])

    def test_store_timeout_is_unknown_and_makes_no_further_calls(self):
        # 超时 = 结果未知：回执只允许只读核实指引，不再发引擎调用（预算已耗尽）
        before = self.recorded()
        out = self.call('store: durable fixture fact', mode='hang', fast=True)
        self.assertIn('store unknown', out)
        self.assertIn('timed out', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)

    def test_stop_deny_and_reentry_zero_calls(self):
        out = json.loads(self.call(event='Stop'))
        self.assertEqual(out['decision'], 'block')
        self.assertIn('rsrs remember', out['reason'])
        before, count = self.recorded(), (self.case / 'nudge').read_text(encoding="utf-8")
        self.assertEqual(self.call(event='Stop', active=True), '')
        self.assertEqual(self.recorded(), before)
        self.assertEqual((self.case / 'nudge').read_text(encoding="utf-8"), count)

    def test_stop_every_third_request_and_disabled_zero_calls(self):
        for number in range(1, 7):
            self.call(f'ordinary input {number}')          # 每轮都是新请求：重新武装收尾预算
            raw = self.call(event='Stop', every=3)
            if number in (3, 6):
                self.assertEqual(json.loads(raw)['decision'], 'block')
            else:
                self.assertEqual(raw, '')
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 2)
        before = self.recorded()
        self.assertEqual(self.call(event='Stop', every=0), '')
        self.assertEqual(self.recorded(), before)
        self.assertEqual((self.case / 'nudge').read_text(encoding="utf-8"), '6')

    def test_stop_engine_turn_bounded_and_fail_open(self):
        # ZC-01/ZC-04：无请求凭证时 fresh 引擎写入不免催（不做跨轮误抑制）
        self.assertEqual(json.loads(self.call(event='Stop', mode='recent'))['decision'], 'block')
        # 请求之后引擎有写入（agent 自行 rsrs remember）→ 免催
        self.call('ordinary input')
        self.assertEqual(self.call(event='Stop', mode='recent'), '')
        # 查询失败/坏信封 → fail-open 放行，且每次至多一次查询
        before = self.recorded()
        self.assertEqual(self.call(event='Stop', mode='failed'), '')
        self.assertEqual(self.call(event='Stop', mode='malformed'), '')
        self.assertEqual(len(self.recorded()) - len(before), 2)

    def test_stop_after_hook_store_does_not_query_engine(self):
        self.call('store: durable fixture fact')
        before = self.recorded()
        self.assertEqual(self.call(event='Stop'), '')
        self.assertEqual(self.recorded(), before)

    def test_turn_receipt_suppression_is_request_scoped(self):
        # T18：只有「同会话、本轮 prompt 之后」的成功写回执才免催；新请求不被旧轮抑制
        self.call('store: durable fixture fact')
        self.assertEqual(self.call(event='Stop'), '')
        self.call('another ordinary input without storing')   # 新请求（未存）
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_stop_once_per_request_latch(self):
        # ZC-05：宿主未带 stop_hook_active 时，同一请求也至多催一次；新请求重新武装
        self.call('ordinary input')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')
        before = self.recorded()
        self.assertEqual(self.call(event='Stop'), '')
        self.assertEqual(self.recorded(), before)
        self.call('fresh request after wrap-up')
        self.assertEqual(json.loads(self.call(event='Stop'))['decision'], 'block')

    def test_receipt_suppression_is_session_scoped(self):
        # 会话隔离：A 会话的写回执不免 B 会话的催存
        self.call('store: durable fixture fact', session='a')
        self.assertEqual(json.loads(self.call(event='Stop', session='b'))['decision'], 'block')

    def test_malformed_spy_cannot_pass_positive_control(self):
        self.positive_control()
        self.assertEqual(self.call('ordinary input', mode='malformed'), '')
        self.assertIn('parse_error', self.log.read_text(encoding="utf-8"))


def assert_versions(root):
    market=json.loads((root/'.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
    entries=[entry for entry in market['plugins'] if entry['name']=='respire']
    manifest=json.loads((root/'.zcode-plugin/plugin.json').read_text(encoding='utf-8'))
    hook=re.search(r'^VERSION = "([^"]+)"',(root/'hooks/respire.py').read_text(encoding='utf-8'),re.M).group(1)
    if len(entries)!=1 or hook!=manifest['version'] or ('version' in entries[0] and entries[0]['version']!=manifest['version']):
        raise ValueError('Plugin/hook/marketplace version mismatch')

class VersionConsistency(unittest.TestCase):
    def test_versions_match(self):
        assert_versions(ROOT)

    def test_each_mismatch_is_rejected(self):
        for component in ('marketplace','manifest','hook'):
            with self.subTest(component=component), tempfile.TemporaryDirectory(prefix='version-negative-') as directory:
                fixture=Path(directory)
                for name in ('.claude-plugin', '.zcode-plugin', 'hooks'):
                    shutil.copytree(ROOT/name,fixture/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                if component=='hook':
                    path=fixture/'hooks/respire.py'
                    path.write_text(re.sub(r'^VERSION = "[^"]+"','VERSION = "999.0.0"',path.read_text(encoding='utf-8'),count=1,flags=re.M),encoding='utf-8')
                else:
                    path=fixture/('.claude-plugin/marketplace.json' if component=='marketplace' else '.zcode-plugin/plugin.json')
                    doc=json.loads(path.read_text(encoding='utf-8'))
                    if component=='marketplace':
                        next(entry for entry in doc['plugins'] if entry['name']=='respire')['version']='999.0.0'
                    else:doc['version']='999.0.0'
                    path.write_text(json.dumps(doc),encoding='utf-8')
                with self.assertRaises(ValueError):assert_versions(fixture)


class ProcessAuditPolicy(unittest.TestCase):
    def test_windows_none_executable_and_exact_commandline_are_allowed(self):
        expected = [r'C:\temp\space name\rsrs-spy.cmd', 'recall', 'ordinary input', '--json']
        self.assertTrue(allowed_process(None, subprocess.list2cmdline(expected), expected, True))

    def test_posix_exact_executable_and_complete_argv_are_allowed(self):
        expected = ['/tmp/rsrs-spy', 'recall', 'ordinary input', '--json']
        self.assertTrue(allowed_process(expected[0], expected, expected, False))

    def test_other_programs_arguments_and_shell_additions_are_rejected(self):
        expected = [r'C:\temp\space name\rsrs-spy.cmd', 'recall', 'ordinary input', '--json']
        encoded = subprocess.list2cmdline(expected)
        for executable, argv, windows in (
            ('cmd.exe', encoded, True),
            ('python.exe', encoded, True),
            (None, encoded + ' & echo unwanted', True),
            (None, encoded + ' extra', True),
            (None, 'cmd.exe /c ' + encoded, True),
            (None, encoded.replace('rsrs-spy.cmd', 'rsrs-spy.cmd-other'), True),
            (None, encoded, False),
            (expected[0], expected + ['extra'], False),
        ):
            with self.subTest(executable=executable, argv=argv, windows=windows):
                self.assertFalse(allowed_process(executable, argv, expected, windows))


if __name__ == '__main__':
    unittest.main(verbosity=2)
