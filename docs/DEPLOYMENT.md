# Deployment

This repository deploys backend updates through `.github/workflows/deploy.yml`.

## CI/CD flow

On every push to `master` (or manual `workflow_dispatch`):

1. Lint backend (`ruff`) and frontend (`npm run lint`)
2. Run backend tests (`pytest`) and Playwright happy-path e2e
3. Build and push backend image to GHCR (`ghcr.io/louischirol/turgotchat-backend:<sha>`)
4. SSH to the server, update `BACKEND_IMAGE`, restart backend, health-check `/`
5. On failure, rollback to the previous container image automatically

## Required GitHub secrets

- `DEPLOY_HOST`: server hostname or IP
- `DEPLOY_USER`: SSH user (e.g. `ubuntu`)
- `DEPLOY_PATH`: deployed repo path on server (e.g. `/home/ubuntu/turgot`)
- `DEPLOY_SSH_PRIVATE_KEY`: private key for SSH deploy user
- `GHCR_USERNAME`: GitHub username for pulling images on the server (if registry login required)
- `GHCR_TOKEN`: token with `read:packages` (if registry login required)

`GITHUB_TOKEN` is used automatically for GHCR push during CI.

## Server expectations

- Docker and Docker Compose installed
- External Docker network `web` (shared with Caddy in `~/lchirol/infra`)
- Repository at `DEPLOY_PATH` with `docker-compose.yml` and `.env`
- `.env` contains runtime secrets (`MISTRAL_API_KEY`, `REDIS_PASSWORD`, etc.)
- Caddy routes `turgot.louischirol.fr` → `turgot-frontend:3000`, `/api/*` → `turgot-backend:8000`
- Frontend build uses `NEXT_PUBLIC_API_URL=/api` (same-origin, no `api.turgotchat.fr` subdomain)
- `turgotchat.fr` redirects to `turgot.louischirol.fr`; `api.turgotchat.fr` kept as legacy API host
- Nginx on the host is **not** the edge proxy (Caddy binds 80/443)

## Manual deploy (without CI)

```bash
./scripts/copy_to_server.sh

# Sync vector DB (large; stop containers first)
ssh -i ~/.ssh/id_ed25519_colbert ubuntu@145.239.71.174 'cd ~/turgot && docker compose down'
rsync -avz --delete -e "ssh -i ~/.ssh/id_ed25519_colbert" \
  database/chroma_db/ ubuntu@145.239.71.174:~/turgot/database/chroma_db/

ssh -i ~/.ssh/id_ed25519_colbert ubuntu@145.239.71.174
cd ~/turgot && ./scripts/deploy.sh
```

Verify: `https://turgot.louischirol.fr` and `https://turgot.louischirol.fr/api/`

## Manual rollback

```bash
cd ~/turgot
# set BACKEND_IMAGE to previous tag in .env.deploy or .env
docker compose --env-file .env --env-file .env.deploy up -d backend
```

## Local testing before deploy

```bash
# Backend tests
cd backend && uv run pytest -q

# Full stack locally
docker compose up --build
# Frontend: http://localhost:3000  Backend: http://localhost:8000
```

See `database/README.md` for vector DB update workflows.
