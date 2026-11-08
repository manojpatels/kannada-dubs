#!/bin/bash
# Double-click to publish the Kannada dubbed movies site (or run: bash publish.command).
# Safe to run again: it only commits and pushes what changed.
cd "$(dirname "$0")" || exit 1
REPO="kannada-dubs"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }
pause() { read -r -p "Press Return when done… " _; }

say "1/4  Building the site"
python3 build_site.py || { echo "Build failed; nothing was published."; exit 1; }

say "2/4  Saving a snapshot with git"
[ -d .git ] || git init -q -b main
git add -A
git commit -qm "Update site $(date +%F)" && echo "Committed." || echo "No changes to commit."

say "3/4  Putting it on GitHub"
if git remote get-url origin >/dev/null 2>&1; then
  git push -u origin main && echo "Pushed."
elif command -v gh >/dev/null 2>&1; then
  gh auth status >/dev/null 2>&1 || gh auth login --web
  gh repo create "$REPO" --public --source . --remote origin --push
else
  echo "A browser tab will open to create an empty public repository named '$REPO'."
  echo "Leave every box unticked (no README, no .gitignore), then click 'Create repository'."
  open "https://github.com/new?name=$REPO&visibility=public"
  read -r -p "Paste your GitHub username and press Return: " GHUSER
  git remote add origin "https://github.com/$GHUSER/$REPO.git"
  git push -u origin main && echo "Pushed."
fi

say "4/4  Connecting Cloudflare Pages (first time only)"
if [ ! -f .cloudflare-connected ]; then
  echo "A Cloudflare tab will open. Choose: Connect to Git → GitHub → '$REPO', then use these settings:"
  echo "   Project name:            kannada-dubs"
  echo "   Production branch:       main"
  echo "   Framework preset:        None"
  echo "   Build command:           (leave empty)"
  echo "   Build output directory:  site"
  open "https://dash.cloudflare.com/?to=/:account/pages/new/provider/github"
  pause
  touch .cloudflare-connected
  echo "Done. Your site will be at https://kannada-dubs.pages.dev in a minute or two."
  echo "If Cloudflare gave it a different address, tell Claude so the links and sitemap can be updated."
else
  echo "Already connected; Cloudflare publishes this push automatically."
fi
