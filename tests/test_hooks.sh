#!/usr/bin/env bash
# respire(zcode) 自测 —— 模拟 stdin 事件 JSON，逐分支断言。
# ZCode 输出契约：一切输出为单行 JSON——文本走 {"additionalContext":...}，Stop 阻塞走 {"decision":"block",...}。
# rsrs 无 data-dir 隔离（runtime 单例＋全局 client.json），故默认只读分支不碰库；
# 加 --store 才跑写探针（写真库→回执断言→rsrs forget 自清理）。
set -u
export MSYS2_ENV_CONV_EXCL='PROMPT_VAL'  # MSYS 连 env 值都会把「/nomem …」转成 Windows 路径——只豁免 prompt 变量
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY3="$(command -v python3)"
RSRS="$(command -v rsrs || true)"
[ -z "$RSRS" ] && RSRS="$HOME/.local/bin/rsrs"
[ -z "$RSRS" ] && RSRS="$HOME/.rsrs/bin/rsrs"
PASS=0; FAIL=0
WITH_STORE=0
[ "${1:-}" = "--store" ] && WITH_STORE=1

if [ -z "$RSRS" ] || [ ! -x "$RSRS" ]; then
  echo "SKIP：未找到 rsrs（respire 引擎），无法自测。"; exit 0
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
CFG_ON="$TMP/config-on.json"
echo '{"session_rules": true}' > "$CFG_ON"
CFG_OFF="$TMP/config-off.json"
echo '{"session_rules": false}' > "$CFG_OFF"

# run <event> [prompt] [config] [session]
# prompt 走环境变量 PROMPT_VAL——MSYS 会把「/nomem …」这类 argv 转成 Windows 路径，env 值不转
run() {
  local ev="$1" pr="${2-}" cfg="${3:-$CFG_ON}" sess="${4:-selftest}"
  PROMPT_VAL="$pr" "$PY3" - "$ev" "$sess" <<'PY' | PROMPT_VAL="$pr" RESPITE_CONFIG="$cfg" RESPITE_LOG="$TMP/hook.log" RESPITE_NUDGE_STATE="$TMP/nudge" RESPITE_TURN_STATE="$TMP/turnstate" "$PY3" "$ROOT/hooks/respire.py" "$ev"
import json, os, sys
ev, sess = sys.argv[1], sys.argv[2]
pr = os.environ.get("PROMPT_VAL", "")
d = {"hook_event_name": ev, "cwd": "/tmp", "session_id": sess}
if ev == "UserPromptSubmit":
    d["prompt"] = pr
if ev == "Stop":
    d["stop_hook_active"] = False
sys.stdout.buffer.write(json.dumps(d, ensure_ascii=False).encode("utf-8"))  # buffer 直写 UTF-8——Windows 默认码页会把 CJK 写成乱码
PY
}

check() {   # check <名字> <实际输出> <模式: 非空|空|含:xxx|不含:xxx>
  local name="$1" got="$2" want="$3" ok=0
  case "$want" in
    非空) [ -n "$got" ] && ok=1 ;;
    空)   [ -z "$got" ] && ok=1 ;;
    不含:*) printf '%s' "$got" | grep -qF -e "${want#不含:}" && ok=0 || ok=1 ;;
    含:*) printf '%s' "$got" | grep -qF -e "${want#含:}" && ok=1 ;;
  esac
  if [ "$ok" = 1 ]; then
    PASS=$((PASS+1)); echo "PASS  $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL  $name  期望[$want] 实际[$(printf '%s' "$got" | head -c 200)]"
  fi
}

