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
FAKE_RECALL_SKIP = '{"status":"skip"}'

# fake rsrs 只按子命令回固定信封；remember 的 status 由 RESPITE_FAKE_STORE_STATUS 切换
FAKE_CMD = r"""@echo off
set "SUB=%~1"
if /i "%SUB%"=="remember" goto rem
if /i "%SUB%"=="show" goto show
if /i "%SUB%"=="status" (echo {STATUS_OK})
if /i "%SUB%"=="list" (echo {LIST_EMPTY})
if /i "%SUB%"=="recall" (echo {RECALL_SKIP})
echo {{"status":"fail","errors":["fake: unknown %SUB%"]}}
exit /b 1
:rem
if "%RESPITE_FAKE_STORE_STATUS%"=="pending" (echo {PENDING})
if "%RESPITE_FAKE_STORE_STATUS%"=="ok" (echo {OK})
exit /b 0
:show
echo {SHOW_DIFF}
exit /b 0
""".replace("{STATUS_OK}", FAKE_STATUS_OK).replace("{LIST_EMPTY}", FAKE_LIST_EMPTY) \
   .replace("{RECALL_SKIP}", FAKE_RECALL_SKIP).replace("{PENDING}", FAKE_PENDING) \
   .replace("{OK}", FAKE_OK).replace("{SHOW_DIFF}", FAKE_SHOW_DIFF)

FAKE_SH = """#!/bin/sh
case "$1" in
  remember)
    if [ "$RESPITE_FAKE_STORE_STATUS" = "pending" ]; then
      echo '%s'
    else
      echo '%s'
    fi ;;
  show) echo '%s' ;;
  status) echo '%s' ;;
  list) echo '%s' ;;
  recall) echo '%s' ;;
  *) echo '{"status":"fail","errors":["fake: unknown"]}' ; exit 1 ;;
esac
exit 0
""" % (FAKE_PENDING, FAKE_OK, FAKE_SHOW_DIFF, FAKE_STATUS_OK, FAKE_LIST_EMPTY, FAKE_RECALL_SKIP)


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
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "随便问一句"})
        self.assertEqual(out, "")

    def test_nomem_prefix_skips(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "/nomem 查一下"})
        self.assertEqual(out, "")

    def test_short_prompt_silent(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t", "prompt": "hi"})
        self.assertEqual(out, "")

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
        doc = json.loads(out)
        self.assertIn("【respire · stored】Saved", doc["additionalContext"])
        self.assertIn(FAKE_SID[:8], doc["additionalContext"])
        # 状态文件：与 respire.py 同命名（sha1(respire-turn-v2:<sid>)[:16]），prompt/store 双凭证
        sp = os.path.join(self.state, "st_%s.json" % expected_sidkey("t"))
        self.assertTrue(os.path.isfile(sp), "状态文件缺失: %s" % sp)
        with open(sp, encoding="utf-8") as f:
            st = json.load(f)
        self.assertIn("prompt_ts", st)
        self.assertIn("store_ts", st)
        self.assertIn("store_req_ts", st)

    def test_store_pending_receipt(self):
        out = self.run_hook("UserPromptSubmit",
                            {"hook_event_name": "UserPromptSubmit", "session_id": "t",
                             "prompt": "记：候选合并场景测试"}, fake_store_status="pending")
        doc = json.loads(out)
        self.assertIn("【respire · store pending】", doc["additionalContext"])
        self.assertIn("cand1", doc["additionalContext"])

    def test_stop_blocks_once_then_latch(self):
        out1 = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": False})
        doc = json.loads(out1)
        self.assertEqual(doc.get("decision"), "block")
        self.assertIn("Memory check", doc.get("reason", ""))
        out2 = self.run_hook("Stop", {"hook_event_name": "Stop", "session_id": "t", "stop_hook_active": False})
        self.assertEqual(out2, "")   # latch 已落：第二次放行

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


if __name__ == "__main__":
    unittest.main()
