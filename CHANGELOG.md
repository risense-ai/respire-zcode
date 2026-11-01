# Changelog

## 0.1.7 — 2026-11-01 · 第五轮复核整改（标记写失败安全降级）

### Fixed

- **POISON 失效令牌（复核⑤）**：`mark_prompt` 不再忽略写失败——gen 标记或状态文件**任一写失败**时立即写 `+inf` 失效令牌（`_poison_marker`，走同一盲写路径）；`turn_stored` 对 POISON 标记或任何有限旧凭证返回 False——**本会话免催优化保持关闭**（宁可多催，不凭旧磁盘凭证免催）。磁盘满/短暂写故障恢复后，首个 mark_prompt 正常重写标记即恢复。测试覆盖：旧同代凭证→共同写失败→降级→不免催；正常登记恢复；POISON 写成功即关闭。

## 0.1.6 — 2026-11-01
## 0.1.6 — 2026-11-01 · 第四轮复核整改（登记失效安全 + 锁所有权 + 严格信封）

### Fixed

- **登记失败安全失效（复核①）**：新增 **gen 标记文件**（`st_<sid>.gen`，盲写 temp+rename——单值覆盖无读改写、不受事务锁竞争影响）。它 是「当前请求」的真值：`mark_prompt` 先写标记再更新状态文件；`turn_stored` 要求 状态文件 prompt_ts == 标记 == store_req_ts。新请求即使 `_map_update` 因锁超窗/写失败未登记，标记也已推进——**旧凭证立即失效，绝不错误免催**（测试：旧请求已存→持锁令新登记失败→释放→Stop 不免催；恢复路径 gen3 正常登记后免催恢复）。
- **锁所有权机制（复核②）**：移除 mtime 年龄抢占（5 秒锁龄不证明持有者已崩）；锁内容=唯一 token，`_release_lock` 只删除与自身 token 一致的锁——**不抢活锁、不删后继持有者的锁**（测试：活持有者期间第二进程等待超窗放弃 ×2；token 不匹配不删；token 匹配正常释放）。等待超窗放弃更新是安全的（配合 gen 标记）。
- **严格信封（复核③）**：`summary.id` 必须原生字符串（JSON 数字 12345678 不再 str() 强转）且匹配 UUID 或 16+ 位 hex（`a-------` 拒绝）→ unknown；回读**三方 id**（summary.id、entry.id 均===目标，原生字符串）+ title/content **原生字符串**（42≠"42"）——错 entry.id、缺失、非字符串正文一律 mismatch，Saved 保留。

### Changed

- 测试：CI 39/39（+2：登记失败失效+恢复、锁所有权不抢不误删；+严格信封数字 id/横线串/无 entry.id/数字正文四反例）。

## 0.1.5 — 2026-11-01
## 0.1.5 — 2026-11-01 · 第三轮复核整改（同会话请求隔离）

### Fixed

- **请求代凭证绑定（复核①）**：`mark_prompt` 返回请求代 gen；`do_store` 在调用入口捕获 gen，成功回执 `mark_store(session, gen)` 记 `store_req_ts`；`turn_stored` 要求 `store_req_ts == prompt_ts`——同会话旧请求（R1）的 remember 在新请求（R2）prompt 之后完成，凭证带 R1 的 gen，**不免催 R2**（屏障测试：R1 写暂停→R2 prompt→R1 完成→R2 不被免催；R2 自己的写→免催）。
- **同会话 RMW 事务锁（复核②）**：`_map_lock`——`O_CREAT|O_EXCL` 独占 lockfile（跨进程），`_map_update` 在锁内 读→改→temp+rename；陈旧锁兜底只看锁文件年龄（mtime>5s，持有者已崩），等待超窗放弃更新（保守方向：丢免催凭证→多一轮有界收催）。旧进程持旧快照写回不可能交错回滚新 prompt（持锁互斥测试）。
- **内部提示在 mark_prompt 之前过滤（复核附注）**：宿主内部 Recap 不是真实新请求——不记请求代、不重武装一次收尾锁（真实请求→deny→内部 Recap→Stop 不二次 deny，CI 专项测试）。

### Changed

- 测试：CI 37/37（+3：请求代绑定两向屏障、RMW 事务锁互斥/陈旧兜底、内部前缀不重武装）。

## 0.1.4 — 2026-11-01
## 0.1.4 — 2026-11-01 · 增量复审整改（PR #4 review round 2）

### Fixed