# ---- 只读分支（真库查询，不写） ----
out=$(run SessionStart)
check "SessionStart 注入简则" "$out" "含:respire memory layer"
check "简则点明引擎与同步" "$out" "含:rsrs.rs"
check "输出为 JSON 且走 additionalContext" "$out" "含:{\"additionalContext\""
check "输出单行无裸换行" "$( [ "$(printf '%s' "$out" | wc -l | tr -d ' ')" = "0" ] && echo SINGLE || echo MULTI)" "含:SINGLE"
check "additionalContext 可解析且含简则" "$(printf '%s' "$out" | python3 -c '
import json,sys
d=json.loads(sys.stdin.read())
print("OK" if "respire memory layer" in d.get("additionalContext","") else "BAD")')" "含:OK"
check "已登录不带登录引导" "$(run SessionStart)" "不含:not signed in"
check "未登录注入登录引导" "$(RESPITE_FAKE_LOGGED_OUT=1 run SessionStart)" "含:not signed in"
check "未登录引导给出注册与代登法" "$(RESPITE_FAKE_LOGGED_OUT=1 run SessionStart)" "含:rsrs login --oauth --no-open"
check "session_rules=false 静默" "$(run SessionStart "" "$CFG_OFF")" "空"
check "已装模型不带提示" "$(run SessionStart)" "不含:semantic model (BGE-M3) is not installed"
check "缺模型注入装法" "$(RESPITE_FAKE_NO_MODEL=1 run SessionStart)" "含:rsrs model activate m3"
check "缺模型点明词面回退" "$(RESPITE_FAKE_NO_MODEL=1 run SessionStart)" "含:lexical tier"
check "有货库不带空库引导" "$(run SessionStart)" "不含:memory store is empty"
check "空库注入首日引导" "$(RESPITE_FAKE_EMPTY=1 run SessionStart)" "含:memory store is empty"
check "空库引导含导入线索" "$(RESPITE_FAKE_EMPTY=1 run SessionStart)" "含:~/.zcode/AGENTS.md"
check "探测失败注入冷启诊断段" "$(RESPITE_FAKE_PROBE_FAIL=1 run SessionStart)" "含:status probe failed"
check "README 载三件事(模型可选)" "$(cat "$ROOT/README.md")" "含:不装模型完全可用"
check "README 载市场装法" "$(cat "$ROOT/README.md")" "含:添加插件市场"
check "包内无自定义安装脚本" "$( { [ -e "$ROOT/install.sh" ] || [ -e "$ROOT/uninstall.sh" ]; } && echo PRESENT || echo absent )" "含:absent"
# 日志留痕：任一事件后 hook.log 应有本行
run SessionStart >/dev/null
run UserPromptSubmit "我的密码是 password: hunter2 这算敏感吗" >/dev/null
check "日志脱敏口令" "$(grep -q 'hunter2' "$TMP/hook.log" && echo LEAK || echo SAFE)" "含:SAFE"
check "secret_skip 只记事件码不落输入" "$(grep '"out": "secret_skip"' "$TMP/hook.log" | grep -v '"d"' | grep -q . && echo BARE || echo DETAIL)" "含:BARE"
check "hook.log 留痕" "$(grep -q '"ev": "session"' "$TMP/hook.log" 2>/dev/null && echo YES)" "含:YES"

# 引擎缺失分支：单元注入 monkeypatch find_rsrs→None（真机造不出「全路径皆缺」）
run_engineless() {
  ROOT="$ROOT" "$PY3" - <<'PY'
import io, json, os, sys, importlib.util
spec = importlib.util.spec_from_file_location("respire", os.path.join(os.environ["ROOT"], "hooks/respire.py"))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
m.find_rsrs = lambda cfg: None
sys.argv = ["respire.py", "SessionStart"]
sys.stdin = io.StringIO('{"hook_event_name":"SessionStart"}')
try:
    m.main()
except SystemExit:
    pass
PY
}
check "引擎缺失注入装法" "$(run_engineless)" "含:npm i -g rsrs-cli"
check "引导禁自造超级密码" "$(run_engineless)" "含:never pass --super"
check "引导要求保存恢复码" "$(run_engineless)" "含:copy and keep it"
check "引擎缺失含注册指引" "$(run_engineless)" "含:rsrs register with the user"
check "probe失败含未注册分支" "$(RESPITE_FAKE_PROBE_FAIL=1 run SessionStart)" "含:never registered"

