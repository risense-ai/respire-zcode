# Changelog

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
