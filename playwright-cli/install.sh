#!/usr/bin/env bash
set -euo pipefail

npm install -g @playwright/cli@0.1.22
skill_source="$(npm root -g)/@playwright/cli/skills/playwright-cli"
skill_target="${CODEX_HOME:-$HOME/.codex}/skills/playwright-cli"
[[ -f "$skill_source/SKILL.md" ]] || { printf 'Installed package is missing the Playwright CLI skill.\n' >&2; exit 1; }
mkdir -p "$(dirname -- "$skill_target")"
if [[ -e "$skill_target" ]]; then
  backup="${CODEX_HOME:-$HOME/.codex}/skill-backups/playwright-cli.$(date +%Y%m%d%H%M%S).$$"
  mkdir -p "$(dirname -- "$backup")"
  mv "$skill_target" "$backup"
  printf 'Previous skill backed up to: %s\n' "$backup"
fi
cp -R "$skill_source" "$skill_target"
playwright-cli --version
printf 'Codex skill installed: %s\nAvailable on your next Codex turn.\n' "$skill_target"
printf 'Try: playwright-cli open https://example.com --browser=chrome --headed\n'