- **共享 turn_map 的跨进程 RMW 回滚（主项）**：删除共享 `turn_map.json`，改为**每会话独立状态文件** `st_<sidkey>.json`（`_map_update`/`_map_load` 只读写本会话文件，temp+rename 原子替换，头 `{"prompt_ts":…,"store_ts":…}`）——不存在跨会话覆盖面，任何交错都不可能回滚别的会话的请求凭证（旧实现 B 持旧快照写回会把 A 的 prompt_ts/store_ts 恢复成旧值，令 A 的 Stop 误认本轮已写而跳过检查）。64 会话收敛逻辑随之删除（每文件独立且极小，运行时产物已 gitignore）。
- **readback 坏 details 吞回执**：`show` 回读遇非字典 `details`（非空数组/字符串）时曾直接 `.get()` 抛 `AttributeError`，被 fail-open 吞掉后**已写回执（Saved）整个消失**；改为类型防护（`isinstance(det, dict)`）→ 非 dict 一律 `unavailable`，保留 Saved 回执。
- **monotonic 共享截止时间**：`do_store` 计时全部改用 `time.monotonic()`（deadline = t0 + `RESPITE_HOOK_BUDGET_S`（默认 20s）− 2.5s 输出余量），不受墙钟跳变影响；`remember` 子进程超时不再固定 `STORE_T`，取 `max(1, min(STORE_T, int(剩余)))`；剩余 ≤0 时不发 remember（零引擎调用），直接 unknown 回执。引擎时间戳归属锚点仍用墙钟（引擎侧输出即墙钟）。

### Changed

- 测试：CI 新增 4 项（per-session 状态文件隔离屏障——A 文件在 B 任意写后逐字节不变、A 新 prompt 后旧 store 不再免催、A 凭证不被 B 抹掉；坏 details 两反例——数组/字符串 details → Saved + unavailable 而非空输出；monotonic 预算下慢坏回执零追加调用（remember 超时=剩余预算）；预算耗尽零调用）。
- `.gitignore` 增 `st_*.json`（每会话状态文件，运行时产物）。

## 0.1.3 — 2026-11-01 · 维护者复核整改（PR #4 review）

### Fixed

- **一次收尾锁重构（复核#1）**：`.store_turn` 单会话状态改为**每会话独立锁文件**（`O_CREAT|O_EXCL` 原子独占——并发 Stop 只有一个能落锁；锁无 TTL，25 小时后仍占用，只有新真实 prompt 删除重新武装；A→B→A 交错不丢锁）；无法落锁（状态目录不可写等）一律放行——绝不无锁 block。prompt_ts/store_ts 存于尽力维护的 per-session map（temp+rename 原子替换，仅按数量收敛），map 失败只损失免催优化。
- **坏结构 list 不再当成功（复核#2）**：`details` 非数组、或非空却无可解析时间戳 → 按查询失败处理（不归属新条目给本次写入）。
- **共享 hook 预算（复核#3）**：remember/回读/只读核实共用截止时间（`RESPITE_HOOK_BUDGET_S`，默认 20s，预留 2.5s 输出余量）；慢坏回执后剩余不足直接 unknown，不再追加 list。
- **回执/回读加固（复核#4）**：`ok`/`warn` 缺有效 id（hex/uuid 白名单校验）、畸形 summary（类型防护不抛异常）、未知 status 一律归 **unknown**（禁重发）；`skip` 明确「引擎按模式拒绝，未写非失败」；`fail` 才断言未接受。回读改为**全量核验**：返回 id 必须=写入 id、标题相等、完整正文相等，才称 verified；否则 mismatch/unavailable 如实标注。
- **免催凭证可归属化（复核#5）**：移除「引擎全库最新写入晚于 prompt 即免催」（无法归属会话，B 写入会误免催 A）；`/nomem` 仍算新请求（mark 提前），只跳召回不跳收尾重武装。

### Changed

- 测试：CI 30/30（+复核要求反例：缺 id/垃圾 id/坏 summary→unknown、skip 回执、错 id/尾部篡改回读→mismatch、慢坏回执+紧预算→零追加调用、坏 schema list 不归属、A→B→A、锁无 TTL、状态不可写放行、Stop 零引擎查询）；bash 93/0（同步场景 + /nomem 重武装 + 不可写目录放行）。

## 0.1.2 — 2026-11-01
All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.2] - 2026-11-01

### Fixed

审计整改（Respire 十插件权威流程审计报告 2026-11-01，ZC-01～ZC-05）：