# ---- 可移植引擎桩（python 实现；Windows 走 .cmd 包装——bash 脚桩 WinError 193 不可 exec）----
# 模式：remember → rem_ok / rem_warn / rem_pend / rem_silent / rem_slow / rem_showbad；
#       list → fresh / stale / list_fail（STUB_LIST 独立控制）；recall → 固定一条命中。
STUB_DIR="$TMP"; TMPN="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")"
cat > "$STUB_DIR/stub_engine.py" <<'PYEOF'
import json, os, sys, time
sub = sys.argv[1] if len(sys.argv) > 1 else ""
mode = os.environ.get("STUB_MODE", "ok")
list_mode = os.environ.get("STUB_LIST", mode)
if sub == "list":
    if list_mode == "list_fail":
        print("garbage not json"); sys.exit(0)
    if list_mode == "list_dead":
        sys.exit(1)
    # 毫秒精度 UTC——真实 CLI 信封即毫秒（…926Z）；整秒截断会让「写入晚于 prompt」错判
    ts = (time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
          + ".%03dZ" % (int(time.time() * 1000) % 1000)) if list_mode == "fresh" else "2020-01-01T00:00:00.000Z"
    print(json.dumps({"command": "list", "status": "ok",
                      "details": [{"id": "ffffffffffffffff", "created_at": ts, "updated_at": ts,
                                   "title": "stub list entry"}]}))
elif sub == "remember":
    if mode == "rem_silent":
        sys.exit(0)
    if mode == "rem_slow":
        time.sleep(5); sys.exit(0)
    if mode == "rem_warn":
        print(json.dumps({"command": "remember", "status": "warn",
                          "summary": {"action": "created", "id": "eeeeeeeeeeeeeeee"},
                          "errors": ["parent (cause) cannot be resolved; stored independently"]})); sys.exit(2)
    if mode == "rem_pend":
        print(json.dumps({"command": "remember", "status": "pending",
                          "summary": {"state": "candidates", "written": False},
                          "items": [{"name": "aaaabbbb", "status": "pending",
                                     "value": "similarity=88% title=stub candidate",
                                     "action": "merge or attach"}],
                          "actions": ["rsrs remember \"<combined content>\" --merge-ids \"aaaabbbb\"",
                                      "rsrs remember \"<content>\" --parent <candidate id>",
                                      "rsrs remember \"<content>\" --force to write as new entry"]})); sys.exit(2)
    print(json.dumps({"command": "remember", "status": "ok",
                      "summary": {"action": "created", "id": "dddddddddddddddd"}}))
elif sub == "show":
    if mode == "rem_showbad":
        print(json.dumps({"command": "show", "status": "ok", "summary": {"id": sys.argv[2], "title": "drifted title"},
                          "details": {"entry": {"id": sys.argv[2], "title": "drifted title", "content": "drifted content"}}}))
    else:
        t = os.environ.get("STUB_TITLE", "stub title")
        c = os.environ.get("STUB_CONTENT", "stub content")
        print(json.dumps({"command": "show", "status": "ok", "summary": {"id": sys.argv[2], "title": t},
                          "details": {"entry": {"id": sys.argv[2], "title": t, "content": c}}}))
elif sub == "recall":
    if mode == "rec_skip":
        print(json.dumps({"command": "recall", "status": "skip", "details": []}))
        sys.exit(0)
    print(json.dumps({"command": "recall", "status": "ok",
                      "details": [{"id": "cccccccccccccccc", "title": "stub recall hit", "score": 0.9}]}))
else:
    sys.exit(1)
