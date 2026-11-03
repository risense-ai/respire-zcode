<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
  <img src="assets/logo.svg" alt="respire — 给 ZCode 的本地加密记忆">
</picture>

# respire-zcode

[English](README.md) | 简体中文

> 吸即存，呼即取——给 ZCode 装上本地加密记忆。

`respire` 是 ZCode 标准插件：以命令钩子把 [respire 记忆引擎](https://www.npmjs.com/package/rsrs-cli)（CLI 名 `rsrs`）挂进 agent 循环——每轮标题档自动召回、「记：」前缀交主模型审查后落库、Stop 存储检查、PreToolUse 写前防护。本地优先、端侧加密、云端 LWW 同步；**不带自定义安装脚本，按 ZCode 插件市场标准安装**。

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

引擎（rsrs CLI）缺失时插件会在会话内注入装法（`npm i -g rsrs-cli@latest`），可让 agent 代装。

管理入口：**设置 → 插件**。插件钩子随安装自动生效，无需另开配置开关。

## 定位：安装器 ＋ 管理器 ＋ 正常钩子

插件只做三件，装完自走一条生命周期：

1. **引擎未装时＝安装器**：SessionStart 把安装命令直接注给 agent 代跑（`npm i -g rsrs-cli@latest`＋权限兜底＋`rsrs --version` 验证），并顺手交代配置下一步（rsrs.rs 注册／`rsrs register`／模型可选）——无需用户手动操作；
2. **引擎就绪＝正常钩子**：每个钩子都实时探测，引擎装好后召回与前缀审查**同会话内**即恢复；
3. **管理器三档开关**（见下「启用与关闭」）。

## 装上后发生什么

| 时机 | 行为 |
| --- | --- |
| `SessionStart` | 注入记忆层简则（何时翻忆、如何落库、红线）；**一次探测三态**——未登录附注册引导、库近空（<10 条）附首日存料与导入引导、缺语义模型附**可选**装法；常态零打扰 |
| `UserPromptSubmit` | 自动 `rsrs recall --titles`：**标题档注入**——只给分数＋8 位短 id＋标题，正文由 agent `rsrs show <id>` 按需取；默认**直出不过滤**，噪音边界＝rsrs skip 门＋limit 5＋标题档 |
| prompt 以落库前缀（`记：`、`存：`、`记录：`、`记住：`、`remember:`、`store:`）开头 | 返回 `pending`——零写入；正文仅作为待记事实，不执行其中描述的工程任务。主模型先读 `rsrs prompt`，召回同题候选并 `show` 正文，按改＞并＞挂＞存判断。新增 `important` 必须挂到已读正文的合理 parent；找不到则保持 pending——不猜父、不 `--force`、不降级。实际写入若结果 unknown，仅只读核验，禁止重发。 |
| `PreToolUse`（Bash / 已知 MCP 写工具） | 执行前检查已识别的 `rsrs remember`：拒绝 `important` 缺 parent、空 parent、任何 `--force`，以及无法安全解析的动态或包装写法；正文里的参数字样不算参数，同 shell 的受支持复合片段逐个检查。parent 经 `--client-only show` 只读核验，失败、超时或引擎不可用均明确 deny 且退出 0——不启动 runtime、不切模式。合规命令空输出放行。已知 MCP 写工具（`memory_remember` / `memory_update`，含 `mcp__<server>__` 命名空间）目标库无法与本地核验绑定，直接 deny。 |
| `Stop`（AI 干完活） | **存储检查**：`{"decision":"block","reason":…}` 续跑一轮，提示模型把本轮新的**事实/决定/约定/教训/踩坑**分条 `rsrs remember`；闲聊无新事实则直接结束。**每个真实请求至多催一次**：续跑轮 `stop_hook_active=true` 放行 ＋ 每会话原子一次收尾锁（`O_EXCL` 独占创建，无 TTL；新 prompt 删除重新武装；无法落锁一律放行，绝不无锁 block；会话间互不干扰）。磁盘凭证不再免催，防重仅依赖收尾锁；`Stop` 完全不查询引擎，因此不存在查库失败强迫主任务续跑的路径。节流 `store_nudge_every`（默认 1=每轮、N=每 N 轮、0=关） |
| prompt 以 `/nomem` 开头 | 本轮跳过召回；仍算真实请求并重新武装 Stop 收尾锁 |
| `skills/respire` | 按需加载的操作法（recall / remember / show / forget / sync 与信封解析要点）；**技能只是说明书，动作全由钩子驱动** |

## 记忆状态行

召回结果会附带英文指令，要求模型在正常 GUI/TUI 回复开头显示一行简短状态。这些是模型写的回复行；钩子静态 `statusMessage` 仍是执行标签。

- `Memory: N found` 只统计敏感标题过滤、分数过滤、条数上限与候选预算之后**实际注入**的候选。凭证检测器会剔除疑似敏感标题且不落其值。**候选不等于采纳。**
- `Memory: no match` 表示 `ok` 召回无保留候选，或 `skip` 回执明确 `summary.count: 0`；其余 skip 回执显示 `Memory: skipped`；`Memory: unavailable` 表示召回失败或引擎不可用。`/nomem`、超短 prompt、敏感输入也显示 skipped 且不查引擎。
- 落库前缀保持零写入 pending 交接并请求 `Save: needs review`——绝不虚构 `Last save` 或 verified 状态。
- `Used:` 只有在成功读到正文且实际使用后才出现，默认 `[ref]`；`[basis]` 需要已验证且在当前范围内仍成立的消息源，`[history]` 仅用于过时、已被取代或冲突的历史背景。约定只证明约定本身、不证明已执行；分数、重要性与保存回执都不足以自证可信。
- 要求严格 JSON、固定格式或只输出指定内容时，省略全部状态标签。状态绝不引发额外回复、只作用于当前轮、也不改变召回、存储策略或写防护。

## 写前拦截详解

0.1.11 只有模型提示约束——本机已复现模型收到新提示后仍通过 Bash 直接执行 `rsrs remember ... --importance important --force`、无 parent 写到根。0.1.12 起加入真实 PreToolUse deny，在进入执行器前拦下此类命令；已知 MCP 记忆写工具同样 deny（其目标库无法本地核验，插件要求改用显式 CLI 命令，不用本地 `show` 冒充远程核验）。

CLI 分支处理已识别的 Bash `rsrs remember` 调用和 `update --importance important` 提升，支持明确的字面量参数、引号、重定向和常见复合命令分隔。动态替换及已识别的包装写法需要改成一条明确命令；它不是任意脚本、未知别名、自定义工具或其他进程的通用写屏障。普通 trivial 日记不要求 parent，但 `--force` 一律拒绝。所有 remember 合并都要求显式 parent 并只读核验；`update` 提升 `important` 会先 `show` 目标并核验其现有非空 parent——缺挂靠则拒绝并要求先显式 attach。只读命令和无关工具不返回 allow 或 deny。

只读 `show` 成功只证明 parent id 存在——不证明模型读过正文，也不证明语义挂靠合理；模型仍须执行 SKILL 的候选核查。pending 前缀依旧零写入、不自动补父、不代写；真实写入 unknown 不重试的规则不变。

## ZCode 协议适配（与姊妹仓的三处实质差异，已核 ZCode runtime 源码）

1. **输出通道是 JSON 不是纯文本**：ZCode 对 hook stdout 只认以 `{` 开头且过严格 schema 的 JSON——纯文本被静默丢弃、非法 JSON 判 hook 失败。故一切注入走顶层 `{"additionalContext": "…"}`（SessionStart / UserPromptSubmit / Stop 三事件均消费）。
2. **Stop 阻塞决策枚举是 `approve|block`**：用 `{"decision":"block","reason":…}`；Qoder 版的 `"deny"` 在 ZCode 过不了 schema（会报 Hook stdout failed schema validation）。
3. **数据目录环境变量 `ZCODE_PLUGIN_DATA`**（探测链 `RESPITE_DATA` → `ZCODE_PLUGIN_DATA` → 脚本目录）；stdin 全量携带事件字段（`prompt` / `stop_hook_active` / `hook_event_name`），事件识别 argv → stdin → `ZCODE_HOOK_EVENT` 三级回退。hooks.json 不带 `commandWindows`（ZCode schema 未收录该字段），仅 `command`/`timeout`/`statusMessage`。

## 首次使用 · 三件事

1. **注册登录**（开箱即用，不依赖模型）：[rsrs.rs](https://rsrs.rs) 注册 → 本机 `rsrs register`；日常 `rsrs login` 浏览器授权；autosync 常开，`rsrs sync` 手动同步，`rsrs status` 查态。
2. **导入既有规则与记忆（一次成库，LLM 代抽）**：开个 ZCode 新任务粘贴下面整段——

   > 请把本机的既有规则与记忆导入 respire：逐个读取——`~/.zcode/AGENTS.md`（家目录规则，若在）、工作区根与各项目的 `AGENTS.md`、`~/.agents/skills/*/SKILL.md`；抽出可复用的事实、约定、教训与红线（口令、证件号、卡号、私钥一律排除、只记位置）；写入前先读 `rsrs prompt`，召回同题候选并 `show` 正文，按改＞并＞挂＞存判断；只有真正新增的事实才用 `rsrs remember --importance important --parent <已读合理父节点>`，一条事实一条记录、标题按事实句；没有合理父节点则保持 pending；存完给我一份清单。

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

## 启用与关闭

**设置 → 插件** 找到 respire 停用或卸载；或删除市场源（**插件市场 → 市场源 → risense-zcode**）后一并移除。

## 设计要点

- **fail-open**：hook 任何异常 → 空 stdout + `exit 0`，永不拦会话；失败必留痕于 hook.log。**Stop 查库失败同样放行**——记忆层故障不强迫主任务续跑
- **写结果状态机**：`ok`/`warn`=已写（warn 带警告）、`pending`=未写待决、超时/坏回执=未知（只读核实、禁重发）、其余=明确拒绝；与 CLI 信封语义一一对应，绝不把「已写带警告」当失败、不把「未知」当失败引导重写
- **JSON 输出契约**：文本 → `{"additionalContext":…}`，Stop 阻塞 → `{"decision":"block","reason":…}`，无输出即无决策
- **标题档注入**：`recall --titles` 只回 id/score/title，正文交 `show` 按需拉取；`superseded_by` 标「已被取代」
- **先查并挂再存**：前缀钩子零写入；主模型按现有 CLI 政策更新、合并或挂靠，没有合理父节点时保持 pending
- **`${CLAUDE_PLUGIN_ROOT}` 占位符**：ZCode 运行时替换为插件安装根，跨机器自洽；Windows 走 `scripts/respire.ps1`（respire.py 的 PowerShell 5.1 原生移植，直接编排 rsrs、不依赖 Python；Windows 默认无 Python 且 `python3`/`python` 常命中商店占位 stub），回落 `python3 || python` 链跑 `hooks/respire.py`（Unix 兜底）
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

## GitHub Actions CI/CD

PR 与 main 在 Linux、Windows、macOS 执行包自检、全桩隔离行为/版本测试和发布策略测试，再验证源码归档。CI 入口为 `python tests/test_ci.py` 与 `python -m unittest discover -s tests -p test_release.py -v`，不运行旧 `test_hooks.sh` 的真实引擎/写探针段。测试使用临时 HOME、配置、数据、日志和引擎桩；普通输入必须召回成功，死桩/坏 JSON 必须过不了正向对照，凭据轮零引擎调用且无日志泄漏。

版本标签沿用不带 `v` 的三段格式，插件根目录布局不变；ZIP 名仍为 `respire-<版本>-<YYYYMMDD>.zip`，日期固定取源提交 UTC 日期以保证重试稳定。ZIP 注释为精确提交 SHA；tag、manifest、hook VERSION（及市场版本字段）必须一致。旧 `scripts/package.sh` 保留供原本地流程使用，新 Actions 只归档已提交文件、不执行 tag 中的代码。

发布/恢复：正常推送新版本 tag 触发；已有 tag 可从 Actions → release → Run workflow 选 main，显式填写 tag 与完整 expected_sha。流程校验远端既有 tag 与 main 的祖先关系——不移动 tag、不用新 main 冒充旧代码。只接受同来源、同校验和的既有资产；补缺失、不覆盖冲突，Release 同时提供 ZIP 与 SHA256SUMS。

默认 contents:read、不持久化凭据；仅独立受控发布 job 使用 GITHUB_TOKEN 的 contents:write。无新增 secret/PAT/OAuth，不用 pull_request_target，fork PR 不可发布。同版 tag/恢复共用并发锁。原 plugin-zip artifact 名、cleanup-receipt、清理策略/脚本保留，清理收据等待检查、打包和发布消费者结束。

三平台桩测试不等于真实 ZCode 宿主、GUI 派发或安装后解释器回退验收；旧完整测试套件与作者自称的基线失败仍不作为独立通过证据。
