# CLAUDE.md

Working notes for future sessions on **automatizari-cc/romanian-rag-assistant**. Read this first; defer to `ARCHITECTURE.md` for detailed design and `README.md` for runbook.

---

## What this is

Self-hosted Romanian-language RAG (ingestion + semantic search + chat). Target host: a single **Hetzner CX53** (16 vCPU / 32 GB / 320 GB / no GPU). Status: **internal / research / non-commercial**.

GitHub: <https://github.com/automatizari-cc/romanian-rag-assistant> (public).

---

## Locked-in decisions — do not relitigate without cause

| Concern | Choice | Why |
|---|---|---|
| LLM | **RoLlama3.1-8B-Instruct** via Ollama | Best Romanian quality at this size class. License is CC-BY-NC-4.0 — non-commercial only. |
| Commercial swap path | Llama-3.1-8B-Instruct (Llama 3.1 Community) or Mistral-Nemo-12B (Apache 2.0) | If/when this goes commercial. Embeddings + reranker stay (Apache 2.0/MIT). |
| Embeddings | BAAI/bge-m3 via TEI | 1024-dim, multilingual, hybrid dense+sparse. |
| Reranker | BAAI/bge-reranker-v2-m3 via TEI | Multilingual cross-encoder; meaningful precision lift. |
| Vector DB | Qdrant | Standard choice; lightweight; no comparable contender debated. |
| Chat UI | Open-WebUI (thin) | Used as front-end only; **does not** own RAG. Its built-in RAG is bypassed. |
| RAG ownership | Custom **FastAPI** in `ingestion/` exposing OpenAI-compat `/v1/chat/completions` | Open-WebUI talks to *us*; we inject context before forwarding to Ollama. Lets us own chunking, reranker, hybrid retrieval. |
| Edge | **Cloudflare** DNS proxy + WAF + Rate Limit + Turnstile on `/auth/*` + **Authenticated Origin Pulls** (mTLS to origin) | mTLS closes the origin-bypass gap. |
| TLS | **Full (Strict)** at CF; origin cert via Let's Encrypt **DNS-01** with scoped CF API token | Avoids exposing port 80 for cert issuance. |
| Network | Hetzner Cloud Firewall: 22 from anywhere (key-only); 80/443 from CF IPv4 ranges only (cron-synced). **IPv4-only** | User explicitly chose SSH-from-anywhere; key-only auth + fail2ban as compensating control. |
| Encryption at rest | LUKS on `/data` only, keyfile-unlocked at boot | Avoids initramfs SSH-unlock dance. Protects against image exfiltration, not host compromise. |
| fail2ban | **sshd jail only** | HTTP brute-force handled at CF edge; fail2ban + Docker iptables is fragile, wrong layer. |
| Custom landing/login | Romanian landing at `/`; `/login` posts to FastAPI `/auth/login` which validates + proxies to Open-WebUI's signin | Option B — chosen over direct browser→Open-WebUI to add real server-side input validation and per-IP rate limit. |
| Container exposure | All services bind to `127.0.0.1` except `nginx` | Origin-bypass attacks have no service to hit even if FW/CF fail open. |

---

## What's been built (commits on `main`)

| SHA | Subject | Notes |
|---|---|---|
| `f126a72` | Initial commit | Pre-session — empty repo, .gitignore, README |
| `6426b77` | scaffold romanian RAG stack with Cloudflare-fronted security model | Full skeleton: compose, ingestion FastAPI (parsers/chunking/embed/rerank/store/llm/retrieval), nginx, all 7 deploy scripts, CI workflows (security + codeql + dependabot + pre-commit) |
| `78f715a` | fix CI: trivy-action tag, semgrep flag, hadolint apt rules, dependabot docker scope | First push uncovered: trivy-action@0.28.0 doesn't exist (→`@master`), semgrep `--error` was removed, hadolint DL3008/DL3009 impractical on debian-slim (→ignore), dependabot docker `/` requires Dockerfile (→removed) |
| `471791f` | add Romanian landing page + custom validated login flow | `nginx/html/{index,login}.html` + `static/{styles.css,landing.js,login.js}`; `ingestion/app/auth.py` (Pydantic+email-validator+per-IP rate limit+Open-WebUI proxy); 23 new tests |
| `3277786` | add workflow_dispatch trigger to codeql workflow | Manual SAST runs from Actions tab |
| `580064b` | harden nginx against host-header spoofing and h2c smuggling | semgrep findings: `$host` use → templated `${DOMAIN}` via nginx envsubst; default_server returns 444; `map $http_upgrade $safe_upgrade` permits only websocket |

---

## CI / security pipeline (all on a public repo, **free**)