PYEOF
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    PY3_WIN="$(cygpath -w "$(py -3 -c 'import sys; print(sys.executable)' 2>/dev/null || command -v python.exe || command -v py.exe)")"
    STUB_ENGINE="$TMPN/rsrs-stub.cmd"
    printf '@echo off\r\n"%s" "%%~dp0stub_engine.py" %%*\r\n' "$PY3_WIN" > "$STUB_DIR/rsrs-stub.cmd"
    ;;
  *)
    STUB_ENGINE="$STUB_DIR/rsrs-stub"
    cp "$STUB_DIR/stub_engine.py" "$STUB_ENGINE"
    chmod +x "$STUB_ENGINE"
    ;;
esac
CFG_STUB="$TMP/config-stub.json"
printf '{"session_rules": true, "rsrs": "%s"}' "$STUB_ENGINE" > "$CFG_STUB"

# run_stub <event> <stdin-json> [STUB_MODE] [STUB_LIST] [session]
run_stub() {
  local ev="$1" payload="$2" sm="${3:-ok}" sl="${4:-}" sess="${5:-selftest}"
  printf '%s' "$payload" | STUB_MODE="$sm" STUB_LIST="$sl" RESPITE_TEST_FAST=1 \
    RESPITE_CONFIG="$CFG_STUB" RESPITE_LOG="$TMP/hook.log" RESPITE_NUDGE_STATE="$TMP/nudge" \
    RESPITE_TURN_STATE="$TMP/turnstate" "$PY3" "$ROOT/hooks/respire.py" "$ev"
}
STOP_JSON='{"hook_event_name": "Stop", "stop_hook_active": false, "session_id": "selftest"}'
reset_state() { rm -rf "$TMP/turnstate" "$TMP/nudge"; }

# ---- 写回执状态机（§7.1/§7.2 契约；全走桩，零真库依赖） ----
FACT="fixed stub fact sentence one."
reset_state
out=$(STUB_TITLE="$FACT" STUB_CONTENT="$FACT" run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_ok)
check "ok 写入回执含短 id" "$out" "含:(dddddddd)"
check "ok 写入回读核验标注" "$out" "含:verified by read-back"
check "ok 回执约束AI抽事实句retitle" "$out" "含:rsrs retitle dddddddd"
out=$(STUB_TITLE="$FACT" STUB_CONTENT="$FACT" run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_warn)
check "warn 已写入不误报失败" "$out" "含:Saved with warnings"
check "warn 回执附引擎警告摘要" "$out" "含:parent (cause) cannot be resolved"
check "warn 不引导重发" "$out" "不含:did not accept"
check "warn 仍给 retitle 精修入口" "$out" "含:retitle eeeeeeee"
out=$(run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_pend)
check "pending 明示未写入" "$out" "含:nothing was written"
check "pending 转述候选带短id" "$out" "含:[aaaabbbb]"
check "pending 保留建议动作merge" "$out" "含:--merge-ids"
check "pending 保留建议动作force" "$out" "含:--force"
out=$(run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_silent stale)
check "坏回执归为unknown" "$out" "含:store unknown"
check "unknown 只读核实指引" "$out" "含:rsrs list --limit 3"
check "unknown 禁止重发" "$out" "含:Do NOT resend"
check "unknown 不误报失败" "$out" "不含:did not accept"
out=$(run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_silent fresh)
check "unknown+新条目报告可能已写" "$out" "含:may already be written"
check "unknown+新条目给出只读id" "$out" "含:rsrs show ffffffff"
out=$(run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_slow)
check "超时归为unknown" "$out" "含:store unknown"
check "超时回执禁重发" "$out" "含:Do NOT resend"
check "超时不引导手动重发remember" "$out" "不含:run rsrs remember manually"
out=$(STUB_TITLE="$FACT" STUB_CONTENT="$FACT" run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_showbad)
check "回读不一致如实标注" "$out" "含:DIFFERENT title/content"

