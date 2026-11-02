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
assert isinstance(expected_argv, list)  # may be empty: zero engine calls are a legal expectation
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
if os.environ.get('TEST_STORE_HELPER') == '1':
    mod = runpy.run_path(sys.argv[0], run_name='respire_helper')
    data = json.load(sys.stdin)
    session = str(data.get('session_id') or '')
    gen = mod['mark_prompt'](session)
    content = data['prompt'].replace('：', ':', 1).split(':', 1)[1].strip()
    print(mod['do_store'](expected, content, mod['load_config'](), session, gen))
else:
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
if sys.argv[1] == '--client-only': del sys.argv[1]
sub = sys.argv[1]
mode = os.environ.get('STUB_MODE', 'ok')
list_mode = os.environ.get('STUB_LIST', mode)
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
    if mode == 'ok_noid': print(json.dumps({'status':'ok','summary':{'action':'created'}})); sys.exit(0)
    if mode == 'ok_junkid': print(json.dumps({'status':'ok','summary':{'id':'zz!!not-hex'}})); sys.exit(0)
    if mode == 'bad_summary': print(json.dumps({'status':'ok','summary':'boom'})); sys.exit(0)
    if mode == 'skip_status': print(json.dumps({'status':'skip','summary':{}})); sys.exit(0)
    if mode == 'slow_garbage':
        time.sleep(float(os.environ.get('STUB_SLEEP', '2.5'))); print('garbage not json'); sys.exit(0)
    print(json.dumps({'status':'ok','summary':{'action':'created','id':'dddddddddddddddd'}}))
elif sub == 'show':
    if mode == 'show_parented_bad' and sys.argv[2] == 'aaaaaaaaaaaaaaaa':
        print(json.dumps({'status':'fail'})); sys.exit(2)
    if mode in ('show_parented','show_parented_bad'):
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2]},
                          'details':{'entry':{'id':sys.argv[2],'parent_id':'aaaaaaaaaaaaaaaa'}}}))
        sys.exit(0)
    if mode == 'show_badsummary':
        print(json.dumps({'status':'ok','summary':{'id':'9999999999999999'},
                          'details':{'entry':{'id':sys.argv[2]}}}))
        sys.exit(0)
    if mode == 'show_fail':
        print(json.dumps({'status':'fail','errors':['not found']}))
        sys.exit(2)
    if mode == 'show_badarr':   # 坏 details 反例：非空数组——旧实现 .get() 抛 AttributeError 吞回执
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':'stub'},
                          'details':[{}]}))
        sys.exit(0)
    if mode == 'show_strdet':   # 坏 details 反例：字符串
        print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':'stub'},
                          'details':'not-a-dict'}))
        sys.exit(0)
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
    if mode == 'show_wrongid':
        print(json.dumps({'status':'ok','summary':{'id':'99999999-9999-4999-8999-999999999999','title':title},
                          'details':{'entry':{'id':'99999999-9999-4999-8999-999999999999','title':title,'content':content}}}))
        sys.exit(0)
    if mode == 'show_tail' and content:
        content = content[:40] + 'TAMPERED-TAIL'
    print(json.dumps({'status':'ok','summary':{'id':sys.argv[2],'title':title},
                      'details':{'entry':{'id':sys.argv[2],'title':title,'content':content}}}))
elif sub == 'status':
    print(json.dumps({'status':'ok','summary':{'session':{'has_token':True,'user':'stub'},'local_total':42}}))