- `.github/workflows/security.yml`: gitleaks, ruff, bandit, pip-audit, hadolint, trivy fs+config, semgrep — push/PR + weekly Mon 04:23 UTC + manual.
- `.github/workflows/codeql.yml`: Python deep SAST — push/PR + weekly Tue 05:37 UTC + manual.
- `.github/dependabot.yml`: pip (`/ingestion`), docker (`/ingestion`), github-actions (`/`). Weekly Monday.
- `.pre-commit-config.yaml`: gitleaks/ruff/bandit/hadolint — for local mirror of CI.
- For deeper one-off: user runs `/ultrareview` (multi-agent cloud review, billed to user's Claude account, Claude cannot launch it).

Repo Settings still TODO (manual UI work for the user):
- Code security → enable Dependabot alerts, secret scanning, push protection.
- Branches → require `security` and `codeql` to pass before merge to `main`.

---

## Open work — pickup points for next session

Highest leverage first:

1. **Local-mode override** (user has a bigger local server with Ollama + 2 unspecified models). Plan was a `docker-compose.local.yml` that strips nginx-with-TLS, removes our `ollama` service, points `ingestion` at host's Ollama via `host.docker.internal`. **Not started.** Pending the user telling us *which* two models they have so we can recommend whether to also pull RoLlama3.1 locally.
2. **Deploy automation on the production VM** (architecture agreed but not coded):
   - `scripts/deploy.sh` — idempotent: git fetch → compare HEADs → reset hard → `compose pull` + `up -d --build` → `compose ps` → log SHA. Skip rebuild when no Dockerfile-relevant files changed; abort on uncommitted server-side changes.
   - `scripts/install-deploy-timer.sh` — installs `rag-deploy.service` + `rag-deploy.timer`, every 2 min.
   - Read-only deploy key on server; pull via SSH.
   - User's local workflow becomes: `git push` (server picks up within 2 min). Manual instant deploy: `ssh server sudo systemctl start rag-deploy.service`.
3. **Provision the actual Hetzner CX53.** None of the deploy scripts have been *run* yet. The runbook is in `ARCHITECTURE.md §7` and `README.md`. After provisioning:
   - Cloudflare dashboard: enable Full Strict, AOP, Always Use HTTPS, Bot Fight Mode, Turnstile rule on `/auth/*`, Rate Limit on `/api/*` and `/auth/*`.
   - Hetzner Cloud Firewall rules.
   - Smoke test: ingest a sample doc, ask a Romanian question, verify citation + language.
4. **Email** — explicitly deferred. When needed: Resend / Postmark / SES / SendGrid via SMTP creds in `.env`. Never self-hosted (Hetzner blocks port 25 outbound; IPs blocklisted). No code yet.

---

## Conventions

- **Discuss tradeoffs before scaffolding.** When there's a real architectural choice (not a clear directive), surface 2–3 options + recommendation and wait for the user. The user has consistently rewarded this pattern with quick yes/no decisions.
- **Never push without explicit per-push OK.** "yes, go" approves *that* push, not future ones.
- **Commit messages: rationale-first.** Lead with the problem and the why, not the diff. Multi-paragraph bodies are fine when there's actual reasoning to capture; the user reads them.
- **No assistant-as-co-author trailers without checking** — current convention is to include `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` on every commit body.
- **Tests + scanners must pass locally before commit.** Pattern in this repo: `ruff check ingestion/`, `bandit -q -r ingestion/app -ll -ii`, `pip-audit -r ingestion/requirements.txt --strict`, `pytest`. Trivy/gitleaks/hadolint run only in CI (no Docker on user's local box).
- **Prefer editing existing files** over creating new ones. Do not generate `.md` docs unless explicitly asked.
- **All non-edge containers bind `127.0.0.1`.** This is load-bearing for the security model — don't relax it.
- **IPv4-only** is intentional, not laziness. Don't add IPv6 paths anywhere.

---

## Repo layout (terse — see `README.md` for detail)

```
.
├── ARCHITECTURE.md          ← service map, RAM/disk budget, security model, runbook
├── CLAUDE.md                ← this file
├── README.md
├── docker-compose.yml
├── .env.example
├── ingestion/               ← FastAPI: ingest, retrieve, OpenAI-compat chat proxy, /auth/login
│   ├── app/                 (auth.py, chunking.py, config.py, embed.py, llm.py,
│   │                         main.py, parsers.py, rerank.py, retrieval.py, store.py)
│   └── tests/               (25 tests, all passing — auth validation + rate limit + happy path)
├── nginx/
│   ├── nginx.conf           (http context: maps, includes)
│   ├── conf.d/cloudflare-realip.conf  (CF IPv4 ranges, refreshed by sync script)
│   ├── templates/server.conf.template (envsubst-rendered with ${DOMAIN})
│   ├── certs/, cf-origin-pull-ca.pem, logs/  (gitignored, populated at deploy)
│   └── html/                (index.html, login.html, static/)
├── scripts/                 (7 deploy/ops scripts; all idempotent; see ARCHITECTURE.md §7)
└── .github/                 (security.yml, codeql.yml, dependabot.yml)
```

---

## Things to watch (technical debt / known caveats)

- **Single-worker assumption.** `ingestion/app/auth.py` rate limiter is in-memory per-process. Compose runs uvicorn with `--workers 1`. If we ever scale to >1 worker, the limiter must move to Redis.
- **`trivy-action@master`** in `.github/workflows/security.yml`. Not pinned to SHA. Dependabot may move it to a version once a release exists; until then, accept the supply-chain risk for simplicity.
- **`ollama pull` of RoLlama3.1 from HF** in `scripts/bootstrap.sh` — depends on the GGUF being available at `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF`. Verified at session time; re-check if pull fails.
- **Open-WebUI is pinned to 0.5.4.** Newer versions may change the `/api/v1/auths/signin` contract or cookie name (`token`); our auth proxy depends on both.
- **Custom landing always shows at `/`.** Already-logged-in users see the landing page (with a JS-detected "Continue" button) rather than being auto-forwarded into Open-WebUI. This was a deliberate simplification — sub-path mounting Open-WebUI is fragile.

---

## User profile (from session)

- GitHub org: `automatizari-cc`. Email: `al.expedient@gmail.com`. Timezone America/New_York.
- Decision style: makes architectural calls quickly when given clear options + a recommendation. Pushes back well ("look at server specs", "short", "give me your input first") when an answer feels generic. Reward: terse, decisive, rationale-led replies.
- Comfort: deploys infra, has Hetzner + Cloudflare in hand, runs Ollama locally on a personal server.
