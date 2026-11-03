#!/usr/bin/env python3
# scripts/respire.ps1（PowerShell 原生 hook）的契约测试。
# 与 tests/test_hooks.sh（respire.py 靶）同口径，但靶是 PS 包装：
# 假 rsrs（Windows=.cmd / Unix=带 shebang 脚本）经 RESPITE_RSRS 注入，
# 不写真库；SessionStart 的模型态用 RESPITE_FAKE_NO_MODEL 后门固定。
# 无 PowerShell 可用的环境（如未装 pwsh 的 Linux）整体 SKIP，不失败。
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PS1 = os.path.join(ROOT, "scripts", "respire.ps1")

FAKE_SID = "abcdef0112345678abcdef0112345678"

FAKE_OK = '{"status":"ok","summary":{"id":"%s"},"errors":[]}' % FAKE_SID
FAKE_PENDING = ('{"status":"pending","items":[{"name":"cand1","value":"existing fact","action":"merge"}],'
                '"actions":["rsrs merge <id> --content ..."]}')
FAKE_STATUS_OK = '{"status":"ok","summary":{"session":{"has_token":true,"user":"tester"},"local_total":42}}'
FAKE_LIST_EMPTY = '{"status":"ok","details":[]}'
FAKE_SHOW_DIFF = ('{"status":"ok","summary":{"id":"%(id)s"},'
                  '"details":{"entry":{"id":"%(id)s","title":"DIFFERENT-TITLE","content":"different body"}}}'
                  ) % {"id": FAKE_SID}
FAKE_RECALL_SKIP = '{"status":"skip","summary":{"count":0}}'
FAKE_RECALL_HITS = "{\"status\":\"ok\",\"details\":[{\"id\":\"ffffffffffffffff\",\"title\":\"api_key: fixture-sensitive-title\",\"score\":0.99},{\"id\":\"aaaaaaaaaaaaaaaa\",\"title\":\"first\",\"score\":0.9},{\"id\":\"bbbbbbbbbbbbbbbb\",\"title\":\"second\",\"score\":0.8},{\"id\":\"cccccccccccccccc\",\"title\":\"below threshold\",\"score\":0.1}]}"
FAKE_SHOW_PARENTED = '{"status":"ok","summary":{"id":"TARGET_ID"},"details":{"entry":{"id":"TARGET_ID","parent_id":"aaaaaaaaaaaaaaaa"}}}'

# fake rsrs 只按子命令回固定信封；remember 的 status 由 RESPITE_FAKE_STORE_STATUS 切换
FAKE_CMD = r"""@echo off
if /i "%~1"=="--client-only" shift
set "SUB=%~1"
if /i "%SUB%"=="remember" goto rem
>>"%RESPITE_TEST_CALLS%" echo %SUB%
if /i "%SUB%"=="show" goto show
if /i "%SUB%"=="status" (echo {STATUS_OK})
if /i "%SUB%"=="list" (echo {LIST_EMPTY})
if /i "%SUB%"=="recall" goto recall
echo {{"status":"fail","errors":["fake: unknown %SUB%"]}}
exit /b 1
:recall
if "%RESPITE_FAKE_STORE_STATUS%"=="recall_skip_false" (echo {"status":"skip","summary":{"count":false}} & exit /b 0)
if "%RESPITE_FAKE_STORE_STATUS%"=="recall_skipped" (echo {"status":"skip"} & exit /b 0)
if "%RESPITE_FAKE_STORE_STATUS%"=="recall_hits" (echo {RECALL_HITS} & exit /b 0)
if "%RESPITE_FAKE_STORE_STATUS%"=="recall_fail" (echo {"status":"fail"} & exit /b 2)
echo {RECALL_SKIP}
exit /b 0
:rem
>>"%RESPITE_TEST_CALLS%" echo remember
if "%RESPITE_FAKE_STORE_STATUS%"=="pending" (echo {PENDING})
if "%RESPITE_FAKE_STORE_STATUS%"=="ok" (echo {OK})
exit /b 0
:show
if "%RESPITE_FAKE_STORE_STATUS%"=="parented_bad" if "%~2"=="aaaaaaaaaaaaaaaa" (echo {"status":"fail"} & exit /b 2)
if "%RESPITE_FAKE_STORE_STATUS%"=="parented_bad" (echo {SHOW_PARENTED} & exit /b 0)
if "%RESPITE_FAKE_STORE_STATUS%"=="parented" (echo {SHOW_PARENTED} & exit /b 0)
if "%RESPITE_FAKE_STORE_STATUS%"=="bad_parent" (echo {"status":"fail"} & exit /b 2)
echo {SHOW_DIFF}
exit /b 0
""".replace("{STATUS_OK}", FAKE_STATUS_OK).replace("{LIST_EMPTY}", FAKE_LIST_EMPTY) \
   .replace("{RECALL_HITS}", FAKE_RECALL_HITS).replace("{RECALL_SKIP}", FAKE_RECALL_SKIP).replace("{PENDING}", FAKE_PENDING) \
   .replace("{OK}", FAKE_OK).replace("{SHOW_DIFF}", FAKE_SHOW_DIFF).replace("{SHOW_PARENTED}", FAKE_SHOW_PARENTED.replace('TARGET_ID','%~2'))

