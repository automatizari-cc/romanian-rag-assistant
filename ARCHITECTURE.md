# Architecture

Self-hosted Romanian-language RAG: document ingestion → semantic search → chat with an LLM that answers in Romanian.

Target host: **Hetzner CX53** (16 vCPU, 32 GB RAM, 320 GB disk, no GPU).
Deployment posture: **internal / research / non-commercial** (driven by RoLlama3.1 license — see "Models").

---

## 1. Service map

```
                   Internet (IPv4 only)
                         │
                         ▼
         ┌──────────────────────────────┐
         │   Cloudflare (DNS + Proxy)   │
         │   • WAF + Rate Limit         │
         │   • Bot Fight Mode           │
         │   • Turnstile on /auth/*     │
         │   • Authenticated Origin     │
         │     Pulls (mTLS to origin)   │
         └──────────────┬───────────────┘
                        │ TLS (Full Strict) + CF client cert
                        ▼
         ┌──────────────────────────────┐
         │  Hetzner Cloud Firewall      │
         │  • 22/tcp from your IP only  │
         │  • 80,443/tcp from CF IPs    │
         │  • everything else dropped   │
         └──────────────┬───────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────┐
│ VM (CX53, IPv4-only, LUKS-encrypted /data)         │
│                                                    │
│  ┌──────────────────┐                              │
│  │  nginx (host:443)│  ← only public-facing svc    │
│  │  • mTLS verify   │                              │
│  │  • real IP from  │                              │
│  │    CF-Connecting │                              │
│  └────────┬─────────┘                              │
│           │ proxy_pass                             │
│           ▼                                        │
│  ┌──────────────────┐    ┌───────────────────┐     │
│  │  open-webui      │───▶│ ingestion (API)   │     │
│  │  127.0.0.1:8080  │    │ 127.0.0.1:8000    │     │
│  │  (chat UI only)  │    │ FastAPI:          │     │
│  └──────────────────┘    │ • /ingest         │     │
│                          │ • /v1/chat/comp.. │     │
│                          │   (OpenAI-compat, │     │
│                          │    injects RAG    │     │
│                          │    context)       │     │
│                          └────┬──────────┬───┘     │
│                               │          │         │
│                       ┌───────┴──┐  ┌────┴──────┐  │
│                       │  qdrant  │  │  ollama   │  │
│                       │ 127:6333 │  │ 127:11434 │  │
│                       └────┬─────┘  └───────────┘  │
│                            │                       │
│                  ┌─────────┴─────────┐             │
│                  │ tei-embed (BGE-M3)│             │
│                  │ 127.0.0.1:8081    │             │
│                  ├───────────────────┤             │
│                  │ tei-rerank        │             │
│                  │ (BGE-reranker-v2) │             │
│                  │ 127.0.0.1:8082    │             │
│                  └───────────────────┘             │
│                                                    │
│  ┌──────────────────┐                              │
│  │ postgres         │  ← Open-WebUI metadata only  │
│  │ 127.0.0.1:5432   │                              │
│  └──────────────────┘                              │
└────────────────────────────────────────────────────┘
```

Only nginx binds to public interfaces. Every other container binds to `127.0.0.1` — origin-bypass attacks have no service to hit even if CF/firewall fails open.

---

## 2. Request flow

