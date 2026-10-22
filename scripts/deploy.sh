#!/usr/bin/env bash
# Deploy the latest code from GitHub. Run on the server:
#   sudo -iu crm bash /home/crm/flatons-crm/scripts/deploy.sh          # deploys main
#   sudo -iu crm bash /home/crm/flatons-crm/scripts/deploy.sh dev      # deploys another branch
set -euo pipefail

APP_DIR="/home/crm/flatons-crm"
WEB_ROOT="/var/www/flatons-crm"
BRANCH="${1:-main}"

echo "==> Pulling latest code ($BRANCH)"
cd "$APP_DIR"
git fetch --prune origin
git checkout "$BRANCH"
git pull --ff-only origin "$BRANCH"

echo "==> Backend dependencies"
cd "$APP_DIR/backend"
export PATH="$HOME/.local/bin:$PATH"
poetry env use python3.12 >/dev/null
poetry sync --only main --no-interaction

if [ -f alembic.ini ]; then
  echo "==> Database migrations"
  poetry run alembic upgrade head
fi

echo "==> Frontend build"
cd "$APP_DIR/frontend"
export NVM_DIR="$HOME/.nvm"
set +u; source "$NVM_DIR/nvm.sh"; set -u
npm ci --no-audit --no-fund
npm run build
rsync -a --delete dist/ "$WEB_ROOT/"

echo "==> Restarting services"
sudo /usr/bin/systemctl restart flatons-api flatons-worker flatons-beat

echo "==> Health check"
sleep 4
curl -fsS http://127.0.0.1:8000/api/health
echo
echo "Deploy OK"
