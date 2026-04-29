# CLAUDE.md

Working notes for future sessions on **automatizari-cc/romanian-rag-assistant**. Read this first; defer to `ARCHITECTURE.md` for detailed design and `README.md` for runbook.

---

## What this is

Self-hosted Romanian-language RAG (ingestion + semantic search + chat). Target host: a single **Hetzner CPX62** (16 dedicated AMD EPYC vCPU / 32 GB / 640 GB / 20 TB / no GPU). Status: **internal / research / non-commercial**.

(Originally planned for CX53. Switched to CPX62 because CX wasn't available; CPX62 is strictly better for this workload — dedicated AMD EPYC cores, AVX2/AVX-512, 2× the disk, same RAM.)

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
| `01e18da` | add CLAUDE.md so future sessions can resume with full context | — |
| `0d9c03a` | add local-mode override; document RoLlama3.1 GGUF pull failure | `docker-compose.local.yml` + README/ARCHITECTURE updates for `--profile prod`; RoLlama3.1 still blocked, see "Things to watch" |
| `d41149b` | add tei-shim for non-AVX2 hosts; bump TEI base image to cpu-1.7 | `tei-shim/` (FastAPI + sentence-transformers + torch CPU 2.2.2) replaces TEI on hosts without AVX2; `docker-compose.silver.yml` overrides only on silver. Bundled the cpu-1.5→1.7 bump from yesterday's working tree. |

**Uncommitted local edits on `silver-shim` (not yet committed):**
- `docker-compose.silver.yml` — added `HF_HUB_DISABLE_XET=1` + `HF_HUB_DOWNLOAD_TIMEOUT=60` + `HF_HUB_ENABLE_HF_TRANSFER=0` to both shim services.
- `docker-compose.yml` — replaced wget-based ingestion healthcheck with python urllib (the slim image has no wget; this is a real bug that would have hit prod too).
- `tei-shim/requirements.txt` — pinned `transformers==4.45.2` (newer transformers gates `torch.load` behind `torch>=2.6` per CVE-2025-32434, but we're stuck on `torch==2.2.2` for pre-AVX2 hosts).
- `ingestion/app/main.py` — added `/v1/models` endpoint returning the configured Ollama model so Open-WebUI's model dropdown populates.
- `CLAUDE.md` — this edit.

These need a commit on `silver-shim`, then push, before any prod deploy. Compose merge re-validates clean and ruff/bandit pass.

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

1. **Provision the Hetzner CPX62 — IN PROGRESS (2026-04-29 evening).** Box already exists with SSH key access; `silver` deploy validated the architecture today via the `tei-shim/` workaround. Two-part plan documented below in **"Prod deploy plan (CPX62)"**. After provisioning:
   - Cloudflare dashboard: enable Full Strict, AOP, Always Use HTTPS, Bot Fight Mode, Turnstile rule on `/auth/*`, Rate Limit on `/api/*` and `/auth/*`.
   - Hetzner Cloud Firewall rules (SSH from anywhere, 80/443 from CF IPv4 only).
   - Generate fresh `.env` on the box (different secrets than any previous local `.env`); back up to password manager as `romanian-rag-assistant .env (hetzner)`.
   - Smoke test: ingest a sample doc, ask a Romanian question, verify citation + language.
2. **Deploy automation** (architecture agreed, not coded — user offered to defer until after first manual prod deploy succeeds):
   - `scripts/deploy.sh` — idempotent: git fetch → compare HEADs → reset hard → `compose pull` + `up -d --build` → `compose ps` → log SHA. Skip rebuild when no Dockerfile-relevant files changed; abort on uncommitted server-side changes.
   - `scripts/install-deploy-timer.sh` — installs `rag-deploy.service` + `rag-deploy.timer`, every 2 min.
   - Read-only deploy key on server; pull via SSH.
   - User's local workflow becomes: `git push` (server picks up within 2 min). Manual instant deploy: `ssh server sudo systemctl start rag-deploy.service`.
3. **Email** — explicitly deferred. When needed: Resend / Postmark / SES / SendGrid via SMTP creds in `.env`. Never self-hosted (Hetzner blocks port 25 outbound; IPs blocklisted). No code yet.

---

## Prod deploy plan (CPX62) — 2026-04-29

Two parts so it can split across days. Box provisioned, SSH key auth works.

### Part 1 — Box ready + stack on raw IP (~3 hours)

End state: full RAG stack running on CPX62, accessible via SSH tunnel. No public access yet.

**1.1 Base hardening (~30 min)**
- Verify SSH key auth, disable password auth in `/etc/ssh/sshd_config` (`PasswordAuthentication no`).
- `apt update && apt upgrade -y`.
- Install `fail2ban`, `ufw` (or rely on Hetzner Cloud Firewall — preferred per CLAUDE.md), `curl`, `git`.
- Install Docker via `get.docker.com`.
- Hetzner Cloud Firewall (panel): SSH 22 from anywhere; **80/443 closed for now** (we'll open to CF IPv4 only in Part 2). Apply firewall to the CPX62.

**1.2 LUKS on `/data` (~30 min)**
- Hetzner CPX62 has a single root disk. Either:
  - (a) Add a Hetzner Volume → format as LUKS → mount at `/data`, OR
  - (b) Carve a LUKS-encrypted file-backed loop device on the root disk (simpler, no extra cost).
- Create `/root/.luks-keyfile` (chmod 0400), use it via `/etc/crypttab` so unlock is automatic at boot.
- `/etc/fstab`: `/data` mounted before docker starts.
- Configure Docker to put its volumes path at `/data/docker` (edit `/etc/docker/daemon.json` → `"data-root": "/data/docker"`), restart Docker.
- Confirm `docker info | grep -i 'docker root dir'` reports `/data/docker`.

**1.3 Repo + .env + first deploy (~60 min)**
- `git clone -b silver-shim https://github.com/automatizari-cc/romanian-rag-assistant.git /opt/rag` (silver-shim has the cpu-1.7 bump and the wget→urllib healthcheck fix; the silver-only files are inert without `-f docker-compose.silver.yml`).
- `cd /opt/rag && cp .env.example .env`. Fill in:
  - `DOMAIN=` actual prod domain
  - `LE_EMAIL=al.expedient@gmail.com`
  - `CLOUDFLARE_API_TOKEN=` (placeholder for now; set in Part 2)
  - `CLOUDFLARE_ZONE_ID=` (placeholder)
  - `OLLAMA_MODEL=qwen2.5:7b` (RoLlama3.1 GGUF still blocked; qwen2.5:7b is the agreed temp choice)
  - `WEBUI_SECRET_KEY=$(openssl rand -hex 32)`
  - `POSTGRES_PASSWORD=$(openssl rand -hex 24)`
  - Leave `EMBED_MAX_BATCH_TOKENS=16384` and `RERANK_MAX_BATCH_TOKENS=16384` — CPX62 has the headroom.
  - `ENABLE_SIGNUP=true` initially (so first-user creation works), flip to false after admin signup.
  - `chmod 600 .env`.
- Pre-pull qwen2.5:7b into the in-compose Ollama:
  ```bash
  docker compose --profile prod up -d ollama
  docker compose --profile prod exec ollama ollama pull qwen2.5:7b
  ```
- Bring up the rest:
  ```bash
  docker compose --profile prod up -d --build
  docker compose --profile prod ps
  ```
- TEI on AMD EPYC + AVX2 should warm up in ~1–2 minutes per model (vs silver's 5+ min). Real TEI image, no shim.
- Watch for any `wget` healthcheck failures elsewhere in the stack (we fixed `ingestion`'s; if `tei-embed`/`tei-rerank` use wget those are still in the real TEI image which has wget, so fine).

**1.4 Smoke test on raw IP (~30 min)**
- From your laptop: `ssh -fNL 8080:127.0.0.1:8080 al@<CPX62-IP>` (`-fN` = background, no shell).
- Browser → `http://localhost:8080`. Sign up first user (admin).
- Send Romanian message *"Salut, ce poți face?"* — should respond in seconds.
- Upload a Romanian text file (or use `curl -X POST /ingest` directly) and ask a grounding question.
- Flip `ENABLE_SIGNUP=false` and `docker compose --profile prod up -d --force-recreate open-webui`.

**END OF PART 1** — stack works on raw IP. Box is firewalled (no inbound 80/443). Browser access is SSH-tunnel only.

### Part 2 — Cloudflare edge integration (~2–3 hours)

End state: production-grade edge with TLS, mTLS, WAF, custom Romanian landing.

**2.1 DNS + initial Cloudflare (~30 min)**
- Cloudflare dashboard: A record `rag.example.ro` → CPX62 IP, proxy = ON (orange cloud).
- SSL/TLS mode: **Full (Strict)**.
- Always Use HTTPS: ON.
- Bot Fight Mode: ON.
- Generate scoped CF API token: `Zone:DNS:Edit` on this zone only. Save in `.env` as `CLOUDFLARE_API_TOKEN`.
- `CLOUDFLARE_ZONE_ID` from zone overview → `.env`.

**2.2 Origin TLS cert via Let's Encrypt DNS-01 (~30 min)**
- Use `scripts/issue-cert.sh` (or whatever the existing one is named — check `scripts/` directory).
- Cert lands at `nginx/certs/{fullchain.pem,privkey.pem}`.
- Auto-renew via systemd timer or cron (also in `scripts/`).
- Verify cert validity: `openssl x509 -noout -dates -subject -in nginx/certs/fullchain.pem`.

**2.3 Authenticated Origin Pulls (mTLS) (~15 min)**
- Cloudflare → SSL/TLS → Origin Server → Authenticated Origin Pulls → enable.
- Download CF's origin pull CA cert from CF docs, place at `nginx/cf-origin-pull-ca.pem`.
- Reload nginx: `docker compose --profile prod up -d --force-recreate nginx`.
- nginx config (already in repo) requires client cert from this CA on 443 — closes the bypass-CF-via-IP attack.

**2.4 Cloudflare advanced rules (~30 min)**
- Rate Limit: 5 req/min/IP on `/auth/*`, 60 req/min/IP on `/api/*`.
- Turnstile: site key + secret for `/auth/login` page. Add keys to `.env` (`TURNSTILE_*` vars if the auth.py code expects them — check first).
- Hetzner Cloud Firewall: open 80/443 to CF IPv4 ranges only. Use `scripts/sync-cf-ips.sh` (cron every 6h) to keep it fresh. Confirm SSH 22 stays open from anywhere (key-only).

**2.5 Custom landing + nginx restart (~30 min)**
- Recreate nginx: `docker compose --profile prod up -d --force-recreate nginx`.
- Browser → `https://rag.example.ro`.
- Custom Romanian landing renders.
- `/login` → `POST /auth/login` flow → Open-WebUI loads after auth.
- Send Romanian chat, upload doc, RAG query — same smoke test as Part 1 but via real domain.

**END OF PART 2** — production ready.

### Deferred (separate sessions)
- **RoLlama3.1 GGUF resolution.** Per CLAUDE.md "Things to watch": still blocked; investigate community GGUF mirrors (bartowski, mradermacher) or build a custom Modelfile from the FP16 repo. Until then, qwen2.5:7b is the prod model.
- **Auto-deploy timer (`rag-deploy.timer`).** Architecture agreed; deferred until after a successful manual prod deploy proves the runbook.
- **Repo Settings UI work.** Enable Dependabot alerts, secret scanning, push protection; require `security` and `codeql` checks on PRs to main.

---

## Local deploy attempts (2026-04-29)

User asked to deploy locally first to validate the stack before paying for the Hetzner box. Two hosts attempted, both abandoned. Useful failure data — informs production sizing.

### Host: `silver`
- **CPU**: Intel Xeon X5650 (Westmere, 2010). **No AVX2.**
- **Outcome**: Hard blocker. TEI 1.5 and 1.7 cpu images both require AVX2; container crash-loops with the same symptom regardless of TEI version. Distro: LMDE 6.
- **Lesson**: AVX2 is non-negotiable for the TEI cpu image. CX53 (AMD EPYC) is fine.

### Host: `opt`
- **CPU**: Intel Core i7-4770 (Haswell, 2013). AVX2 + FMA present, no AVX-512.
- **RAM**: 31 GiB total, **~11 GiB baseline used by desktop session before the stack**.
- **Disk**: 553 GiB free.
- **What worked**:
  - Docker install via `get.docker.com`.
  - Ollama install via `ollama.com/install.sh`. Required override at `/etc/systemd/system/ollama.service.d/override.conf`: `Environment="OLLAMA_HOST=0.0.0.0:11434"` so the in-container `host.docker.internal` could reach it.
  - `gemma4:e4b` (9.6 GB on disk) was already pulled — used as `OLLAMA_MODEL` since RoLlama3.1 GGUF is still blocked.
  - `docker-compose.local.yml` worked exactly as designed (skipped ollama+nginx via `--profile prod` opt-out; `extra_hosts: host.docker.internal:host-gateway` on `ingestion`).
  - TEI cpu-1.7 image actually downloaded artifacts from HF (the 1.5 hf-hub redirect bug is fixed there).
  - `tei-embed` (bge-m3) fully loaded and went `Ready` after **~7 minutes** of warmup. Direct `curl 127.0.0.1:8081/health` returned 200.
- **What didn't**:
  - **TEI 1.5 hf-hub redirect bug** ("relative URL without a base"). Caught with the `cpu-1.5 → cpu-1.7` bump (uncommitted in tree). Already documented above.
  - **`tei-rerank` OOM-killed in a tight loop.** With FP32 default and `RERANK_MAX_BATCH_TOKENS=16384`, bge-reranker-v2-m3 needed > 5 GB live, on top of `tei-embed`'s ~5–6 GB and the 11 GB desktop baseline. `free -h` snapshot during the failure: 27 Gi used, 294 Mi free, **7.4 Gi of 8 Gi swap consumed**. tei-rerank kept reaching `Starting Bert model on Cpu` and then getting killed before warmup finished, restarting every ~6 min.
  - System UI froze during the OOM thrash, prompting the user to abandon local deploy and tear everything down.
- **Lessons for the production deploy**:
  - **Memory budget for the full stack with default settings is ~20 GB just for the two TEI services.** Plus Ollama with `gemma4:e4b` loaded (~10 GB), plus everything else, you want at least 32 GB *with no other tenant*. CX53 is 32 GB and headless — should fit, no margin.
  - **If memory is tight on CX53**, drop both `EMBED_MAX_BATCH_TOKENS` and `RERANK_MAX_BATCH_TOKENS` from `16384` to `4096` in `.env`. ~4× less activation memory per batch.
  - **TEI healthcheck `start_period: 120s` is too short on slow CPUs.** On Haswell, bge-m3 warmup took ~7 min, so the container was marked `unhealthy` before it actually went `Ready`. It self-heals on the next probe cycle — but `ingestion`'s `depends_on` won't wait that long, so dependent services were `Created` and never `Started`. Consider bumping TEI `start_period` to `300s` before the prod deploy. (Not done yet — deferred until we see the actual warmup time on EPYC.)
  - **Open-WebUI 0.5.4 image had to be pulled** — `--build` was needed for `ingestion`; the `up -d` for the rest of the stack pulled fine.

### Teardown done
- `docker compose down -v --remove-orphans` (volumes deleted, no data of value lost).
- All images for this stack `docker rmi`'d, including the stale `cpu-1.5`.
- Ollama systemd unit removed (`/etc/systemd/system/ollama.service` + `.service.d/`); `ollama` user deleted; `gemma4:e4b` model files at `/usr/share/ollama` and `~/.ollama` removed.
- Repo at `~/romanian-rag-assistant` left intact for tomorrow's reuse, but the production deploy will be a fresh `git clone` on CX53.
- Nothing was pushed during this session. Working tree carries the `cpu-1.5 → cpu-1.7` edit only.

---

## Silver deploy outcome (2026-04-29 evening, second attempt)

`opt` was abandoned that morning. User pivoted to `silver` (X5650 / 70 GB / Ubuntu / no AVX2). Built `tei-shim/` (FastAPI + sentence-transformers + torch CPU 2.2.2) to replace TEI on the AVX2-less host. **Stack came up successfully end-to-end. Romanian RAG verified working.**

Lessons we hit, all of which are now captured in code or docs:

1. **HF Hub xet protocol stalled mid-download** with no progress logs and no retries (silver's `xet_*.log` artifacts in `/data` were the smoking gun). Fix: set `HF_HUB_DISABLE_XET=1` + `HF_HUB_DOWNLOAD_TIMEOUT=60` + `HF_HUB_ENABLE_HF_TRANSFER=0` env vars. Now in `docker-compose.silver.yml`. Silver-only (prod uses real TEI which doesn't go through this code path), but worth knowing the workaround if HF xet bites elsewhere.

2. **transformers >=4.49 gates `torch.load` behind `torch>=2.6` per CVE-2025-32434.** We're stuck on `torch==2.2.2` for pre-AVX2 hosts (Westmere SIGILLs on newer torch). bge-m3 ships its weights as `pytorch_model.bin` (a pickle) so it goes through `torch.load`; bge-reranker-v2-m3 ships `safetensors` and is unaffected. Fix: pin `transformers==4.45.2` in `tei-shim/requirements.txt`.

3. **Base `docker-compose.yml` had a broken `wget`-based healthcheck on `ingestion`.** The image is `python:3.12-slim` which has no wget. Container was perpetually `unhealthy` even though `/health` returned 200. This would have hit prod too — fixed in `docker-compose.yml` by switching to `python -c 'urllib.request...'`.

4. **`postgres-data` volume is sticky across `.env` regen.** If you generated different `POSTGRES_PASSWORD` previously and the volume persists, postgres rejects today's password (`FATAL: password authentication failed for user "openwebui"`). Open-WebUI 0.5.4 swallows the real error behind an `UnboundLocalError` in `handle_peewee_migration`. Fix: `docker volume rm romanian-rag_postgres-data` before re-init. Action item: document in README, "if regenerating .env, also wipe postgres-data".

5. **Open-WebUI's `ENABLE_SIGNUP=false` blocks initial admin creation.** The first user normally auto-becomes admin, but only if signup is enabled. Workflow: set `ENABLE_SIGNUP=true`, recreate open-webui, sign up admin, optionally flip back to false. Don't bake into prod default.

6. **ingestion didn't expose `/v1/models`.** Open-WebUI calls `/v1/models` to populate the model dropdown; without it, the dropdown is empty. Added a stub in `ingestion/app/main.py` returning `[{id: settings.OLLAMA_MODEL, ...}]` — single model, since the chat handler uses `settings.OLLAMA_MODEL` regardless of what the client sends.

### Silver final state (left running, useful as ongoing dev/staging box)
- 6 containers healthy: qdrant, postgres, tei-embed (shim, embedder), tei-rerank (shim, reranker), ingestion, open-webui.
- Browser: SSH tunnel from laptop → `http://localhost:8080`. Sign-in works, Romanian chat works, RAG retrieval works (verified with a Bucharest-facts test doc).
- No cleanup needed. If silver gets reused, just `docker compose -f docker-compose.yml -f docker-compose.silver.yml up -d`.

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

- **TEI cpu-1.5 hf-hub redirect bug — fixed by bumping to cpu-1.7 (uncommitted edit).** Confirmed on `opt` 2026-04-29: cpu-1.5 dies at first model-config download with `request error: builder error: relative URL without a base` (hf-hub-0.3.2 inside the image misparses HF Hub redirects). cpu-1.7 downloads fine. The change is a one-line bump in two places in `docker-compose.yml`. Commit it before any deploy or it'll bite again.
- **AVX2 is required for TEI** at any version. Pre-Haswell CPUs (e.g. silver's Xeon X5650) cannot run TEI. Hetzner CX53 uses AMD EPYC = fine.
- **TEI healthcheck `start_period: 120s` is too short on slow CPUs.** Haswell needed ~7 min for bge-m3 warmup. `tei-embed` was marked `unhealthy` and `ingestion`'s `depends_on: tei-embed: {condition: service_healthy}` never resolved. Decide on the prod box whether to bump `start_period` to `300s` or just be patient on first boot.
- **Memory ceiling.** With FP32 default and `*_MAX_BATCH_TOKENS=16384`, the two TEI services together need ~10–12 GB live. Plus Ollama with gemma4:e4b (~10 GB), plus the rest of the stack and OS, the CX53's 32 GB is tight but workable on an idle host. If it OOMs, drop both batch-tokens vars to `4096` in `.env`.
- **RoLlama3.1 GGUF cannot currently be pulled into Ollama** (verified 2026-04-28 against Ollama 0.x.x and the freshly upgraded latest):
  - `ollama pull hf.co/OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M` → `realm host "huggingface.co" does not match original host "hf.co"` (known Ollama bug with the `hf.co` shortcut and HF redirects).
  - `ollama pull huggingface.co/OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M` → `401: Invalid username or password.` (the GGUF repo at this exact path appears not to exist or is gated; the FP16 repo `OpenLLM-Ro/RoLlama3.1-8b-Instruct` is open but Ollama needs GGUF).
  - **Status:** unresolved. `scripts/bootstrap.sh` references `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` and will fail on the production VM until either (a) Ollama upstream fixes the redirect handling for this repo, (b) we find a community GGUF mirror with the right tag, or (c) we switch to a manual `Modelfile` flow that downloads the GGUF from HF directly. **Action item for next session:** verify what GGUFs are actually available for RoLlama3.1, possibly under a different uploader (e.g. bartowski, `mradermacher`).
  - **Workaround in production deploy:** keep `gemma4:e4b` (or another locally-available model) as a temporary `OLLAMA_MODEL` value while RoLlama3.1 access is being figured out.
- **Local-dev mode is wired and working.** `docker-compose.local.yml` is the override; it skips `ollama` and `nginx` (both `profiles: [prod]` in the base compose) and points `ingestion` at the host's Ollama via `host.docker.internal:11434`. Requires the host's Ollama to listen on `0.0.0.0:11434` (default install binds 127.0.0.1, has to be edited via `systemctl edit ollama.service`). `gemma4:e4b` is the working default for the user's local box.
- **Production runbook now requires `--profile prod`** on every `docker compose` command (since adding the profile to ollama+nginx). README and ARCHITECTURE.md updated accordingly.
- **Single-worker assumption.** `ingestion/app/auth.py` rate limiter is in-memory per-process. Compose runs uvicorn with `--workers 1`. If we ever scale to >1 worker, the limiter must move to Redis.
- **`trivy-action@master`** in `.github/workflows/security.yml`. Not pinned to SHA. Dependabot may move it to a version once a release exists; until then, accept the supply-chain risk for simplicity.
- **Open-WebUI is pinned to 0.5.4.** Newer versions may change the `/api/v1/auths/signin` contract or cookie name (`token`); our auth proxy depends on both.
- **Custom landing always shows at `/`.** Already-logged-in users see the landing page (with a JS-detected "Continue" button) rather than being auto-forwarded into Open-WebUI. This was a deliberate simplification — sub-path mounting Open-WebUI is fragile.

---

## User profile (from session)

- GitHub org: `automatizari-cc`. Email: `al.expedient@gmail.com`. Timezone America/New_York.
- Decision style: makes architectural calls quickly when given clear options + a recommendation. Pushes back well ("look at server specs", "short", "give me your input first") when an answer feels generic. Reward: terse, decisive, rationale-led replies.
- Comfort: deploys infra, has Hetzner + Cloudflare in hand, runs Ollama locally on a personal server.
