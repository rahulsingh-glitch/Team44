#!/usr/bin/env bash
set -e
echo "Installing Claude Code config into .claude ..."
mkdir -p .claude/agents .claude/commands
cp claude-setup/agents/*   .claude/agents/
cp claude-setup/commands/* .claude/commands/
echo "Done. Agents:";   ls .claude/agents
echo "Commands:";       ls .claude/commands
echo "Now run:  claude   (from this folder), then type /"