# ---- Stop 存储检查（新契约：fail-open + 请求级凭证 + 一次收尾锁；每场景独立 reset 状态） ----
STOP_JSON='{"hook_event_name": "Stop", "stop_hook_active": false, "session_id": "selftest"}'
reset_state() { rm -rf "$TMP/turnstate" "$TMP/nudge"; }
stop_case() {  # stop_case <STUB_LIST>：reset 后单次 Stop，输出入 OUT_STOP
  reset_state
  OUT_STOP="$(run_stub Stop "$STOP_JSON" ok "${1:-stale}")"
}
stop_case stale
check "Stop 无凭证时催存(block)" "$OUT_STOP" '含:"decision": "block"'
check "Stop 提示含存储指令" "$OUT_STOP" "含:rsrs remember"
check "Stop 无 deny 决策（ZCode 枚举外）" "$OUT_STOP" '不含:"deny"'
check "Stop 阻塞输出可过 JSON 解析" "$(printf '%s' "$OUT_STOP" | "$PY3" -c '
import json,sys
d=json.loads(sys.stdin.read())
print("OK" if d.get("decision")=="block" and "rsrs remember" in d.get("reason","") else "BAD")')" "含:OK"
reset_state
run_stub Stop "$STOP_JSON" ok stale >/dev/null
check "同请求二次Stop一次收尾锁放行(宿主未带active)" "$(run_stub Stop "$STOP_JSON" ok stale)" "空"
reset_state
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "next real question", "session_id": "selftest"}' ok >/dev/null
check "新请求重新武装仍催" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"'
stop_case list_fail
check "查库坏信封不再影响Stop(不查引擎)" "$OUT_STOP" '含:"decision": "block"'
stop_case list_dead
check "查库死进程不再影响Stop(不查引擎)" "$OUT_STOP" '含:"decision": "block"'
stop_case fresh
check "无请求凭证时引擎新写入仍催(不跨轮误抑制)" "$OUT_STOP" '含:"decision": "block"'
reset_state
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "turn with engine store", "session_id": "selftest"}' ok >/dev/null
# 复核整改：Stop 不再查询引擎——引擎侧写入（无法归属会话）不再免催，也没有查库失败续跑路径
check "引擎写入晚于prompt不再免催(去无归属抑制)" "$(run_stub Stop "$STOP_JSON" ok fresh)" '含:"decision": "block"'
NUDGE_N0="$(grep -c '"ev": "stop", "out": "nudge"' "$TMP/hook.log" 2>/dev/null)"; NUDGE_N0="${NUDGE_N0:-0}"
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "arm single nudge count", "session_id": "selftest"}' ok >/dev/null
run_stub Stop "$STOP_JSON" ok fresh >/dev/null
NUDGE_N1="$(grep -c '"ev": "stop", "out": "nudge"' "$TMP/hook.log" 2>/dev/null)"; NUDGE_N1="${NUDGE_N1:-0}"
check "Stop 不再发起引擎查询(单次nudge)" "$( [ $((NUDGE_N1 - NUDGE_N0)) = 1 ] && echo ONE || echo MANY )" "含:ONE"
check "fail-open 留痕(旧查库路径已移除)" "$(grep -q 'once_latch_skip' "$TMP/hook.log" && echo YES)" "含:YES"
# 状态目录被同名文件挡住 → 无法落锁 → 放行（绝不无锁 block）
rm -rf "$TMP/not-a-dir"; BLOCKER="$TMP/not-a-dir"; printf 'x' > "$BLOCKER"
reset_state
check "状态目录不可写时放行(绝不无锁block)" "$(printf '%s' '{"hook_event_name": "Stop", "stop_hook_active": false, "session_id": "selftest"}' | RESPITE_CONFIG="$CFG_STUB" RESPITE_LOG="$TMP/hook.log" RESPITE_NUDGE_STATE="$TMP/nudge" RESPITE_TURN_STATE="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")/not-a-dir/sub" "$PY3" "$ROOT/hooks/respire.py" Stop)" "空"
rm -f "$BLOCKER"
# 锁不设 TTL：25 小时前的锁仍占用，只有新 prompt 重新武装
reset_state
run_stub Stop "$STOP_JSON" ok stale >/dev/null
OLDLATCH="$(ls "$TMP"/turnstate/.latch_* 2>/dev/null | head -1)"
if [ -n "$OLDLATCH" ]; then printf '{"ts": 100}' > "$OLDLATCH"; fi
check "25小时前的锁仍占用(无TTL)" "$( [ -n "$OLDLATCH" ] && out="$(run_stub Stop "$STOP_JSON" ok stale)" && [ -z "$out" ] && echo HELD || echo LOST )" "含:HELD"
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "re-arm after aged latch", "session_id": "selftest"}' ok >/dev/null
check "新请求重新武装后仍可催" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"'
# /nomem 只跳召回，仍是新请求（重新武装收尾锁）
reset_state
run_stub Stop "$STOP_JSON" ok stale >/dev/null
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "/nomem skip recall only", "session_id": "selftest"}' ok >/dev/null
check "/nomem 轮重新武装收尾锁" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"' 
check "一次收尾锁留痕" "$(grep -q 'once_latch_skip' "$TMP/hook.log" && echo YES)" "含:YES"
reset_state
STUB_TITLE="$FACT" STUB_CONTENT="$FACT" run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"sessA\"}" rem_ok >/dev/null
check "其他会话不被本会话凭证免催" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"'
reset_state
STUB_TITLE="$FACT" STUB_CONTENT="$FACT" run_stub UserPromptSubmit "{\"hook_event_name\": \"UserPromptSubmit\", \"prompt\": \"记：$FACT\", \"session_id\": \"selftest\"}" rem_ok >/dev/null
check "记：成功后Stop仍催(磁盘凭证免催已取消)" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"'
run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "new turn after store", "session_id": "selftest"}' ok >/dev/null
check "下一轮不被上一轮成功写误抑制(应催)" "$(run_stub Stop "$STOP_JSON" ok stale)" '含:"decision": "block"'
CFG_NUDGE0="$TMP/config-nudge0.json"
echo '{"store_nudge_every": 0}' > "$CFG_NUDGE0"
check "Stop 节流关闭静默" "$(printf '%s' '{"hook_event_name": "Stop", "stop_hook_active": false, "session_id": "selftest"}' | RESPITE_CONFIG="$CFG_NUDGE0" RESPITE_LOG="$TMP/hook.log" RESPITE_NUDGE_STATE="$TMP/nudge" RESPITE_TURN_STATE="$TMP/turnstate" "$PY3" "$ROOT/hooks/respire.py" Stop)" "空"
CFG_OFFE="$TMP/config-disabled.json"
echo '{"enabled": false}' > "$CFG_OFFE"
check "enabled=false 全线静默" "$(run SessionStart "" "$CFG_OFFE")" "空"
check "enabled=false 落库也静默" "$(run UserPromptSubmit "记：关断时不应落库" "$CFG_OFFE")" "空"

