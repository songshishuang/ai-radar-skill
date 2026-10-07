#!/usr/bin/env bash
# ai-radar 一键安装到 Claude Code / 兼容 agent 的 skills 目录
# 用法: ./install.sh [目标目录]   默认 ~/.claude/skills/ai-radar
# 可重复执行：把仓库内容同步进目标目录，已安装也不会嵌套；不删目标目录里的其它文件
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${1:-$HOME/.claude/skills/ai-radar}"
mkdir -p "$DEST"
# 不随 skill 分发开发文件和本地产物
tar -C "$SRC" \
  --exclude=.git --exclude=__pycache__ --exclude=.pytest_cache \
  --exclude=.claude --exclude=ai-radar-reports --exclude=.DS_Store \
  -cf - . | tar -C "$DEST" -xf -
echo "✓ ai-radar 已安装到 $DEST"
echo "  重开会话后说「给我今天的 AI 日报」即可触发。"
