#!/usr/bin/env bash
# respire 插件打包 —— CI 与本地共用同一口径。
# 规范：zip 根=插件根（解压后根读 .zcode-plugin/plugin.json，ZCode 本地市场与 zip 分发同构）。
# 产出 dist/respire-<version>-<yyyymmdd>.zip，zip 注释行为构建基线 commit。
# stdout 恰两行：第一行 zip 路径，第二行 sha256。
# 兼容 macOS bash 3.2：变量展开一律 ${VAR} 花括号隔离，邻近不放中文标点。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VER="$(python3 -c "import json; print(json.load(open('.zcode-plugin/plugin.json'))['version'])")"
REV="$(git rev-parse HEAD 2>/dev/null || echo nobaseline)"
STAMP="$(date +%Y%m%d)"
OUT="dist/respire-${VER}-${STAMP}.zip"

mkdir -p dist
rm -f "$OUT"

zip -r "$OUT" \
  .zcode-plugin .claude-plugin .gitignore CHANGELOG.md LICENSE README.md \
  assets hooks scripts skills tests .github \
  -x 'hooks/__pycache__/*' 'hooks/__pycache__/' \
  -x 'hooks/hook.log' 'hooks/.nudge_counter' \
  -x '*.DS_Store' '*.pyc' >/dev/null

printf '%s\n' "$REV" | zip -z "$OUT" >/dev/null

echo "$OUT"
python3 -c "import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], 'rb').read()).hexdigest())" "$OUT"