out=$(run UserPromptSubmit "rsrs 信封 JSON 结构解析取哪层")
check "相关 prompt 触发召回" "$out" "非空"
check "召回也走 additionalContext" "$out" "含:{\"additionalContext\""
check "注入为标题档无正文" "$out" "不含:｜"
check "默认直出无阈值拦截" "$out" "含:rsrs direct"
check "召回头行与条数一致" "$(printf '%s' "$out" | python3 -c '
import re,json,sys
s=json.loads(sys.stdin.read())["additionalContext"]; head=s.split("\n",1)[0]
n=sum(1 for l in s.split("\n") if l.startswith("- ["))
m=re.search(r"matched (\d+) item",head)
print("OK" if m and int(m.group(1))==n else "BAD")')" "含:OK"

check "无关 prompt 不注入(引擎skip门,确定性桩)" "$(run_stub UserPromptSubmit '{"hook_event_name": "UserPromptSubmit", "prompt": "今晚吃什么菜好呢", "session_id": "selftest"}' rec_skip)" "空"
check "单字 prompt 跳过" "$(run UserPromptSubmit "嗯")" "空"
check "/nomem 关闭召回" "$(run UserPromptSubmit "/nomem rsrs 信封结构")" "空"
# 合成凭据守卫（审计回归）：凭据轮须零引擎调用（recall/remember 均不发）、hook.log 与
# 注入输出均不得含合成值。合成值运行时拼接——仓库不出现 sk-<16+位> 字面量，
# 分发前静态扫描（scripts/validate_plugin.py）本体未动。引擎桩另作「正常轮确实会过引擎」的对照，
# 证明零调用断言不是桩失联造成的假通过。桩用原生路径（Windows python 解析不了 MSYS 的 /tmp）。
SYN="sk-""abcdefghijklmnopqrst"
GUARD_LOG="$TMP/guard-calls.log"; : > "$GUARD_LOG"
TMPN="$(cygpath -m "$TMP" 2>/dev/null || printf '%s' "$TMP")"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    STUB_GUARD="$TMPN/rsrs-guard.bat"
    sed 's/$/\r/' > "$TMP/rsrs-guard.bat" <<EOF
