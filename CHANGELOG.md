# Changelog

All notable changes to this project are documented in this file.
The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

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