elif sub == 'list':
    ts = datetime.datetime.now(datetime.timezone.utc).isoformat() if list_mode == 'recent' else '2020-01-01T00:00:00Z'
    if list_mode == 'list_schema':
        print(json.dumps({'status':'ok','details':{'broken':True}}))
    elif list_mode == 'list_notimes':
        print(json.dumps({'status':'ok','details':[{'id':'record','no_dates':True}]}))
    else:
        print(json.dumps({'status':'fail'} if list_mode == 'failed' else {'status':'ok','details':[{'id':'record','updated_at':ts}]}))
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
                        RESPITE_TURN_STATE=str(self.case / 'turn-state'),
                        ZCODE_PLUGIN_DATA=str(self.case / 'plugin-data'),
                        TEST_ENGINE=str(self.engine), TEST_CALLS=str(self.calls),
                        TEST_DENIED=str(self.denied), TEST_HOOK=str(ROOT / 'hooks/respire.py'),
                        PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1')

    def call(self, prompt='', event='UserPromptSubmit', mode='ok', active=False, every=1,
             session='s1', fast=False, extra_env=None, list_mode=None, no_calls=False, direct_store=False, guard_command=None, guard_parent=None, guard_tool="Bash"):
        self.config.write_text(json.dumps({'rsrs':str(self.engine), 'session_rules':True,
                                          'store_nudge_every':every}), encoding="utf-8")
        if event == 'PreToolUse':
            parents = guard_parent if isinstance(guard_parent, list) else [guard_parent] if guard_parent else []
            args_seq = [['--client-only','show',p,'--json'] for p in parents]
        elif event == 'Stop':
            args_seq = [['list','--limit','3','--json']]
        elif event == 'SessionStart':
            args_seq = [['status','--json']]
        elif no_calls:          # 期望零引擎调用（如预算耗尽：remember 根本不发）
            args_seq = []
        elif prompt.startswith(('记：','store:')) and direct_store:
            content = prompt.replace('：',':',1).split(':',1)[1].strip()
            argv = ['remember',content,'--title',content,'--importance','important','--json']
            if mode in ('ok','show_fail','show_mismatch','show_wrongid','show_tail',
                        'show_badarr','show_strdet'):
                args_seq = [argv, ['show','dddddddddddddddd','--json']]
            elif mode == 'warn':
                args_seq = [argv, ['show','eeeeeeeeeeeeeeee','--json']]
            elif mode in ('silent','ok_noid','ok_junkid','bad_summary'):  # 未知回执 → 只读核实 list
                args_seq = [argv, ['list','--limit','3','--json']]
            else:                    # pending / hang / skip_status / slow_garbage：不再有后续引擎调用
                args_seq = [argv]
        elif prompt.startswith(('记：','store:')):
            args_seq = []
        else:
            args_seq = [['recall',prompt,'--limit','5','--titles','--json']]
        env = dict(self.env, TEST_EXPECTED_ARGV=json.dumps([[str(self.engine)] + a for a in args_seq]),
                   TEST_EVENT=event, STUB_MODE=mode)
        if direct_store:
            env['TEST_STORE_HELPER'] = '1'
        if fast:
            env['RESPITE_TEST_FAST'] = '1'
        if extra_env:
            env.update(extra_env)
        if list_mode is not None:
            env['STUB_LIST'] = list_mode

        payload = {'prompt':prompt,'hook_event_name':event,'stop_hook_active':active}
        if event == 'PreToolUse':
            payload.update(tool_name=guard_tool, tool_input={'command':guard_command})
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
        context = json.loads(output)['additionalContext']
        self.assertIn('[0.90] spy', context)
        self.assertIn('Memory: 1 found', context.splitlines())
        for rule in ('strict JSON', 'fixed format', 'only-specified output', 'including Used and unused',
                     'Candidates are not adoptions', 'successfully reading a body and actually using it',
                     'Default to [ref]', '[basis]', '[history]', 'not that it was carried out',
                     'most conservative label', '24 Unicode characters', '(title hidden)',
                     'Never show bodies, full IDs', 'Memory: unused', 'DO NOT invent Last save'):
            self.assertIn(rule, context)
        self.assertNotRegex(context, r'(?m)^(?:Used|Last save):')
        import importlib.util
        spec = importlib.util.spec_from_file_location('visibility_fixture', ROOT / 'hooks' / 'respire.py')
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        hook.log_event = lambda *a, **k: None
        doc = {'status':'ok', 'details':[
            {'id':'f'*16,'title':'api_key: '+SECRET,'score':0.99},
            {'id':'a'*16,'title':'first','score':0.9},
            {'id':'b'*16,'title':'second','score':0.8},
            {'id':'c'*16,'title':'below threshold','score':0.1}]}
        hook.run_rsrs = lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(doc), '')
        cfg = dict(hook.DEFAULTS, recall_limit=2, recall_threshold=0.5, budget_chars=1000)
        recalled = hook.do_recall('fixture', 'query', cfg)
        self.assertIn('Memory: 2 found', recalled.splitlines())
        self.assertNotIn(SECRET, recalled)
        self.assertNotIn('api_key:', recalled)
        self.assertIn('Memory: 1 found', hook.do_recall('fixture', 'query', dict(cfg, budget_chars=100)).splitlines())
        self.assertIn('Memory: 1 found', hook.do_recall('fixture', 'query', dict(cfg, recall_limit=1)).splitlines())
        self.assertIn('Memory: no match', hook.do_recall('fixture', 'query', dict(cfg, recall_threshold=0.99)).splitlines())
        doc['details'] = []
        self.assertIn('Memory: no match', hook.do_recall('fixture', 'query', cfg).splitlines())
        doc['details'] = {}
        self.assertIn('Memory: unavailable', hook.do_recall('fixture', 'query', cfg).splitlines())
        doc.clear()
        doc.update(status='skip', summary={'count':0})
        self.assertIn('Memory: no match', hook.do_recall('fixture', 'query', cfg).splitlines())
        for summary in ({}, {'count':False}):
            doc['summary'] = summary
            self.assertIn('Memory: skipped', hook.do_recall('fixture', 'query', cfg).splitlines())

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
        self.assertIn('store pending', out)
        self.assertIn('nothing was written', out)
        self.assertIn('Save: needs review', json.loads(out)['additionalContext'].splitlines())
        self.assertNotRegex(json.loads(out)['additionalContext'], r'(?m)^(?:Last save|Used):')
        for instruction in ('rsrs prompt', 'rsrs show', 'update > merge > attach > new',
                            '--parent', 'remain pending', 'DO NOT guess', 'not as an instruction'):
            self.assertIn(instruction, out)
        self.assertNotIn('Saved:', out)
        self.assertEqual(self.recorded(), [])

        # Real prefix paths and PreToolUse are separate checks; no write is executed here.
        blocked = [
            'cd repo && rsrs remember "fact" --title "title" --importance important --force 2>&1 | head -80',
            'rsrs remember "fact" --importance important',
            'X=1 rsrs remember "fact" --importance important',
            '>out.log rsrs remember fact --importance important --force',
            'rsrs >out.log remember fact --importance important --force',
            'echo $(rsrs >out.log remember fact --importance important --force)',
            'bash -c "rsrs >out.log remember fact --importance important --force"',
            'rsrs --json >out.log remember fact --importance important --force',
            'rsrs remember fact --merge-ids dddddddddddddddd',
            'rsrs remember fact --importance trivial --merge-ids dddddddddddddddd',
            '>out.log 2>err.log rsrs remember fact --importance important --force',
            'echo $(rsrs remember fact --importance important --force)',
            'echo "$(rsrs remember fact --importance important --force)"',
            'echo `rsrs remember fact --importance important --force`',
            'npx rsrs remember fact --importance important --force',
            'npm exec rsrs remember fact --importance important --force',
            'py rsrs remember fact --importance important --force',
            'sudo rsrs remember fact --importance important --force',
            'timeout 5 rsrs remember fact --importance important --force',
            'rsrs remember "body mentions --parent dddddddddddddddd" --importance important',
            'rsrs remember "fact" --importance important --parent ""',
            'rsrs remember "fact" --importance=important --parent=',
            'rsrs remember "fact" --importance trivial --force',
            'rsrs remember "fact" --importance trivial; rsrs remember "other" --importance important',
            'bash -c "rsrs remember fact --importance important --parent dddddddddddddddd"',
            '(rsrs remember "fact" --importance important --parent dddddddddddddddd)',
            'rsrs remember "$fact" --importance important --parent dddddddddddddddd',
            'rsrs remember "fact" --importance important --parent dddddddddddddddd --force',
            'rsrs remember "unfinished',
        ]
        for command in blocked:
            before = self.recorded()
            out = json.loads(self.call(event='PreToolUse', guard_command=command))
            self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'PreToolUse')
            self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny', command)
            self.assertEqual(self.recorded(), before, command)
        for command in ('echo "rsrs remember"', 'rsrs recall "fact" --json',
                        'rsrs recall remember --titles --json',
                        'rsrs --client-only --json recall remember --titles',
                        'rsrs --json --client-only candidates remember',
                        'rsrs --model-task-id audit --progress-id progress recall remember --json',
                        'npx rsrs recall remember --json',
                        'bash -c "rsrs recall remember --json"',
                        "echo '$(rsrs remember fact --importance important --force)'",
                        "echo '`rsrs remember fact --importance important --force`'",
                        'rsrs remember "diary" --importance trivial',
                        'rsrs remember "fact" --help'):
            self.assertEqual(self.call(event='PreToolUse', guard_command=command), '', command)
        for prefix in ('--client-only --json', '--json --client-only', '--model-task-id audit --progress-id progress', '--progress-id=progress --model-task-id=audit --json'):
            denied = json.loads(self.call(event='PreToolUse', guard_command='rsrs ' + prefix + ' remember "fact" --importance important'))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(self.call(event='PreToolUse', guard_command='rsrs ' + prefix + ' remember "fact" --importance important --parent dddddddddddddddd', guard_parent='dddddddddddddddd'), '')
        metadata = ' --model-task-id audit --progress-id progress --project Respire --tags plugin,parent --type context --summary "candidate summary" --source-refs "[]" --valid-until 2027-01-01T00:00:00.000Z --review-at 2027-01-01T00:00:00.000Z --artifact "{}" --computer TB16P --emotion -1 --supersedes dddddddddddddddd --see-also dddddddddddddddd'
        for suffix in (metadata, ' --clear-summary --clear-source-refs --clear-valid-until --clear-review-at --clear-artifact'):
            self.assertEqual(self.call(event='PreToolUse', guard_command='>out.log rsrs remember fact --importance important --parent dddddddddddddddd' + suffix, guard_parent='dddddddddddddddd'), '')
        for command in ('rsrs >out.log remember fact --importance important --parent dddddddddddddddd',
                        'rsrs remember fact --emotion 1 >out.log --importance important --parent dddddddddddddddd',
                        'rsrs remember ">" --importance important --parent dddddddddddddddd',
                        'rsrs remember fact --merge-ids eeeeeeeeeeeeeeee --parent dddddddddddddddd'):
            self.assertEqual(self.call(event='PreToolUse', guard_command=command, guard_parent='dddddddddddddddd'), '')
        command = 'rsrs update dddddddddddddddd --importance important --content "updated fact"'
        denied = json.loads(self.call(event='PreToolUse', guard_command=command, guard_parent='dddddddddddddddd'))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('attach', denied['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(self.call(event='PreToolUse', guard_command=command, guard_parent=['dddddddddddddddd','aaaaaaaaaaaaaaaa'], mode='show_parented'), '')
        for promotion in ('rsrs update --importance important dddddddddddddddd', 'rsrs update --importance=important dddddddddddddddd'):
            denied = json.loads(self.call(event='PreToolUse', guard_command=promotion, guard_parent='dddddddddddddddd'))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(self.call(event='PreToolUse', guard_command=promotion, guard_parent=['dddddddddddddddd','aaaaaaaaaaaaaaaa'], mode='show_parented'), '')
        denied = json.loads(self.call(event='PreToolUse', guard_command=command, guard_parent=['dddddddddddddddd','aaaaaaaaaaaaaaaa'], mode='show_parented_bad'))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.call(event='PreToolUse', guard_command='rsrs update dddddddddddddddd --importance trivial'), '')
        command = 'cd repo && rsrs remember "fact" --title "title" --importance=important --parent=dddddddddddddddd 2>&1 | head -80'
        self.assertEqual(self.call(event='PreToolUse', guard_command=command,
                                   guard_parent='dddddddddddddddd'), '')
        for mode in ('show_fail', 'show_wrongid', 'show_badsummary', 'show_badarr', 'show_strdet', 'malformed', 'dead', 'hang'):
            out = json.loads(self.call(event='PreToolUse', guard_command=command,
                                       guard_parent='dddddddddddddddd', mode=mode, fast=True))
            self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny', mode)
        out = json.loads(self.call(event='PreToolUse', guard_command=command,
                                  extra_env={'RESPITE_HOOK_BUDGET_S':'1'}))
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.call(event='PreToolUse', guard_command=command, guard_tool='Read'), '')
        self.assertEqual(self.call(event='PreToolUse', guard_command=command, guard_tool='mcp__other__memory_recall'), '')
        matcher = json.loads((ROOT / 'hooks' / 'hooks.json').read_text())['hooks']['PreToolUse'][0]['matcher']
        for tool in ('mcp__respire__memory_remember','memory_remember','mcp__rsrs__memory_remember','memory_update','mcp__rsrs__memory_update'):
            self.assertIsNotNone(re.fullmatch(matcher, tool))
            denied = json.loads(self.call(event='PreToolUse', guard_tool=tool))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertIn('target store', denied['hookSpecificOutput']['permissionDecisionReason'])

    def test_store_warn_is_written_not_refused(self):
        # CLI 契约：status=warn + 有效 id = 已提交但有警告（parent 未解析等）——
        # 不得误报「未接受」，更不得引导重发（重复写风险）
        out = self.call('store: durable fixture fact', mode='warn', direct_store=True)
        self.assertIn('Saved with warnings', out)
        self.assertIn('parent (cause) cannot be resolved', out)
        self.assertIn('retitle eeeeeeee', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'show'])

    def test_store_pending_relays_candidates_and_actions(self):
        for mode in ('pending', 'ok', 'warn', 'silent', 'hang'):
            out = self.call('store: durable fixture fact', mode=mode)
            self.assertIn('store pending', out)
            self.assertIn('nothing was written', out)
            self.assertIn('update > merge > attach > new', out)
            self.assertIn('remain pending', out)
            self.assertEqual(self.recorded(), [])

    def test_store_readback_states(self):
        # R11 写后核验：verified / mismatch / unavailable 三态都如实进回执
        self.assertIn('verified by read-back', self.call('store: durable fixture fact', direct_store=True))
        self.assertIn('DIFFERENT title/content',
                      self.call('store: durable fixture fact', mode='show_mismatch', direct_store=True))
        self.assertIn('Read-back unavailable',
                      self.call('store: durable fixture fact', mode='show_fail', direct_store=True))

    def test_store_readback_bad_details_keeps_saved_receipt(self):
        # 复核2轮#2：show 回读遇非字典 details（非空数组/字符串）曾抛 AttributeError 被
        # fail-open 吞掉——Saved 回执整个消失。现须保留 Saved + unavailable：
        # 不是空输出，也不是 did not accept（did not accept 会诱发重发/重复写）。
        for mode in ('show_badarr', 'show_strdet'):
            out = self.call('store: bad details fact', mode=mode, direct_store=True)
            self.assertTrue(out.strip(), mode)
            self.assertIn('Saved:', out, mode)
            self.assertIn('Read-back unavailable', out, mode)
            self.assertNotIn('did not accept', out, mode)
            self.assertEqual([a[0] for a in self.recorded()][-2:], ['remember', 'show'], mode)

    def test_store_unknown_receipt_never_demands_resend(self):
        # R10：坏回执 = 结果未知 → 只读核实；绝不当确定失败、绝不引导重发 remember
        out = self.call('store: durable fixture fact', mode='silent', direct_store=True)
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertIn('rsrs list --limit 3', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([args[0] for args in self.recorded()], ['remember', 'list'])

    def test_store_timeout_is_unknown_and_makes_no_further_calls(self):
        # 超时 = 结果未知：回执只允许只读核实指引，不再发引擎调用（预算已耗尽）
        before = self.recorded()
        out = self.call('store: durable fixture fact', mode='hang', fast=True, direct_store=True)
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
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 0)
        before = self.recorded()
        self.assertEqual(self.call(event='Stop', every=0), '')
        self.assertEqual(self.recorded(), before)
        self.assertEqual((self.case / 'nudge').read_text(encoding="utf-8"), '6')

    def test_receipt_edge_cases_are_unknown_not_failed(self):
        # 复核整改：ok/warn 缺 id、垃圾 id、summary 非对象 → unknown（禁重发，不当失败也不当成功）
        for mode, expect_list in (('ok_noid', True), ('ok_junkid', True), ('bad_summary', True)):
            out = self.call('store: edge fact', mode=mode, direct_store=True)
            self.assertIn('store unknown', out, mode)
            self.assertIn('Do NOT resend', out, mode)
            self.assertNotIn('did not accept', out, mode)
            self.assertNotIn('Saved', out, mode)
            self.assertEqual([a[0] for a in self.recorded()][-1] == 'list', expect_list, mode)
        # skip：引擎按模式拒绝执行——未写、不是失败、不引导重发
        before = len(self.recorded())
        out = self.call('store: edge fact', mode='skip_status', direct_store=True)
        self.assertIn('not stored', out)
        self.assertIn('never force a write', out)
        self.assertNotIn('did not accept', out)
        self.assertEqual([a[0] for a in self.recorded()][before:], ['remember'])

    def test_readback_full_verification(self):
        # 错误 id：返回的是别的条目 → mismatch，绝不 verified
        out = self.call('store: full verify fact', mode='show_wrongid', direct_store=True)
        self.assertIn('Saved:', out)
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        # 相同前 40 字但尾部被篡改 → mismatch（不再「前缀包含即全文一致」）
        out = self.call('store: full verify fact tail', mode='show_tail', direct_store=True)
        self.assertIn('DIFFERENT', out)
        self.assertNotIn('verified by read-back', out)
        # 正常全量一致 → verified（措辞如实：id、标题与完整正文）
        out = self.call('store: full verify fact ok', direct_store=True)
        self.assertIn('verified by read-back', out)

    def test_slow_bad_receipt_respects_shared_budget(self):
        # 慢坏回执（2.5s 后回垃圾）+ 紧张预算（4s）：不再追加 list，直接输出 unknown 禁重发
        before = self.recorded()
        out = self.call('store: slow garbage fact', mode='slow_garbage',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '4'}, direct_store=True)
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)  # 只有 remember，没有 list

    def test_store_monotonic_deadline_clamps_remember_timeout(self):
        # 复核2轮#3：共享截止时间改 monotonic，且 remember 子进程超时=剩余预算（不再固定 STORE_T）。
        # 预算 4s（预留 2.5 → 剩 1.5s）、慢桩睡 6s：remember 在剩余预算处被截断——回执是
        # "timed out"（旧固定 STORE_T 会等完 6s 拿到垃圾，回执是 "unreadable receipt"）；
        # 预算随后耗尽，零追加调用。
        before = self.recorded()
        out = self.call('store: slow garbage fact', mode='slow_garbage',
                        extra_env={'RESPITE_HOOK_BUDGET_S': '4', 'STUB_SLEEP': '6'}, direct_store=True)
        self.assertIn('store unknown', out)
        self.assertIn('timed out', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(len(self.recorded()) - len(before), 1)  # 只有 remember，没有 list

    def test_store_no_remaining_budget_sends_nothing(self):
        # 复核2轮#3：剩余预算 ≤0（预算 2s < 预留 2.5s）时 remember 根本不发——零引擎调用，
        # 直接 unknown 回执（只读核实指引 + 禁重发）
        before = self.recorded()
        out = self.call('store: no budget fact', extra_env={'RESPITE_HOOK_BUDGET_S': '2'},
                        no_calls=True, direct_store=True)
        self.assertIn('store unknown', out)
        self.assertIn('Do NOT resend', out)
        self.assertEqual(self.recorded(), before)

    def test_verify_list_schema_failures_are_not_attribution(self):
        # 坏 schema list（details 非数组 / 无可解析时间戳）→ 不把新条目归属给本次写入
        for mode in ('list_schema', 'list_notimes'):
            before = len(self.recorded())
            out = self.call('store: schema fact', mode='silent', list_mode=mode, direct_store=True)
            self.assertIn('store unknown', out, mode)
            self.assertNotIn('may already be written', out, mode)
            self.assertEqual([a[0] for a in self.recorded()][before:], ['remember', 'list'], mode)

    def test_prompt_registration_failure_invalidates_old_receipt(self):
        # 第四轮①：旧请求已存（同代新鲜凭证）→ 持事务锁令新 prompt 状态更新失败
        # → 释放锁 → 新请求 Stop 不得凭旧记录免催（gen 标记已推进，旧凭证立即失效）
        import importlib.util as iu4, time as _t
        from pathlib import Path as P4
        import os as os4
        spec = iu4.spec_from_file_location('rh5', P4(self.env['TEST_HOOK']))
        mod = iu4.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P4(self.env['RESPITE_TURN_STATE'])
        old = os4.environ.get('RESPITE_TURN_STATE')
        try:
            os4.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            sid = 'failreg'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))  # 免催已取消（复核⑥）
            lock = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(lock)
            try:
                gen2 = mod.mark_prompt(sid)
                self.assertGreater(gen2, gen1)
                self.assertFalse(mod.turn_stored(sid))  # 标记已推进：旧凭证失效
            finally:
                mod._release_lock(lock)
            self.assertFalse(mod.turn_stored(sid))
            mod.mark_store(sid, gen2)
            # 登记曾失败：pt 仍是 gen1 ≠ marker(gen2)——本轮凭证保守失效（多催方向）
            self.assertFalse(mod.turn_stored(sid))
            # 恢复路径：锁已释放，下一请求 gen3 正常登记+写入（免催已取消，恒 False）
            gen3 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen3)
            self.assertFalse(mod.turn_stored(sid))
        finally:
            if old is not None:
                os4.environ['RESPITE_TURN_STATE'] = old

    def test_common_write_failure_poisons_old_receipt(self):
        # 第五轮残余（复审点名顺序）：播种旧成功凭证 → 普通 marker/state/POISON 三写均失败
        # 期间调用 mark_prompt → 恢复写能力但不再调用 mark_prompt、不手动写 POISON
        # → 当前请求 Stop 不得凭旧记录免催 → 正常登记后免催恢复。
        # 关键：失效靠 _invalidate_state 的 unlink（不需要磁盘空间）——三写全失败仍生效。
        import importlib.util as iu6
        from pathlib import Path as P6
        import os as os6, tempfile as tf6, shutil as sh6
        spec = iu6.spec_from_file_location('rh7', P6(self.env['TEST_HOOK']))
        mod = iu6.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P6(tf6.mkdtemp(prefix='zcode-r5b-'))
        self.addCleanup(sh6.rmtree, base, True)
        old = os6.environ.get('RESPITE_TURN_STATE')
        os6.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            sid = 'poison'
            gen1 = mod.mark_prompt(sid)
            mod.mark_store(sid, gen1)
            self.assertFalse(mod.turn_stored(sid))      # 免催已取消（复核⑥）：恒 False
            state_p = P6(mod._state_path(sid))
            self.assertTrue(state_p.exists())
            # 三写全部失败（同一磁盘故障）：marker/POISON/state 均返回 False
            orig_w, orig_u = mod._write_gen_marker, mod._map_update
            mod._write_gen_marker = lambda s2, g2: False
            mod._map_update = lambda s2, p2: False
            mod.mark_prompt(sid)                        # 真实调用：unlink 删旧状态（未被 mock）
            mod._write_gen_marker = orig_w             # 恢复写能力
            mod._map_update = orig_u
            # 不再调用 mark_prompt、不手动写 POISON——当前请求 Stop：
            self.assertFalse(state_p.exists())          # 旧状态文件已物理删除
            self.assertFalse(mod.turn_stored(sid))     # 免催已取消：恒 False
            gen3 = mod.mark_prompt(sid)                 # 恢复路径（下一请求）
            mod.mark_store(sid, gen3)
            self.assertFalse(mod.turn_stored(sid))     # 免催已取消：恒 False（回执仍给模型）
        finally:
            if old is not None:
                os6.environ['RESPITE_TURN_STATE'] = old
            else:
                os6.environ.pop('RESPITE_TURN_STATE', None)

    def test_lock_ownership_no_steal_no_wrong_release(self):
        # 第四轮②：活持有者暂停期间第二进程不得抢锁；释放只删自己的锁（token 校验）
        import importlib.util as iu5
        from pathlib import Path as P5
        import os as os5
        spec = iu5.spec_from_file_location('rh6', P5(self.env['TEST_HOOK']))
        mod = iu5.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P5(self.env['RESPITE_TURN_STATE'])
        old = os5.environ.get('RESPITE_TURN_STATE')
        try:
            os5.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            sid = 'locks'
            first = mod._map_lock(sid, wait_s=0.05)
            self.assertIsNotNone(first)
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))  # 无年龄抢占：等待超窗放弃
            self.assertIsNone(mod._map_lock(sid, wait_s=0.05))
            from pathlib import Path as _LP
            lp = _LP(first[0])
            lp.write_text('other-holder-token', encoding='utf-8')  # 后继持有者接管
            mod._release_lock(first)                                # token 不匹配：不删
            self.assertTrue(lp.exists())
            lp.write_text(first[1], encoding='utf-8')
            mod._release_lock(first)
            self.assertFalse(lp.exists())
        finally:
            if old is not None:
                os5.environ['RESPITE_TURN_STATE'] = old

    def test_stale_request_receipt_does_not_suppress_new_request(self):
        # 第三轮复核①：同会话 R1 写暂停 → R2 prompt → R1 完成——R1 凭证带旧 gen，不免催 R2
        import importlib.util as iu2
        from pathlib import Path as P2
        spec = iu2.spec_from_file_location('rh3', P2(self.env['TEST_HOOK']))
        mod = iu2.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P2(self.env['RESPITE_TURN_STATE'])
        import os as os2
        old = os2.environ.get('RESPITE_TURN_STATE')
        try:
            os2.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            sid = 'genbind'
            gen1 = mod.mark_prompt(sid)          # R1 请求开始
            # R1 的 remember 「暂停」——期间 R2 到来：
            gen2 = mod.mark_prompt(sid)          # R2 真实新请求（prompt_ts 推进）
            self.assertGreater(gen2, gen1)
            mod.mark_store(sid, gen1)            # R1 的写此刻才完成
            self.assertFalse(mod.turn_stored(sid))  # 免催已取消：任何磁盘凭证都不免催（复核⑥）
        finally:
            if old is not None:
                os2.environ['RESPITE_TURN_STATE'] = old

    def test_same_session_rmw_is_transactional(self):
        import time as _t
        # 第三轮复核②：旧进程已读快照 → 新 prompt 提交 → 旧进程写回——事务锁保证新 prompt 不回滚
        import importlib.util as iu2
        from pathlib import Path as P2
        spec = iu2.spec_from_file_location('rh4', P2(self.env['TEST_HOOK']))
        mod = iu2.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P2(self.env['RESPITE_TURN_STATE'])
        import os as os2, json as j2
        old = os2.environ.get('RESPITE_TURN_STATE')
        try:
            os2.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            sid = 'rmtx'
            mod.mark_prompt(sid)
            sp = P2(mod._state_path(sid))
            stale = j2.loads(sp.read_text(encoding='utf-8'))   # 旧进程读到旧快照
            gen2 = mod.mark_prompt(sid)                         # 新 prompt 提交（prompt_ts 前进）
            self.assertFalse(mod.turn_stored(sid))              # 新代未写：不免催
            # 事务锁保证：本进程持锁读改写期间，另一持锁进程不可能交错写回
            # （直接验证锁的互斥；外部无锁裸写不在插件控制面内）
            self.assertTrue(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen2}))
            self.assertFalse(mod.turn_stored(sid))              # 免催已取消（复核⑥）
            # 旧代凭证（gen1）完成后写回：store_req_ts 回到旧代 → 不免催新代（复审①交错）
            self.assertTrue(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': stale.get('prompt_ts', 0)}))
            self.assertFalse(mod.turn_stored(sid))
            # 持锁期间另一进程的 _map_update 保守放弃（新鲜锁不抢、等待超窗返回 False）
            lock = mod._map_lock(sid, wait_s=0.05)
            try:
                self.assertIsNotNone(lock)
                self.assertFalse(mod._map_update(sid, {'store_ts': 1.0, 'store_req_ts': stale.get('prompt_ts', 0)}))
            finally:
                mod._release_lock(lock)  # token 所有权释放
            # 解锁后正常更新可用（写入仅作诊断，不再免催）
            gen_now = mod._map_load(sid).get('prompt_ts')
            self.assertTrue(mod._map_update(sid, {'store_ts': _t.time(), 'store_req_ts': gen_now}))
            self.assertFalse(mod.turn_stored(sid))  # 免催已取消（复核⑥）
        finally:
            if old is not None:
                os2.environ['RESPITE_TURN_STATE'] = old

    def test_internal_prefix_prompt_does_not_rearm_latch(self):
        # 第三轮附注：内部 Recap 在 mark_prompt 之前过滤——真实请求 deny 后内部 Recap 不重武装
        import json as j3, subprocess as sp3, sys as sy3
        from pathlib import Path as P3
        cfg_skip = {'rsrs': j3.loads(P3(self.config).read_text(encoding='utf-8'))['rsrs'],
                    'session_rules': True, 'store_nudge_every': 1,
                    'skip_prefixes': ['Host internal recap']}
        cfgp = P3(self.config).parent / 'skipcfg.json'
        cfgp.write_text(j3.dumps(cfg_skip), encoding='utf-8')
        def call_skip(event, prompt, session):
            payload = j3.dumps({'prompt': prompt, 'hook_event_name': event,
                                'stop_hook_active': False, 'session_id': session})
            env = {k: v for k, v in self.env.items()}
            env['RESPITE_CONFIG'] = str(cfgp)
            r = sp3.run([sy3.executable, self.env['TEST_HOOK']], input=payload, text=True,
                        capture_output=True, env=env, cwd=str(cfgp.parent), timeout=30)
            return r.stdout.strip()
        self.assertIn('block', call_skip('Stop', '', 's9'))                 # 真实请求后的 Stop：deny（落锁）
        self.assertEqual(call_skip('UserPromptSubmit', 'Host internal recap: summary', 's9'), '')  # 内部 Recap：无输出
        self.assertEqual(call_skip('Stop', '', 's9'), '')                    # 锁未被内部 Recap 重武装：放行

    def test_stop_never_queries_engine(self):
        # 复核整改：Stop 完全不再查询引擎——无归属的全库时间抑制已移除（B 会话写入不会误免催 A），
        # 也没有任何「查库失败强迫续跑」的路径；任何 list 模式（recent/failed/malformed）行为一致
        for mode in ('ok', 'recent', 'failed', 'malformed'):
            self.call(f'request before stop {mode}')
            self.assertEqual(json.loads(self.call(event='Stop', mode=mode))['decision'], 'block', mode)
        self.assertEqual([a[0] for a in self.recorded()].count('list'), 0)

    def test_latch_is_per_session_and_permanent_until_new_prompt(self):
        # A→B→A：B 的新请求不得消耗/解除 A 的一次收尾锁（会话隔离）
        self.call('session A first request', session='A')
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')
        self.call('session B unrelated request', session='B')
        self.assertEqual(json.loads(self.call(event='Stop', session='B'))['decision'], 'block')
        self.assertEqual(self.call(event='Stop', session='A'), '')  # A 未再收到新请求：锁仍在
        self.call('session A second request', session='A')          # 只有 A 的新请求重新武装
        self.assertEqual(json.loads(self.call(event='Stop', session='A'))['decision'], 'block')

    def test_turn_state_is_per_session_no_shared_map(self):
        # 复核2轮#1（屏障）：共享 turn_map 的跨进程 RMW 已从结构上消灭——每会话独立
        # st_<sidkey>.json。旧交错 B-load(旧) → A-update(新) → B-write 不再可能：
        # B 的任意写只落 B 自己的文件。断言 A 的状态文件在 B 任意写后逐字节不变、
        # 共享 map 不再被创建、A 新 prompt 后旧 store 不再免催、A 新凭证不被 B 抹掉。
        import importlib.util as iu
        import time as _t
        spec = iu.spec_from_file_location('rh_ps', self.env['TEST_HOOK'])
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = Path(tempfile.mkdtemp(prefix='zcode-psstate-'))
        self.addCleanup(shutil.rmtree, base, True)
        old = os.environ.get('RESPITE_TURN_STATE')
        os.environ['RESPITE_TURN_STATE'] = str(base)
        try:
            now = _t.time()
            # A 旧轮：prompt_ts=now-100、store=now-50（同代凭证，仍新鲜）+ gen 标记同步
            self.assertTrue(mod._map_update('A', {'prompt_ts': now - 100, 'store_ts': now - 50,
                                                  'store_req_ts': now - 100}))
            self.assertTrue(mod._write_gen_marker('A', now - 100))
            self.assertFalse(mod.turn_stored('A'))  # 免催已取消（复核⑥）
            a_path = base / ('st_' + mod._sid_key('A') + '.json')
            self.assertTrue(a_path.is_file())
            raw_before = a_path.read_bytes()
            # B 端任意写（含模拟「B 持旧快照后写回」：B 的写从不触碰 A 的文件）
            mod.mark_prompt('B')
            mod.mark_store('B')
            mod._map_update('B', {'prompt_ts': now - 999, 'store_ts': now - 999})
            self.assertEqual(a_path.read_bytes(), raw_before)   # A 文件逐字节不变
            self.assertFalse((base / 'turn_map.json').exists())  # 共享 map 已不存在
            # A 新真实请求：旧代凭证不免催；B 的写不影响该判定
            genA2 = mod.mark_prompt('A')
            self.assertFalse(mod.turn_stored('A'))
            mod.mark_store('B')
            self.assertFalse(mod.turn_stored('A'))
            # A 当前代写入凭证不被 B 更新抹掉（另一方向的反向覆盖也曾丢凭证致多余催存）
            mod.mark_store('A', genA2)
            self.assertFalse(mod.turn_stored('A'))  # 免催已取消
            mod.mark_prompt('B')
            mod.mark_store('B')
            self.assertFalse(mod.turn_stored('A'))
        finally:
            if old is not None:
                os.environ['RESPITE_TURN_STATE'] = old
            else:
                os.environ.pop('RESPITE_TURN_STATE', None)

    def test_latch_survives_age_and_unwritable_state_fails_open(self):
        # 锁不设 TTL：25 小时前的锁仍然占用（只有新 prompt 重新武装）；状态目录不可写 → fail-open 放行
        import importlib.util as iu
        from pathlib import Path as P
        spec = iu.spec_from_file_location('rh', P(self.env['TEST_HOOK']))
        mod = iu.module_from_spec(spec); spec.loader.exec_module(mod)
        base = P(self.env['RESPITE_TURN_STATE'])
        import os
        old = os.environ.get('RESPITE_TURN_STATE')
        try:
            os.environ['RESPITE_TURN_STATE'] = str(base)
            base.mkdir(parents=True, exist_ok=True)
            self.assertTrue(mod.latch_claim('aged'))
            for f in base.glob('.latch_*'):
                f.write_text(json.dumps({'ts': 1}), encoding='utf-8')  # 1970 年的锁
            self.assertFalse(mod.latch_claim('aged'))
        finally:
            if old is not None:
                os.environ['RESPITE_TURN_STATE'] = old
        # 目录被同名文件挡住 → 无法落锁 → Stop 放行（绝不无锁 block）
        blocker = base.parent / 'blocker-file'
        blocker.write_text('not a dir', encoding='utf-8')
        env_backup = self.env.get('RESPITE_TURN_STATE')
        try:
            import subprocess as sp, sys
            payload = json.dumps({'prompt': '', 'hook_event_name': 'Stop',
                                  'stop_hook_active': False, 'session_id': 'nowhere'})
            cfg = json.loads(P(self.config).read_text(encoding='utf-8'))
            r = sp.run([sys.executable, self.env['TEST_HOOK']],
                       input=payload, text=True, capture_output=True, timeout=30,
                       env={**{k: v for k, v in self.env.items() if k != 'RESPITE_TURN_STATE'},
                            'RESPITE_TURN_STATE': str(blocker / 'sub')})
            self.assertEqual(r.stdout.strip(), '')
        finally:
            pass

    def test_stop_after_hook_store_queries_nothing_but_still_nudges(self):
        # 复核⑥：磁盘凭证免催已取消——Stop 不查引擎，但也不凭旧记录免催（仍催一次）
        self.call('store: durable fixture fact', direct_store=True)
        before = self.recorded()
        self.assertTrue(json.loads(self.call(event='Stop'))['decision'], 'block')
        self.assertEqual(self.recorded(), before)  # 零引擎查询

    def test_turn_receipt_suppression_is_request_scoped(self):
        # 复核⑥：磁盘凭证免催已取消——Stop 不凭旧记录免催；同请求二次 Stop 由 latch 放行
        self.call('store: durable fixture fact', direct_store=True)
        self.assertTrue(json.loads(self.call(event='Stop'))['decision'] == 'block')  # 仍催
        self.assertEqual(self.call(event='Stop', active=True), '')                   # latch：同请求一次
        self.call('another ordinary input without storing')
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
        self.call('store: durable fixture fact', session='a', direct_store=True)
        self.assertEqual(json.loads(self.call(event='Stop', session='b'))['decision'], 'block')

    def test_malformed_spy_cannot_pass_positive_control(self):
        self.positive_control()
        self.assertIn('Memory: unavailable', self.call('ordinary input', mode='malformed'))
        self.assertIn('parse_error', self.log.read_text(encoding="utf-8"))


def assert_versions(root):
    market=json.loads((root/'.claude-plugin/marketplace.json').read_text(encoding='utf-8'))
    entries=[entry for entry in market['plugins'] if entry['name']=='respire']
    manifest=json.loads((root/'.zcode-plugin/plugin.json').read_text(encoding='utf-8'))
    hook=re.search(r'^VERSION = "([^"]+)"',(root/'hooks/respire.py').read_text(encoding='utf-8'),re.M).group(1)
    ps=re.search(r"^\$VERSION = '([^']+)'",(root/'scripts/respire.ps1').read_text(encoding='utf-8-sig'),re.M).group(1)
    if len(entries)!=1 or ps!=manifest['version'] or hook!=manifest['version'] or ('version' in entries[0] and entries[0]['version']!=manifest['version']):
        raise ValueError('Plugin/hook/marketplace version mismatch')

class VersionConsistency(unittest.TestCase):
    def test_versions_match(self):
        assert_versions(ROOT)

    def test_each_mismatch_is_rejected(self):
        for component in ('marketplace','manifest','hook','ps'):
            with self.subTest(component=component), tempfile.TemporaryDirectory(prefix='version-negative-') as directory:
                fixture=Path(directory)
                for name in ('.claude-plugin', '.zcode-plugin', 'hooks', 'scripts'):
                    shutil.copytree(ROOT/name,fixture/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                if component=='hook':
                    path=fixture/'hooks/respire.py'
                    path.write_text(re.sub(r'^VERSION = "[^"]+"','VERSION = "999.0.0"',path.read_text(encoding='utf-8'),count=1,flags=re.M),encoding='utf-8')
                elif component=='ps':
                    path=fixture/'scripts/respire.ps1'
                    path.write_text(re.sub(r"^\$VERSION = '[^']+'", "$VERSION = '999.0.0'",path.read_text(encoding='utf-8-sig'),count=1,flags=re.M),encoding='utf-8')
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
