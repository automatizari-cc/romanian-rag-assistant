# romanian-rag-assistant

Self-hosted Romanian-language RAG: ingest documents, search them semantically, chat with an LLM that answers in Romanian. Designed to run on a single Hetzner CX53 (16 vCPU / 32 GB / no GPU), behind Cloudflare.

> **Status:** internal / research deployment. The default LLM (RoLlama3.1-8B-Instruct) is **CC-BY-NC-4.0** — non-commercial only. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the commercial swap path.

---

## Stack

| Layer | Component |
|---|---|
| LLM (Romanian-primary) | RoLlama3.1-8B-Instruct via Ollama |
| Embeddings | BAAI/bge-m3 via text-embeddings-inference |
| Reranker | BAAI/bge-reranker-v2-m3 via text-embeddings-inference |
| Vector DB | Qdrant |
| Ingestion + retrieval API | FastAPI (`ingestion/`), OpenAI-compatible endpoint |
| Chat UI | Open-WebUI (talks to the FastAPI service, not Ollama directly) |
| Reverse proxy | nginx (TLS, mTLS to Cloudflare via Authenticated Origin Pulls) |
| Edge | Cloudflare (DNS proxy, WAF, Turnstile on `/auth/*`, Rate Limit) |

Full service map and request flow: **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

---

## Quickstart (local dev — uses your host's Ollama)

```bash
# 1. Make your host's Ollama reachable from containers (one-time):
sudo systemctl edit ollama.service
# add:
#   [Service]
#   Environment="OLLAMA_HOST=0.0.0.0:11434"
sudo systemctl daemon-reload && sudo systemctl restart ollama

# 2. Configure and run:
cp .env.example .env
# edit .env: set OLLAMA_MODEL to a tag from `ollama list`,
# generate WEBUI_SECRET_KEY and POSTGRES_PASSWORD,
# leave DOMAIN / LE_EMAIL / CLOUDFLARE_* blank.
#   openssl rand -hex 32   # WEBUI_SECRET_KEY
#   openssl rand -hex 24   # POSTGRES_PASSWORD

docker compose -f docker-compose.yml -f docker-compose.local.yml up -d
# first boot pulls BGE-M3 + reranker (~4 GB) — wait a few minutes
# then open http://localhost:8080
```

The local override skips nginx/TLS and the in-compose Ollama — `ingestion` talks to your host's Ollama directly. No custom landing page in this mode; you log into Open-WebUI's own UI.

---

## Production deploy on Hetzner CX53

Full runbook is in [ARCHITECTURE.md §7](./ARCHITECTURE.md#7-operational-runbook-initial-deploy). Short version:

```bash
# on the VM, as root
git clone https://github.com/automatizari-cc/romanian-rag-assistant /opt/rag
cd /opt/rag

./scripts/harden-host.sh                         # SSH hardening, IPv6 off, unattended-upgrades
DATA_DEV=/dev/sdb ./scripts/setup-luks-data.sh   # LUKS-encrypt /data
cp .env.example .env && $EDITOR .env

./scripts/issue-cert.sh                          # LE cert via DNS-01 + CF API token
./scripts/setup-origin-pulls.sh                  # CF Authenticated Origin Pulls CA
./scripts/sync-cloudflare-ips.sh                 # also schedule via cron, daily
./scripts/setup-fail2ban.sh                      # SSH brute-force protection

docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile prod up -d
./scripts/bootstrap.sh
```

Then in the **Cloudflare dashboard** for this zone:

1. SSL/TLS → set to **Full (Strict)**
2. SSL/TLS → Origin Server → enable **Authenticated Origin Pulls**
3. SSL/TLS → Edge Certificates → **Always Use HTTPS**
4. Security → **Bot Fight Mode** on
5. Security → WAF → add a **Rate Limit** rule on `/api/*` and `/auth/*`
6. Security → WAF → add a **Turnstile Challenge** rule on `/auth/*` with pre-clearance

---

## Security model — at a glance

- **Edge:** Cloudflare WAF + Turnstile + Rate Limit. Authenticated Origin Pulls (mTLS) ensures requests reaching the VM came through Cloudflare.
- **Network:** Hetzner Cloud Firewall — SSH from anywhere (key-only), 80/443 from Cloudflare ranges only (kept in sync by cron). IPv4-only.
- **Host:** LUKS on `/data`, SSH key-only, fail2ban for sshd, IPv6 disabled at sysctl + Docker.
- **App:** all containers bound to `127.0.0.1` except nginx; non-root container users; secrets only via `.env`; signup disabled on Open-WebUI by default.
- **Supply chain:** every push runs gitleaks, ruff, bandit, pip-audit, hadolint, trivy (fs + config), semgrep, and CodeQL. Dependabot opens weekly PRs for pip / docker / actions. Local pre-commit catches the same issues before you push.

Full breakdown: [ARCHITECTURE.md §6](./ARCHITECTURE.md#6-security-model).

---

## Repo layout

```
.
├── ARCHITECTURE.md          ← read this first
├── docker-compose.yml
├── .env.example
├── ingestion/               ← FastAPI: ingest, retrieve, OpenAI-compat chat proxy
├── nginx/                   ← reverse proxy + TLS + Cloudflare mTLS
├── scripts/                 ← deploy + ops scripts (idempotent)
├── docker/                  ← reserved (custom images, currently none)
├── docs/                    ← project documentation
├── embeddings/              ← reserved (TEI runs from official image; custom configs go here)
├── qdrant/                  ← reserved (Qdrant runs from official image; snapshots go here)
├── open-webui/              ← reserved (Open-WebUI runs from official image; theme/branding here)
├── uploads/                 ← runtime user uploads — gitignored
├── tests/                   ← top-level integration tests (per-service tests live next to code)
└── .github/                 ← CI: security, codeql, dependabot
```

---

## Development

```bash
# install pre-commit hooks (one-time)
pip install pre-commit && pre-commit install

# python deps for local lint
pip install ruff bandit pip-audit
ruff check ingestion/
bandit -r ingestion/app -ll -ii
pip-audit -r ingestion/requirements.txt --strict
```

CI runs the same set on every push and PR.
