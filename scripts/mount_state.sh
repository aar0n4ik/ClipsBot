#!/usr/bin/env bash
# Монтирует ветку `data` (состояние бота) в ./state. Создаёт её при первом запуске.
set -euo pipefail
git config --global user.name "clip-bot"
git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"
if git ls-remote --exit-code --heads origin data >/dev/null 2>&1; then
  git fetch --depth=1 origin data
  git worktree add -f --detach state FETCH_HEAD
else
  git worktree add --detach state HEAD
  cd state
  git checkout --orphan data
  git rm -rf -q . >/dev/null 2>&1 || true
  echo "# Состояние бота (генерируется автоматически)" > README.md
  git add README.md
  git commit -q -m "init state"
  git push -q origin HEAD:data
fi