FAKE_SH = """#!/bin/sh
if [ "$1" = "--client-only" ]; then shift; fi
echo "$1" >> "$RESPITE_TEST_CALLS"
case "$1" in
  remember)
    if [ "$RESPITE_FAKE_STORE_STATUS" = "pending" ]; then
      echo '%s'
    else
      echo '%s'
    fi ;;
  show) if [ "$RESPITE_FAKE_STORE_STATUS" = "bad_parent" ]; then echo '{"status":"fail"}'; elif [ "$RESPITE_FAKE_STORE_STATUS" = "parented" ]; then echo '%s' | sed "s/TARGET_ID/$2/g"; else echo '%s'; fi ;;
  status) echo '%s' ;;
  list) echo '%s' ;;
  recall) if [ "$RESPITE_FAKE_STORE_STATUS" = "recall_skip_false" ]; then echo '{"status":"skip","summary":{"count":false}}'; elif [ "$RESPITE_FAKE_STORE_STATUS" = "recall_skipped" ]; then echo '{"status":"skip"}'; elif [ "$RESPITE_FAKE_STORE_STATUS" = "recall_hits" ]; then echo '%s'; elif [ "$RESPITE_FAKE_STORE_STATUS" = "recall_fail" ]; then echo '{"status":"fail"}'; exit 2; else echo '%s'; fi ;;
  *) echo '{"status":"fail","errors":["fake: unknown"]}' ; exit 1 ;;
esac
exit 0
""" % (FAKE_PENDING, FAKE_OK, FAKE_SHOW_PARENTED, FAKE_SHOW_DIFF, FAKE_STATUS_OK, FAKE_LIST_EMPTY, FAKE_RECALL_HITS, FAKE_RECALL_SKIP)


def find_powershell():
    if sys.platform == "win32":
        return "powershell.exe"   # Windows 自带 PS 5.1（目标运行时）
    from shutil import which
    return which("pwsh")          # GitHub ubuntu/macos runner 自带 pwsh


def expected_sidkey(session):
    h = hashlib.sha1(("respire-turn-v2:" + (session or "~")).encode("utf-8"))
    return h.hexdigest()[:16]