- **ZC-02 写结果状态机**：「记：」回执不再只认 `status=ok`——`warn`+有效 id 是**已写入带警告**（parent 未解析/post-remember hook 告警），如实回执并附错误摘要，绝不误报「未接受」、绝不引导重发（旧实现会把已提交数据当失败，诱发重复写）。
- **ZC-03 未知写结果只读核实**：超时/坏回执/无输出归为 **unknown**——回执明令「先 `rsrs list`/`rsrs show` 只读核实、禁止重发 remember」；秒回的坏回执还会自动 `list` 核对是否已落新条并报告可能已写（附只读 id）。旧文案「手动 rsrs remember 核实」已删（重写风险）。
- **ZC-01 Stop fail-open**：查库 `list` 失败/超时/坏信封/死进程时**直接放行**，不再 block——记忆层故障不得拦主任务结束。
- **ZC-04 请求级免催凭证**：废除「近 10 分钟任意写入」全局抑制（跨轮误抑制）；改为 turn 状态文件 `.store_turn`——只有**同会话、本轮 prompt 之后**的成功写回执或引擎侧写入才免催；缺凭证时宁可多一轮有界收尾。pending 回执保留候选短 id 与引擎建议动作全量（改＞并＞挂＞存），不再缩成 parent/force 两项（§7.2）。ok/warn 写入后 `show` 写后回读核验（R11），verified/mismatch/unavailable 如实标注。
- **ZC-05 一次收尾锁**：宿主未带 `stop_hook_active` 时同一请求也至多 block 一次（`.store_turn` 的 stop_block_ts；新 prompt 重新武装）——不再单靠宿主防重位。

### Changed

- 测试大改：CI 桩白名单升级为**有序调用序列**（remember→show 回读链合法化），spy 支持 warn/pending/silent/hang/show_mismatch 模式；新增 8 个契约测试（warn 不误报、pending 转达 merge、unknown 禁重发、fail-open、请求级凭证、会话隔离、一次收尾锁、跨轮不误抑制）；**翻转旧错误期望**（failed→block 曾被当正确结果）。bash 套件换可移植 python 引擎桩（.cmd 包装，修 Windows 下 bash 桩 WinError 193 与 MSYS 路径转换伪故障），基线 54/7 → 89/0。
- `RESPITE_TEST_FAST=1` 测试后门（全部 CLI 超时压到秒级，供超时分支测试）；`RESPITE_TURN_STATE` 指定轮次状态文件路径。
- README「记：」/Stop 行为表与设计要点同步新契约；`.gitignore` 增 `.store_turn`。

## [0.1.1] - 2026-10-31

### Changed

- 提示词全量英文化（dimcode 0.5.6 同款）：`RULES` / `NO_RSRS` / `LOGIN_NUDGE` / `EMPTY_NUDGE` / `NO_MODEL` / `PROBE_FAIL` / `STORE_NUDGE`、落库回执（stored / store pending / store failed / 超时）、召回头行（auto-recall）全部改英文；「记：」等中文前缀与信封解析兼容不变。SKILL.md 同步英文（保留中文触发词）。
- 新增输入侧疑似凭据扫描（`contains_secret`）：命中私钥块 / 高危 token 前缀 / 口令赋值形态的 prompt 不召回也不落库，注入 `SECRET_SKIP` 提示——补齐与 codex/pi/dsh 侧一致的防线。
- 安装与注册口径对齐 CLI 现状：`rsrs-cli@latest` 为官方新用户入口；注册为本机 `rsrs register` 直注、无网站步骤（NO_RSRS / LOGIN_NUDGE / PROBE_FAIL 与插件清单 description 同步修正）。
- 测试断言随英文输出同步（56 项），新增疑似凭据不召回 / 不落库两条。

## [0.1.0] - 2026-10-23

### Added

- 首版：respire（rsrs）记忆层接入 ZCode——SessionStart 简则注入、UserPromptSubmit 每轮标题档召回、「记：」一前缀落库回执、Stop 存储检查（block 续跑一轮）。
- ZCode 协议适配（对照 respire-qoder 0.6.3 骨架）：
  - 输出走严格 JSON：文本 → `{"additionalContext":…}`（ZCode 忽略纯文本 stdout，已核 runtime 源码）；
  - Stop 阻塞用 `{"decision":"block","reason":…}`（ZCode 枚举 approve|block，不收 `deny`）；
  - 数据目录探测 `RESPITE_DATA` → `ZCODE_PLUGIN_DATA` → 脚本目录；hooks.json 仅 ZCode schema 收录字段，不带 `commandWindows`。
- `scripts/validate_plugin.py`（结构/清单/hooks/输出契约/敏感扫描）、`scripts/package.sh`＋`release.yml`（tag→release，与 dimcode 同口径）、`tests/test_hooks.sh`（stdin 模拟断言＋`--store` 写探针自清理）。
