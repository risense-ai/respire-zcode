# respire-zcode

> 吸即存，呼即取——给 ZCode 装上本地加密记忆。

`respire` 是 ZCode 标准插件：以命令钩子把 [respire（CLI 名 rsrs）](https://www.npmjs.com/package/@rsrsai/cli) 记忆引擎挂进 agent 循环——每轮标题档自动召回、「记：」一前缀即落库、Stop 存储检查。本地优先、端侧加密、云端 LWW 同步；**不带自定义安装脚本，按 ZCode 插件市场标准安装**。

姊妹仓：[respire-dimcode](https://github.com/risense-ai/respire-dimcode)（Dim）· [respire-qoder](https://github.com/risense-ai/respire-qoder)（Qoder）· respire-workbuddy（WorkBuddy）——四宿主共用同一钩子方案与打包口径，差异只在宿主协议适配。

## 不装模型完全可用（降级是一等公民）

- **注册、登录、同步、召回全不依赖端侧模型**——装完插件即可用，未装模型时引擎自动走词面档。
- BGE-M3 是**纯可选增强**：想要更好的语义召回再 `rsrs model install && rsrs model activate m3`，插件检测到未装会在会话内提示一句，装与不装都不报错、不拦路。

## 安装（ZCode 插件市场 · 本地目录源）

```bash
git clone https://github.com/risense-ai/respire-zcode.git && cd respire-zcode
python3 scripts/validate_plugin.py                     # 自检：结构/清单/hooks/敏感扫描
```

然后在本机 ZCode 客户端：

1. **插件市场 → 添加 → 添加插件市场**，粘贴本仓目录（市场根=仓根，清单在 `.claude-plugin/marketplace.json`）；
2. **个人 → risense-zcode → respire → 安装**；
3. **新会话**生效——SessionStart 注入简则即标志挂接成功。

引擎（rsrs CLI）缺失时插件会在会话内注入装法（`npm i -g @rsrsai/cli@latest`），可让 agent 代装。

管理入口：**设置 → 插件**。插件钩子随安装自动生效，无需另开配置开关。

## 定位：安装器 ＋ 管理器 ＋ 正常钩子

插件只做三件，装完自走一条生命周期：

1. **引擎未装时＝安装器**：SessionStart 把安装命令直接注给 agent 代跑（`npm i -g @rsrsai/cli@latest`＋权限兜底＋`rsrs --version` 验证），并顺手交代配置下一步（rsrs.rs 注册／`rsrs register`／模型可选）——无需用户手动操作；
2. **检测就绪＝自动切正常钩子**：每轮实时探测，引擎装完**同会话内**即恢复简则、召回与「记：」落库；
3. **管理器三档开关**（见下「启用与关闭」）。

## 装上后发生什么

| 时机 | 行为 |
| --- | --- |
| `SessionStart` | 注入记忆层简则（何时翻忆、如何落库、红线）；**一次探测三态**——未登录附注册引导、库空（<10 条）附首日存料与导入引导、缺语义模型附**可选**装法；常态零打扰 |
| `UserPromptSubmit` | 自动 `rsrs recall --titles`：**标题档注入**——只给分数＋8 位短 id＋标题，正文由 agent `rsrs show <id>` 按需取；默认**直出不过滤**，噪音边界＝rsrs skip 门＋limit 5＋标题档 |
| `prompt` 以「记：」「存：」「remember:」开头 | 直接 `rsrs remember … --importance important` 落库并回执；判后即存判为相似时**不写入**、回执转述候选（`--parent` 挂靠或 `--force` 直写），由模型决断；回执硬约束 AI 抽「主语＋动作＋结果」事实句 `retitle` 替换暂拟题 |
| `Stop`（AI 干完活） | **存储检查**：`{"decision":"block","reason":…}` 续跑一轮，提示模型把本轮新的**事实/决定/约定/教训/踩坑**分条 `rsrs remember`；闲聊无新事实则直接结束。防循环：续跑轮 stdin 带 `stop_hook_active=true` 即放行（ZCode 自身限续跑至多三次，本层一次即止）；节流 `store_nudge_every`（默认 1=每轮，N=每 N 轮，0=关）；近 10 分钟本库有过落库（问引擎 `list` 取最近 `updated_at`）则不再催 |
| `prompt` 以 `/nomem` 开头 | 本轮跳过召回 |
| `skills/respire` | 按需加载的操作法（recall/remember/show/forget/sync 与信封解析要点）；**注意技能只是说明书，动作全由钩子驱动** |

## ZCode 协议适配（与姊妹仓的三处实质差异，已核 ZCode runtime 源码）

1. **输出通道是 JSON 不是纯文本**：ZCode 对 hook stdout 只认以 `{` 开头且过严格 schema 的 JSON——纯文本被静默丢弃、非法 JSON 判 hook 失败。故一切注入走顶层 `{"additionalContext": "…"}`（SessionStart / UserPromptSubmit / Stop 三事件均消费）。
2. **Stop 阻塞决策枚举是 `approve|block`**：用 `{"decision":"block","reason":…}`；Qoder 版的 `"deny"` 在 ZCode 过不了 schema（会报 Hook stdout failed schema validation）。
3. **数据目录环境变量 `ZCODE_PLUGIN_DATA`**（探测链 `RESPITE_DATA` → `ZCODE_PLUGIN_DATA` → 脚本目录）；stdin 全量携带事件字段（`prompt` / `stop_hook_active` / `hook_event_name`），事件识别 argv → stdin → `ZCODE_HOOK_EVENT` 三级回退。hooks.json 不带 `commandWindows`（ZCode schema 未收录该字段），仅 `command`/`timeout`/`statusMessage`。

## 首次使用 · 三件事

1. **注册登录**（开箱即用，不依赖模型）：[rsrs.rs](https://rsrs.rs) 注册 → 本机 `rsrs register`；日常 `rsrs login` 浏览器授权；autosync 常开，`rsrs sync` 手动同步，`rsrs status` 查态。
2. **导入既有记忆与规则（一次成库，LLM 代抽）**：开个 ZCode 新任务粘贴下面整段——

   > 请把本机的既有规则与记忆导入 respire：逐个读取——`~/.zcode/AGENTS.md`（家目录规则，若在）、工作区根与各项目的 `AGENTS.md`、`~/.agents/skills/*/SKILL.md`；抽出可复用的事实、约定、教训与红线（口令、证件号、卡号、私钥一律排除、只记位置），去重后用 `rsrs remember` 分条存入（`--importance important`、标题按事实句；判重给候选先决断挂靠或合并），存完给我一份清单。

   空库首日 SessionStart 会注入同一线索。
3. **端侧模型（可选增强）**：`rsrs model install && rsrs model activate m3`——不装完全可用，想要更好语义召回再装。

## 调优（可选）

插件安装目录下 `hooks/respire.config.json`（缺失即全默认，改完新会话生效；**不涉及登录与账号**；模板见 `hooks/respire.config.example.json`）：

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `rsrs` | `""` | 引擎路径；空 = 自动探测（PATH → `~/.local/bin` → `~/.rsrs/bin`） |
| `recall_threshold` | `0.0` | 召回下限；**0=默认关（rsrs 直出）**，设正数才启用过滤 |
| `recall_limit` | `5` | 取前 N 条 |
| `min_prompt_chars` | `2` | 1 字才跳，2 字起即查 |
| `session_rules` | `true` | 是否注入 SessionStart 简则 |
| `budget_chars` | `1500` | 单轮注入总预算（标题行远短于此） |
| `enabled` | `true` | **总开关**：false=全线静默 |
| `store_nudge_every` | `1` | Stop 存储检查节流：1=每轮、N=每 N 轮、0=关（每轮=多一轮模型小调用） |
| `skip_prefixes` | `[]` | 宿主内部提示白名单：命中前缀的 prompt 不召回不落库（如宿主自动化 Recap） |
| `log` | `true` | 数据目录 `hook.log` 留痕（超 256KB 清轮） |

过滤策略：**默认不设阈值**——三层已框住噪音：rsrs skip 门、limit 5、标题档。历史教训：阈值每降一次都是真相关被拦的补救，漏召代价远大于多看两行标题。

## 卸载

**设置 → 插件** 找到 respire 停用或卸载；或删除市场源（**插件市场 → 市场源 → risense-zcode**）后一并移除。

## 设计要点

- **fail-open**：hook 任何异常 → 空 stdout + `exit 0`，永不拦会话；失败必留痕于 hook.log
- **JSON 输出契约**：文本 → `{"additionalContext":…}`，Stop 阻塞 → `{"decision":"block","reason":…}`，无输出即无决策
- **标题档注入**：`recall --titles` 只回 id/score/title，正文交 `show` 按需拉取；`superseded_by` 标「已被取代」
- **判后即存尊重设计**：落库不带 `--force`，`pending` 候选原样转述给模型决断
- **`${CLAUDE_PLUGIN_ROOT}` 占位符**：ZCode 运行时替换为插件安装根，跨机器自洽；command 带 `python3 || python` 回退链
- **包内自检**：`python3 scripts/validate_plugin.py`（结构/清单/hooks 形状/可编译/fail-open/ZCode 输出契约/敏感扫描），分发前必跑

## 已知边界

- **召回质量是引擎上限**：用词鸿沟下 BGE-M3 可能漏召真条——简则已约束模型「命中不贴题换词补查」（同义词/上位词/英文词分路）
- **冷启动窗**：runtime 冷启＋模型加载实测 7s+，故 hook timeout 20s、recall 14s、probe 10s；探测失败时 SessionStart 注入诊断段
- **钩子生效以新会话为准**：安装/更新后旧会话不热载；ZCode 限 Stop 续跑至多三次，本层每轮至多催一次
- **留痕**：数据目录 `hook.log` 每事件一行（ts/ev/out/ms/d 含 query 摘要），按行复盘「灵不灵」

## 测试

```bash
python3 scripts/validate_plugin.py   # 包结构自检
bash tests/test_hooks.sh             # 行为只读断言（简则/召回/清洗/引导/JSON 契约），不碰库
bash tests/test_hooks.sh --store     # 加写探针（写真库→回执→rsrs forget 自清理）
```

rsrs 无 data-dir 隔离（runtime 单例＋全局 client.json），故写测试仅在显式开启时进行，即写即忘。

## 发版

```bash
git tag 0.1.0 && git push origin 0.1.0   # tag 须等于 manifest version
# CI：validate + package → GitHub Release 自动挂 dist/respire-<ver>-<date>.zip
```

## License

MIT