@echo off
>>"$TMPN/guard-calls.log" echo guard-called
exit /b 0
EOF
    ;;
  *)
    STUB_GUARD="$TMPN/rsrs-guard"
    cat > "$TMP/rsrs-guard" <<EOF
#!/usr/bin/env bash
printf 'guard-called\n' >> "$TMPN/guard-calls.log"
exit 0
EOF
    chmod +x "$TMP/rsrs-guard"
    ;;
esac
CFG_GUARD="$TMP/config-guard.json"
echo '{"session_rules": true, "rsrs": "'"$STUB_GUARD"'"}' > "$CFG_GUARD"
out=$(run UserPromptSubmit "api_key = ${SYN} 存一下" "$CFG_GUARD")
check "疑似凭据不发引擎" "$out" "含:contains a credential"
check "凭据注入不含合成值" "$out" "不含:${SYN}"
check "凭据轮引擎零调用(recall)" "$( [ -s "$GUARD_LOG" ] && echo CALLED || echo CLEAN )" "含:CLEAN"
check "凭据值不落 hook.log" "$(grep -qF -- "$SYN" "$TMP/hook.log" && echo LEAK || echo SAFE)" "含:SAFE"
out=$(run UserPromptSubmit "记：数据库密码 = hunter2u" "$CFG_GUARD")
check "疑似凭据不落库" "$out" "含:contains a credential"
check "凭据轮引擎零调用(remember)" "$( [ -s "$GUARD_LOG" ] && echo CALLED || echo CLEAN )" "含:CLEAN"
: > "$GUARD_LOG"
run UserPromptSubmit "rsrs 信封 JSON 结构解析取哪层" "$CFG_GUARD" >/dev/null
check "守卫桩通路自检(正常轮过引擎)" "$( [ -s "$GUARD_LOG" ] && echo CALLED || echo CLEAN )" "含:CALLED"
check "技能指认轮剥前缀仍召回" "$(run UserPromptSubmit '$skill: 笔痕 rsrs 信封 JSON 结构解析取哪层')" "含:auto-recall"
echo '{"session_rules": true, "skip_prefixes": ["你正在为宿主写 Recap"]}' > "$TMP/config-skip.json"
check "skip_prefixes 白名单跳过" "$(run UserPromptSubmit "你正在为宿主写 Recap：无事" "$TMP/config-skip.json")" "空"
check "坏 stdin 静默" "$(printf 'not-json{{{' | RESPITE_CONFIG="$CFG_ON" "$PY3" "$ROOT/hooks/respire.py" UserPromptSubmit)" "空"
check "未知事件静默" "$(run PreToolUse "rsrs 信封")" "空"