class TestRespirePs1(unittest.TestCase):
    ps = None

    @classmethod
    def setUpClass(cls):
        cls.ps = find_powershell()
        if cls.ps:
            # 语法自检先行：无 BOM 的 UTF-8 会被 PS5 按 ANSI 误解——这里等价于真机加载检查
            probe = subprocess.run(
                [cls.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", PS1, "__NoSuchEvent__"],
                input="", capture_output=True, timeout=60)
            cls.assertFalse(cls, probe.returncode != 0, "respire.ps1 加载失败: %s" % probe.stderr[:400])

    def setUp(self):
        if not self.ps:
            self.skipTest("PowerShell 不可用")
        self.tmp = tempfile.mkdtemp(prefix="respire-ps1-test-")
        self.fake_dir = os.path.join(self.tmp, "fakebin")
        os.makedirs(self.fake_dir, exist_ok=True)
        if sys.platform == "win32":
            self.fake = os.path.join(self.fake_dir, "rsrs.cmd")
            with open(self.fake, "w", encoding="utf-8") as f:
                f.write(FAKE_CMD)
        else:
            self.fake = os.path.join(self.fake_dir, "rsrs")
            with open(self.fake, "w", encoding="utf-8") as f:
                f.write(FAKE_SH)
            os.chmod(self.fake, 0o755)
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state, exist_ok=True)

    def tearDown(self):
        try:
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)
        except Exception:
            pass

    def run_hook(self, event, data, fake_store_status="ok", engine=True, enabled_config=None):
        cfg_path = ""
        if enabled_config is not None:
            cfg_path = os.path.join(self.tmp, "respire.config.json")
            with open(cfg_path, "w", encoding="utf-8") as f:
                json.dump(enabled_config, f)
        env = dict(os.environ)
        env.update({
            "RESPITE_TEST_FAST": "1",
            "RESPITE_RSRS": self.fake if engine else "",
            "RESPIRE_BIN": "",
            "RESPITE_DATA": self.state,
            "RESPITE_TURN_STATE": self.state,
            "RESPITE_NUDGE_STATE": os.path.join(self.state, "nudge"),
            "RESPITE_LOG": os.path.join(self.state, "hook.log"),
            "RESPITE_FAKE_STORE_STATUS": fake_store_status,
            "RESPITE_TEST_CALLS": os.path.join(self.state, "engine-calls"),
            "RESPITE_CONFIG": cfg_path,
        })
        if not engine:
            # 摘掉引擎：收窄 PATH 并把 HOME 指向空临时目录，令 PATH/home 探测链全落空
            if sys.platform == "win32":
                env["PATH"] = os.environ.get("SystemRoot", r"C:\Windows") + r"\System32"
            else:
                env["PATH"] = "/usr/bin:/bin"
            env["USERPROFILE"] = self.tmp
            env["HOME"] = self.tmp
        proc = subprocess.run(
            [self.ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", PS1, event],
            input=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            capture_output=True, timeout=60, env=env)
        self.assertEqual(proc.returncode, 0, "exit 必须恒 0（fail-open）: %s" % proc.stderr[:300])
        return proc.stdout.decode("utf-8", "replace")

    # ---- 输出契约 ----

    def test_session_start_injects_rules(self):
        out = self.run_hook("SessionStart", {"hook_event_name": "SessionStart", "session_id": "t"})
        doc = json.loads(out)
        self.assertIn("additionalContext", doc)
        self.assertIn("【respire memory layer · attached】", doc["additionalContext"])
        self.assertNotIn("engine missing", doc["additionalContext"])

    def test_session_start_engine_missing(self):
        out = self.run_hook("SessionStart", {"session_id": "t"}, engine=False)
        doc = json.loads(out)
        self.assertIn("【respire · engine missing】", doc["additionalContext"])

    def test_recall_skip_is_silent(self):
        data = {"hook_event_name":"UserPromptSubmit", "session_id":"t", "prompt":"recall fixture query"}
        context = json.loads(self.run_hook("UserPromptSubmit", data))["additionalContext"]
        self.assertIn("Memory: no match", context.splitlines())
        for rule in ("strict JSON", "fixed format", "only-specified output", "including Used and unused",
                     "Candidates are not adoptions", "successfully reading a body and actually using it",
                     "Default to [ref]", "[basis]", "[history]", "not that it was carried out",
                     "most conservative label", "24 Unicode characters", "(title hidden)",
                     "Never show bodies, full IDs", "Memory: unused", "DO NOT invent Last save"):
            self.assertIn(rule, context)
        self.assertNotRegex(context, r"(?m)^(?:Used|Last save):")
        for cfg, expected in (({"recall_limit":2,"recall_threshold":0.5,"budget_chars":1000}, "Memory: 2 found"),
                              ({"recall_limit":2,"recall_threshold":0.5,"budget_chars":100}, "Memory: 1 found"),
                              ({"recall_limit":1,"recall_threshold":0.5}, "Memory: 1 found"),
                              ({"recall_threshold":0.99}, "Memory: no match")):
            output = self.run_hook("UserPromptSubmit", data, fake_store_status="recall_hits", enabled_config=cfg)
            context = json.loads(output)["additionalContext"]
            self.assertIn(expected, context.splitlines())
            self.assertNotIn("fixture-sensitive-title", context)
            self.assertNotIn("api_key:", context)
            self.assertNotRegex(context, r"(?m)^(?:Used|Last save):")
        for mode in ("recall_skipped", "recall_skip_false"):
            context = json.loads(self.run_hook("UserPromptSubmit", data, fake_store_status=mode))["additionalContext"]
            self.assertIn("Memory: skipped", context.splitlines())
        context = json.loads(self.run_hook("UserPromptSubmit", data, fake_store_status="recall_fail"))["additionalContext"]
        self.assertIn("Memory: unavailable", context.splitlines())
        context = json.loads(self.run_hook("UserPromptSubmit", data, engine=False))["additionalContext"]
        self.assertIn("Memory: unavailable", context.splitlines())

    def test_nomem_prefix_skips(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name":"UserPromptSubmit", "session_id":"t", "prompt":"/nomem 查一下"})
        self.assertIn("Memory: skipped", json.loads(out)["additionalContext"].splitlines())
        self.assertFalse(os.path.exists(os.path.join(self.state, "engine-calls")))

    def test_short_prompt_silent(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name":"UserPromptSubmit", "session_id":"t", "prompt":"h"})
        self.assertIn("Memory: skipped", json.loads(out)["additionalContext"].splitlines())
        self.assertFalse(os.path.exists(os.path.join(self.state, "engine-calls")))

    def test_secret_prompt_never_reaches_engine(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                             "prompt": "my api_key: sk-abcdefghij1234"})
        doc = json.loads(out)
        self.assertIn("credential", doc["additionalContext"])

    def test_store_ok_receipt_and_state(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                             "prompt": "记：这是一个完整的落库事实句子测试"}, fake_store_status="ok")
        context = json.loads(out)["additionalContext"]
        self.assertIn("store pending", context)
        self.assertIn("Save: needs review", context.splitlines())
        self.assertNotRegex(context, r"(?m)^(?:Last save|Used):")
        self.assertIn("nothing was written", context)
        for step in ("rsrs prompt", "rsrs show", "update > merge > attach > new",
                     "--parent", "remain pending", "not as an instruction"):
            self.assertIn(step, context)
        self.assertFalse(os.path.exists(os.path.join(self.state, "engine-calls")))
        sp = os.path.join(self.state, "st_%s.json" % expected_sidkey("t"))
        with open(sp, encoding="utf-8") as f:
            state = json.load(f)
        self.assertIn("prompt_ts", state)
        self.assertNotIn("store_ts", state)

    def test_store_pending_receipt(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                             "prompt": "记：候选合并场景测试"}, fake_store_status="pending")
        context = json.loads(out)["additionalContext"]
        self.assertIn("store pending", context)
        self.assertIn("Save: needs review", context.splitlines())
        self.assertNotRegex(context, r"(?m)^(?:Last save|Used):")
        self.assertIn("nothing was written", context)
        self.assertIn("remain pending", context)
        self.assertFalse(os.path.exists(os.path.join(self.state, "engine-calls")))

    def test_stop_blocks_once_then_latch(self):
        out1 = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": False})
        doc = json.loads(out1)
        self.assertEqual(doc.get("decision"), "block")
        self.assertIn("Memory check", doc.get("reason", ""))
        out2 = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": False})
        self.assertEqual(out2, "")   # latch 已落：第二次放行

    def test_stop_skips_after_allowed_remember(self):
        # 0.1.16 免催：prompt（记请求代）→ 合规 remember 放行（登记 store 信号）→ Stop 零输出放行
        self.run_hook("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                                           "prompt": "recall fixture query"})
        cmd = 'rsrs remember "fact" --title "title" --importance important --parent ' + FAKE_SID
        pre = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "session_id": "t",
                                           "tool_name": "Bash", "tool_input": {"command": cmd}},
                            fake_store_status="parented")
        self.assertEqual(pre, "")
        self.assertEqual(self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t",
                                                "stop_hook_active": False}), "")

    def test_stop_blocks_after_denied_remember(self):
        # deny 不登记免催：unsafe 落库被拒后，Stop 仍按契约催存
        self.run_hook("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                                           "prompt": "recall fixture query"})
        cmd = 'rsrs remember "fact" --title "title" --importance important --force'
        pre = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "session_id": "t",
                                           "tool_name": "Bash", "tool_input": {"command": cmd}})
        self.assertEqual(json.loads(pre)["hookSpecificOutput"]["permissionDecision"], "deny")
        out = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": False})
        self.assertEqual(json.loads(out).get("decision"), "block")

    def test_stop_skips_after_allowed_merge(self):
        # 0.1.17：merge 不进守卫拦截面（放行），但出现写动词即登记免催
        self.run_hook("UserPromptSubmit", {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                                           "prompt": "recall fixture query"})
        pre = self.run_hook("PreToolUse", {"hook_event_name": "PreToolUse", "session_id": "t",
                                           "tool_name": "Bash",
                                           "tool_input": {"command": 'rsrs merge abcdef0112345678 --content "merged fact"'}})
        self.assertEqual(pre, "")
        self.assertEqual(self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t",
                                                "stop_hook_active": False}), "")

    def test_stop_active_passes(self):
        out = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": True})
        self.assertEqual(out, "")

    def test_stop_engine_missing_silent(self):
        out = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t",
                                     "stop_hook_active": False}, engine=False)
        self.assertEqual(out, "")

    def test_disabled_config_is_silent(self):
        out = self.run_hook("SessionStart", {"session_id": "t"}, enabled_config={"enabled": False})
        self.assertEqual(out, "")

    def test_bad_event_silent(self):
        out = self.run_hook("__NoSuchEvent__", {"session_id": "t"})
        self.assertEqual(out, "")

        blocked = [
            'cd repo && rsrs remember "fact" --title "title" --importance important --force 2>&1 | head -80',
            'rsrs remember "body contains --parent abcdef0112345678abcdef0112345678" --importance important',
            'X=1 rsrs remember "fact" --importance important',
            '>out.log rsrs remember fact --importance important --force',
            'rsrs >out.log remember fact --importance important --force',
            'echo $(rsrs >out.log remember fact --importance important --force)',
            'bash -c "rsrs >out.log remember fact --importance important --force"',
            'rsrs --json >out.log remember fact --importance important --force',
            'rsrs remember fact --merge-ids abcdef0112345678abcdef0112345678',
            'rsrs remember fact --importance trivial --merge-ids abcdef0112345678abcdef0112345678',
            '>out.log 2>err.log rsrs remember fact --importance important --force',
            'echo $(rsrs remember fact --importance important --force)',
            'echo "$(rsrs remember fact --importance important --force)"',
            'echo `rsrs remember fact --importance important --force`',
            'npx rsrs remember fact --importance important --force',
            'npm exec rsrs remember fact --importance important --force',
            'py rsrs remember fact --importance important --force',
            'sudo rsrs remember fact --importance important --force',
            'timeout 5 rsrs remember fact --importance important --force',
            'rsrs remember "fact" --importance important --parent ""',
            'rsrs remember "fact" --importance=important --parent=',
            'rsrs remember "fact" --importance trivial --force',
            'rsrs remember "fact" --importance trivial; rsrs remember "other" --importance important',
            'bash -c "rsrs remember fact --importance important"',
            '(rsrs remember "fact" --importance important)',
            'rsrs remember "$fact" --importance important --parent abcdef0112345678abcdef0112345678',
            'rsrs remember "unfinished',
        ]
        for command in blocked:
            out = json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':command}}))
            self.assertEqual(out['hookSpecificOutput']['hookEventName'], 'PreToolUse')
            self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny', command)
            self.assertFalse(os.path.exists(os.path.join(self.state, 'engine-calls')))
        for command in ('echo "rsrs remember"', 'rsrs recall "fact" --json',
                        'rsrs recall remember --titles --json',
                        'rsrs --client-only --json recall remember --titles',
                        'rsrs --json --client-only candidates remember',
                        'rsrs --model-task-id audit --progress-id progress recall remember --json',
                        'npx rsrs recall remember --json',
                        'bash -c "rsrs recall remember --json"',
                        "echo '$(rsrs remember fact --importance important --force)'",
                        "echo '`rsrs remember fact --importance important --force`'",
                        'rsrs remember "diary" --importance trivial', 'rsrs remember "fact" --help'):
            self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':command}}), '', command)
        for prefix in ('--client-only --json', '--json --client-only', '--model-task-id audit --progress-id progress', '--progress-id=progress --model-task-id=audit --json'):
            out = json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':'rsrs ' + prefix + ' remember "fact" --importance important'}}))
            self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')
        command = 'rsrs remember "fact" --importance important --parent ' + FAKE_SID
        metadata = ' --model-task-id audit --progress-id progress --project Respire --tags plugin,parent --type context --summary "candidate summary" --source-refs "[]" --valid-until 2027-01-01T00:00:00.000Z --review-at 2027-01-01T00:00:00.000Z --artifact "{}" --computer TB16P --emotion -1 --supersedes ' + FAKE_SID + ' --see-also ' + FAKE_SID
        for suffix in (metadata, ' --clear-summary --clear-source-refs --clear-valid-until --clear-review-at --clear-artifact'):
            self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':'>out.log ' + command + suffix}}), '')
        for prefix in ('--client-only --json', '--json --client-only', '--model-task-id audit --progress-id progress', '--progress-id=progress --model-task-id=audit --json'):
            self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':'rsrs ' + prefix + ' remember "fact" --importance important --parent ' + FAKE_SID}}), '')
        self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':command}}), '')
        for wrapped in ('rsrs >out.log remember fact --importance important --parent ' + FAKE_SID,
                        'rsrs remember fact --emotion 1 >out.log --importance important --parent ' + FAKE_SID,
                        'rsrs remember ">" --importance important --parent ' + FAKE_SID,
                        'rsrs remember fact --merge-ids aaaaaaaaaaaaaaaa --parent ' + FAKE_SID):
            self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':wrapped}}), '')
        with open(os.path.join(self.state, 'engine-calls'), encoding='utf-8') as calls:
            self.assertEqual(calls.read().splitlines(), ['show'] * 11)
        promotion='rsrs update ' + FAKE_SID + ' --importance important --content "updated fact"'
        denied=json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':promotion}}))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertIn('attach', denied['hookSpecificOutput']['permissionDecisionReason'])
        self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':promotion}}, fake_store_status='parented'), '')
        for promotion in ('rsrs update --importance important ' + FAKE_SID, 'rsrs update --importance=important ' + FAKE_SID):
            denied=json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':promotion}}))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':promotion}}, fake_store_status='parented'), '')
        denied=json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':promotion}}, fake_store_status='parented_bad'))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':'rsrs update ' + FAKE_SID + ' --importance trivial'}}), '')
        denied = json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':command}}, fake_store_status='bad_parent'))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'Read','tool_input':{'command':command}}), '')
        self.assertEqual(self.run_hook('PreToolUse', {'tool_name':'mcp__other__memory_recall','tool_input':{'content':'fact'}}), '')
        with open(os.path.join(self.state, 'engine-calls'), encoding='utf-8') as calls:
            before = calls.read()
        for args in ({'content':'fact','importance':'important','force':True}, {'content':'fact','importance':'important','parent':FAKE_SID}):
            denied = json.loads(self.run_hook('PreToolUse', {'tool_name':'mcp__respire__memory_remember','tool_input':args}))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        for tool in ('memory_remember','mcp__rsrs__memory_remember','memory_update','mcp__rsrs__memory_update'):
            denied=json.loads(self.run_hook('PreToolUse', {'tool_name':tool,'tool_input':{'content':'fact'}}))
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')
        with open(os.path.join(self.state, 'engine-calls'), encoding='utf-8') as calls:
            self.assertEqual(calls.read(), before)
        denied = json.loads(self.run_hook('PreToolUse', {'tool_name':'Bash','tool_input':{'command':command}}, engine=False))
        self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')


if __name__ == "__main__":
    unittest.main()