### Chat
1. User → Cloudflare → nginx (mTLS verified) → open-webui
2. open-webui sends OpenAI-format request to `ingestion` (it thinks it's talking to OpenAI)
3. `ingestion` extracts the latest user message, embeds it via `tei-embed`, queries Qdrant (hybrid dense+sparse), reranks top-K via `tei-rerank`, takes top-N
4. `ingestion` builds a prompt with the retrieved context + Romanian system prompt, forwards to `ollama` (`/api/chat`), streams the response back as OpenAI-format SSE
5. open-webui renders to the user

### Ingestion
1. Operator (or future UI hook) POSTs files to `ingestion /ingest`
2. `ingestion` parses (PDF/DOCX/TXT/MD/HTML), chunks (semantic + size-bounded), embeds per-chunk via `tei-embed`, upserts into Qdrant with payload (source, page, chunk_id, text)
3. Returns ingestion summary

---

## 3. Models

| Role | Model | Reason |
|---|---|---|
| LLM | **RoLlama3.1-8B-Instruct** (Q4_K_M GGUF, via Ollama) | Best Romanian quality at this size; CC-BY-NC-4.0 — internal use only |
| Embeddings | **BAAI/bge-m3** | Multilingual, hybrid dense+sparse, 1024-dim, strong on Romanian |
| Reranker | **BAAI/bge-reranker-v2-m3** | Multilingual cross-encoder; meaningful precision lift on top-K |

Embedding + reranker run on `text-embeddings-inference` (TEI), CPU build, AVX2.

**Commercial swap path:** if/when this becomes a product, replace LLM with `Llama-3.1-8B-Instruct` (Llama 3.1 Community License) or `Mistral-Nemo-Instruct-12B` (Apache 2.0). Embedding + reranker stay (Apache 2.0 / MIT).

---

## 4. RAM & disk budget (steady state)

| Component | RAM | Disk |
|---|---|---|
| OS + Docker overhead | ~2 GB | ~10 GB |
| Qdrant (idle + small collection) | ~1.5 GB | grows with corpus |
| postgres (Open-WebUI) | ~0.4 GB | <1 GB |
| open-webui | ~0.5 GB | <1 GB |
| tei-embed (BGE-M3) | ~2.5 GB | ~2 GB |
| tei-rerank (BGE-reranker-v2-m3) | ~2 GB | ~2 GB |
| ingestion (FastAPI) | ~0.4 GB | minimal |
| nginx | ~0.05 GB | logs |
| **Subtotal (non-LLM)** | **~9 GB** | |
| Ollama + RoLlama3.1-8B Q4 + 8k ctx KV | ~10 GB | ~5 GB |
| **Total** | **~19 GB** | |
| Headroom (page cache, growth, ingestion bursts) | ~13 GB | |

Speed expectation: **~5–7 tok/s** generation, **single-user sequential**. Multi-user = queue (intentional — no GPU).

---

## 5. Storage layout

```
/data  ← LUKS-encrypted partition, unlocked at boot via keyfile on root FS
        (protects against image-level exfiltration; not against root compromise)
├── docker/                  → bind-mounted into Docker root (var-lib-docker)
├── qdrant/                  → Qdrant persistent storage
├── ollama/                  → GGUF models + KV cache
├── postgres/                → Open-WebUI metadata
├── uploads/                 → ingested source documents (immutable archive)
└── nginx-logs/              → access/error logs (host-side, for fail2ban + audit)
```

`docs/` in the repo = project documentation. `uploads/` in the repo = empty placeholder; runtime uploads live under `/data/uploads/` on the server (bind-mounted into the `ingestion` container).

---

## 6. Security model

### Network
- **IPv4-only.** IPv6 disabled at sysctl, in Docker daemon, and in nginx.
- **Hetzner Cloud Firewall** is the network-level gate: only 22 (SSH, key-only, from anywhere — explicit user choice), 80/443 (from Cloudflare IPv4 ranges only).
- **Cloudflare Authenticated Origin Pulls (mTLS):** nginx requires the Cloudflare client certificate. Any request reaching the VM that isn't from Cloudflare is rejected at the TLS handshake, not at the app.
- TLS mode at Cloudflare: **Full (Strict)**. Origin cert: **Let's Encrypt via DNS-01** using a scoped CF API token (`Zone:DNS:Edit` on this zone only).
- **Container exposure:** all services bind to `127.0.0.1`; only nginx is on the public interface.

### Host
- LUKS on `/data` (data-only, system stays plain to avoid initramfs SSH unlock dance).
- `unattended-upgrades` enabled.
- SSH: key-only, `PermitRootLogin no`, `PasswordAuthentication no`. Port 22 (per user choice).
- `fail2ban` jail: **`sshd` only** — HTTP brute-force is handled at Cloudflare's edge (WAF + Rate Limit + Turnstile), so fail2ban doesn't try to defend HTTP through the proxy.

### Application
- Open-WebUI auth: signup disabled by default (operator creates accounts), strong-password policy.
- Cloudflare Turnstile gates `/auth/*` via a CF Challenge rule with pre-clearance — no upstream code change.
- Secrets only in `.env` (gitignored); CI scans every push for accidental commits (gitleaks).
- Containers run as non-root where the upstream image supports it.

### Supply chain & code
- Every push and PR triggers: gitleaks, ruff (security rules), bandit, pip-audit, hadolint, trivy (fs + config), semgrep, CodeQL.
- Dependabot opens PRs for pip, docker base images, and GitHub Actions.
- pre-commit hooks run a fast subset (gitleaks + ruff + bandit) locally.

---

## 7. Operational runbook (initial deploy)

1. Provision CX53, attach 320 GB disk.
2. Hetzner Cloud Firewall: SSH from your IP, 80/443 from CF v4 ranges.
3. SSH in. Run `scripts/harden-host.sh`.
4. Run `scripts/setup-luks-data.sh` — formats and mounts `/data`.
5. `git clone` into `~/romanian-rag-assistant`.
6. Fill `.env` from `.env.example` — including `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ZONE_ID`, `DOMAIN`, `LE_EMAIL`.
7. Run `scripts/issue-cert.sh` — issues LE cert via DNS-01.
8. Run `scripts/setup-origin-pulls.sh` — installs CF origin-pull CA.
9. Run `scripts/sync-cloudflare-ips.sh` once, then schedule via cron (daily).
10. Run `scripts/setup-fail2ban.sh`.
11. Run `scripts/bootstrap.sh` — pulls RoLlama3.1 GGUF, creates Ollama Modelfile, pre-warms TEI models.
12. `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile prod up -d`.
13. In Cloudflare dashboard: enable Full Strict, Always Use HTTPS, Authenticated Origin Pulls, Bot Fight Mode, Turnstile rule on `/auth/*`, Rate Limit rules on `/auth/*` and `/api/*`.
14. Smoke test: ingest a sample doc, ask a Romanian question, verify citation and answer language.

---

## 8. Out of scope (now)

- GPU inference (would change LLM choice and concurrency story).
- Multi-tenant isolation.
- Outbound email — deferred; will use a transactional provider (Resend / Postmark / SES) when added, never self-hosted SMTP.
- Backup/DR — needs a separate doc once corpus stabilizes.