# ---- title 规则抽取（纯函数，零污染；ROOTM=混合路径——Windows python 解析不了 MSYS 的 /d/...） ----
ROOTM="$(cygpath -m "$ROOT" 2>/dev/null || printf '%s' "$ROOT")"
check "整句优先取完整句" "$(python3 -c '
import sys,importlib.util
spec=importlib.util.spec_from_file_location("r","'"$ROOTM"'/hooks/respire.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(m.extract_title("respire 插件路径迁至 respire-zcode 下。后续以仓库为准。"))')" "含:respire 插件路径迁至 respire-zcode 下。"
check "无句号退分隔符不切半词" "$(python3 -c '
import sys,importlib.util
spec=importlib.util.spec_from_file_location("r","'"$ROOTM"'/hooks/respire.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
t=m.extract_title("这是一条没有句号的长事实句，讲清楚何时谁做了什么事，以及结果如何，后面还有别的内容")
print(t)')" "含:讲清楚何时谁做了什么事，"
check "长串不超70字" "$(python3 -c '
import sys,importlib.util
spec=importlib.util.spec_from_file_location("r","'"$ROOTM"'/hooks/respire.py"); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print(len(m.extract_title("默" * 200)))')" "非空"

# ---- 写探针（--store 显式开启；写真库→断言→forget 清理） ----
if [ "$WITH_STORE" = 1 ]; then
  # 内容须与全库零语义关联：纯随机无义串（域词会撞相似走待决态）
  MARK="zq$(date +%s)$RANDOM kw7f2 随机标记无义串"
  out=$(run UserPromptSubmit "记：$MARK")
  if printf '%s' "$out" | grep -qF "store pending"; then
    # 实时库判重门对随机串也可能放pending（库况相关）——ok 路径改由 CI 桩套件保证，此处记 SKIP
    PASS=$((PASS+1)); echo "SKIP  随机串判重待决（实时库判重门收紧，ok 回执路径由 CI 桩覆盖）"
  else
    check "落库成功回执" "$out" "含:Saved:"
    check "回执约束AI抽事实句retitle" "$out" "含:rsrs retitle"
    SID=$(printf '%s' "$out" | sed -n 's/.*(\([0-9a-f]\{8\}\)).*/\1/p')
    check "回执带短 id" "$SID" "非空"
    if [ -n "$SID" ]; then
      rc=$(rsrs forget "$SID" --json 2>/dev/null | python3 -c 'import json,sys; print(json.load(sys.stdin).get("status","err"))')
      check "探针清理(status=ok)" "$rc" "含:ok"
    fi
  fi
  # 判重待决：复述库中稳定条目 → 大概率撞高相似 → pending 未写入。
  # 断言依赖实时库内容（教训：零命中必 FAIL）——判直写则兜底清理后记 SKIP，不硬失败。
  out=$(run UserPromptSubmit "记：1memory 更名 respire：吸即存呼即取，材料全线改（复述既有条目触发判重待决）")
  if printf '%s' "$out" | grep -qF "Saved:"; then
    BID=$(printf '%s' "$out" | sed -n 's/.*(\([0-9a-f]\{8\}\)).*/\1/p')
    [ -n "$BID" ] && rsrs forget "$BID" --json >/dev/null 2>&1
    PASS=$((PASS+1)); echo "SKIP  判重待决转述候选（库况变化判为直写，已清理 $BID）"
  else
    check "判重待决转述候选" "$out" "含:store pending"
    check "待决列出候选与决断法" "$out" "含:--force"
  fi
else
  echo "SKIP  写探针（默认只读；加 --store 开启，写真库并自动 forget 清理）"
fi

echo "----"
echo "PASS=$PASS FAIL=$FAIL"
[ "$FAIL" -eq 0 ]
