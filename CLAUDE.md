# CLAUDE.md

Working notes for future sessions on **automatizari-cc/romanian-rag-assistant**. Read this first; defer to `ARCHITECTURE.md` for detailed design and `README.md` for runbook.

---

## What this is

Self-hosted Romanian-language RAG (ingestion + semantic search + chat). Target host: a single **Hetzner CPX62** (16 dedicated AMD EPYC vCPU / 32 GB / 640 GB / 20 TB / no GPU). Status: **internal / research / non-commercial**.

(Originally planned for CX53. Switched to CPX62 because CX wasn't available; CPX62 is strictly better for this workload — dedicated AMD EPYC cores, AVX2/AVX-512, 2× the disk, same RAM.)

GitHub: <https://github.com/automatizari-cc/romanian-rag-assistant> (public).

---

## Behavioral guidelines

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

### 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:
- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them - don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

### 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

### 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:
- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it - don't delete it.

When your changes create orphans:
- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

### 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:
- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:
```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

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
| Custom landing/login | `/login` posts to FastAPI `/auth/login` which validates + proxies to Open-WebUI's signin. **`/` is auth-aware in nginx** — token cookie present → proxy to Open-WebUI's `/`; absent → static Romanian landing. Both paths keep URL bar at `/`. FastAPI proxy returns the JWT in the response body so login.js can seed `localStorage.token` (Open-WebUI 0.5.4's SPA reads localStorage, not the cookie, to render chat vs. login UI). | Option B (server-side validation + rate limit) for the auth flow; **Option A (auto-forward at `/`)** for the post-auth UX after the original "/" → "/c/" → 404 trap. The two are independent decisions. |
| Bot management | Cloudflare **Bot Fight Mode = OFF**. Edge defenses are: Rate Limit on `/auth/*` (5 req/10s/IP), WAF Managed Challenge on **`/login` GET** (full-page nav, where the challenge can render), and Authenticated Origin Pulls. Server-side: nginx rate limit + FastAPI per-IP limiter. | Free-plan BFM has no XHR carve-out and returns a challenge HTML on the `/auth/login` POST that login.js can't render — silent failure. Acceptable for single-tenant non-commercial; revisit if commercial. |
| Container exposure | All services bind to `127.0.0.1` except `nginx` | Origin-bypass attacks have no service to hit even if FW/CF fail open. |
| Doc ingestion path | Two paths, kept separate on purpose. **(a) Admin curl-to-`/ingest`** on `127.0.0.1:8000` — bypasses auth, no doc_id stamping (legacy). **(b) Registered-user `/upload` page** → `POST /kb/upload` (JWT-verified via shared `WEBUI_SECRET_KEY`). Single shared KB; all logged-in users can list + delete any doc. Open-WebUI's chat-UI paperclip still lands in OWU's own store and is **not** wired to our RAG — tell users to use `/upload` instead. | (b) added 2026-04-30 (commit `476600c`). Single-tenant trust model is intentional; per-user isolation can be added later by filtering `retrieve()` on doc owner. |

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
| `30efbdb` | silver smoke-tests clean end-to-end; consolidate fixes for prod | Bundled six findings from the silver deploy: (a) ingestion compose healthcheck wget→urllib (real prod bug — slim image has no wget), (b) added `/v1/models` stub for Open-WebUI's dropdown, (c) silver HF env vars (`HF_HUB_DISABLE_XET`/`HF_HUB_DOWNLOAD_TIMEOUT`/`HF_HUB_ENABLE_HF_TRANSFER`), (d) `transformers==4.45.2` pin for pre-AVX2 hosts (CVE-2025-32434 + torch 2.2.2 lock), plus two doc-only items in CLAUDE.md. |
| `0db492d` | fix three bugs uncovered during CPX62 Part 2 deploy | Three integration bugs from Part 2 smoke testing. |
| `95e3972` | fix login loop end-to-end after CPX62 Part 2 deploy | Five auth/routing bugs (cookie scope, browser cache, CF challenge vs XHR, OWU localStorage contract, redirect target). All committed in one with rationale-first message. |
| `476600c` | add /kb document upload UI for registered users | Registered-user upload UI at `/upload`. New `/kb/{upload,documents,documents/{id}}` endpoints in ingestion, JWT-verified via shared `WEBUI_SECRET_KEY` (HS256, algorithm-confusion-guarded). Single-tenant shared KB; drag-drop with list+delete. 17 new tests; PyJWT 2.12.1 (clears CVE-2026-32597). Behavioral guidelines section added to CLAUDE.md per user request. **Branch hygiene:** merged `silver-shim` → `main` and deleted `silver-shim` on origin and locally — `main` is now the only branch. |
| `fc4c012` | fix: batch embed_batch requests to TEI's --max-client-batch-size | First real `/upload` end-to-end test (2026-05-01) failed: TEI returns 413 on >32 chunks; `embed_batch` was POSTing all chunks in one call. Fixed by looping in slices of `EMBED_CLIENT_BATCH=32` (TEI's default). Latent in `/ingest` too — only worked previously because earlier curl tests used small docs. The 2026-04-30 "smoke-tested same day" claim only verified `/upload` *renders*, not that uploads complete. |

(Working tree clean as of CLAUDE.md last edit. **`main` is the only branch now**; `silver-shim` was deleted after merging — don't recreate it for ad-hoc fixes, commit to `main`.)

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

> **🔔 Last session (2026-05-02) — surface these first thing next session:**
>
> 1. **RoLlama3.1 GGUF unblocked and running in prod.** Pulled `mradermacher/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M` (the `hf.co` redirect bug is gone in current Ollama). Hit a second trap: the GGUF inherited OpenLLM-Ro's upstream `tokenizer_config.json` which ships the **Llama Guard 3 chat template** (a safety classifier), not the Llama 3.1 Instruct template — every prompt was getting classified as "safe"/"unsafe" instead of answered. Fix: custom Modelfile at `ollama/Modelfile.rollama3.1` overriding TEMPLATE with the proper Llama 3.1 Instruct template. Built locally as `rollama3.1:Q4_K_M`. `OLLAMA_MODEL=rollama3.1:Q4_K_M` set on the box. Smoke-tested: cleaner Romanian than qwen (correct `superior` vs qwen's non-word `superios`, idiomatic article agreement), no Chinese drift, "super fast" per user. qwen2.5:7b retained as A/B fallback.
> 2. **Verbosity is prompt+context, not the model.** RoLlama produced near-identical long answer to qwen for the wine-fermentation query — both are faithfully reproducing the structured source chunk because `INGEST_SYSTEM_PROMPT_RO` says *"strict pe contextul furnizat"*. Patch agreed but not yet shipped: tighten the system prompt (add concision + "no list-spam unless asked" + "don't reproduce source structure") + add `"num_predict": 600` in `ollama_chat_stream`. **First thing for next session: ship that patch and re-test.** It's the actual fix for what the user keeps complaining about.
> 3. **Misleading `/upload` "Eroare de rețea la încărcare" still open** (was item #2 yesterday). Cheap UX fix; not blocking. Catch `httpx.HTTPStatusError` in `/kb/upload` and return JSON, or add a FastAPI exception handler that always returns JSON.
> 4. **Source-document errors surfaced during smoke test.** Both models output `vântului` (wind) instead of `vinului` (wine), `Durante` instead of `Pe durata`, and other typos — these are OCR errors in the source PDF, faithfully reproduced. Out of scope for now; could be a corpus-cleanup pass later if quality matters more.

Already done (kept here for breadcrumb only):
- **CPX62 Part 1** — DONE 2026-04-29 evening. See §"CPX62 Part 1 outcome".
- **CPX62 Part 2** — DONE 2026-04-30. See §"CPX62 Part 2 outcome".
- **Doc-upload UI for registered users** — DONE 2026-04-30, deployed and smoke-tested same day (see §"Doc-upload deploy outcome"). Commit `476600c`. Single-tenant shared KB at `/upload`.
- **`embed_batch` TEI batching fix** — DONE 2026-05-01, commit `fc4c012`. First real `/upload` end-to-end test exposed `embed_batch` not respecting TEI's `--max-client-batch-size`. Latent in `/ingest` too.
- **RoLlama3.1 GGUF unblock** — DONE 2026-05-02. Mradermacher mirror works; the real trap was Llama Guard chat template upstream. Modelfile committed as `ollama/Modelfile.rollama3.1`. Running in prod. See §"Last session (2026-05-02)" callout above and Things to watch entries below.

Highest leverage first (still open):

1. **Ship the verbosity patch (system prompt + `num_predict`).** RoLlama is now in prod but answers are still verbose because both models faithfully reproduce the structured source context. Concrete change: tighten `INGEST_SYSTEM_PROMPT_RO` in `ingestion/app/config.py` (concision + "no list-spam unless asked" + "don't reproduce source structure") + add `"num_predict": 600` in `ollama_chat_stream` in `ingestion/app/llm.py`. This is the actual fix for "answers are too long." See §"Last session (2026-05-02)" for the suggested prompt text.
2. **Fold `amd-fix.yml` + remaining out-of-tree edits into a tracked compose file.** **Real urgency** — this just bit us during the doc-upload deploy on 2026-04-30: the runbook command omitted `-f docker-compose.amd-fix.yml`, compose tried to bring tei-rerank back to the base spec image, and the bge-reranker MKL segfault killed it, breaking the whole dependency chain. Until folded, every redeploy on an AMD host risks repeating this. Decision: prefer **(b) create `docker-compose.prod.yml`** that includes the AMD-specific overrides (rerank routed through `tei-shim`, tei-embed healthcheck disabled because the cpu-1.7 image is distroless, ingestion `depends_on` switched to `service_started` for tei-embed) and update the runbook to make `-f docker-compose.yml -f docker-compose.prod.yml` the default. Bundle in the same commit: nothing else is dirty post-2026-04-30 reset (hot patches were equivalent to commits `0db492d` + `95e3972` and were stashed clean during the deploy).
3. **Update `scripts/bootstrap.sh` and `.env.example` to use the RoLlama Modelfile flow.** Bootstrap currently references the broken `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` (doesn't exist as a public repo) and would fail on a fresh deploy. New flow: pull `hf.co/mradermacher/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M`, then `ollama create rollama3.1:Q4_K_M -f /opt/rag/ollama/Modelfile.rollama3.1`. Update `.env.example` to set `OLLAMA_MODEL=rollama3.1:Q4_K_M` as the default. Skipped in 2026-05-02 commit per Surgical Changes — separate commit on its own merit.
4. **Fix misleading `/upload` "Eroare de rețea la încărcare" error.** The frontend's `r.json()` throws on FastAPI's default HTML 500 page and falls into the generic `.catch()` block. Cheap fix: catch `httpx.HTTPStatusError` in `/kb/upload` handler and return JSON with a real `detail`, OR install a FastAPI exception handler that always returns JSON. Cosmetic but cost ~30 min of debugging on 2026-05-01.
5. **Cert auto-renewal cron.** Cert valid until **2026-07-28**. `issue-cert.sh` is a no-op when cert isn't due for renewal, so it's safe to run daily. Need to wire it as a systemd timer running as root (the install commands at the end need root to read the LE state — see §"Things to watch" entry on cert/sudo). Manual fallback: `sudo bash scripts/issue-cert.sh` before mid-July.
6. **Backfill pre-doc_id chunks (only if needed).** Docs ingested via `curl -F file=@... /ingest` before 2026-04-30 don't carry `doc_id` in payload, so they don't appear in the new `/upload` UI list/delete. Chat retrieval still includes them. If the user wants them surfaced or deletable through the UI, scroll the collection, group by `source`, and re-payload with synthetic `doc_id`s.
7. **Switch Hetzner FW management from manual to automated.** Steps: generate Hetzner API token (Read+Write firewalls), put `HCLOUD_TOKEN` and `HCLOUD_FIREWALL_ID` in `.env`, `apt install hcloud-cli` on the box, cron `scripts/sync-cloudflare-ips.sh` every 6h. The script already has the optional automation block (lines 41-55); it's a no-op until those env vars are set.
8. **Deploy automation** (architecture agreed, not coded):
   - `scripts/deploy.sh` — idempotent: git fetch → compare HEADs → reset hard → `compose pull` + `up -d --build` → `compose ps` → log SHA.
   - `scripts/install-deploy-timer.sh` — installs `rag-deploy.service` + `rag-deploy.timer`, every 2 min.
   - Read-only deploy key on server; pull via SSH.
9. **Rate limit on `/kb/upload`.** Deliberately deferred per Simplicity First. Add an nginx `limit_req_zone` for `/kb/` (mirroring `auth_zone`) if abuse becomes a concern. Server-side per-user limit also possible by extending the existing FastAPI in-memory limiter, keyed on JWT user id.
10. **Source-document OCR cleanup pass (low priority).** Smoke testing 2026-05-02 surfaced that the wine-corpus PDF has OCR errors faithfully reproduced by both qwen and RoLlama: `vântului` (wind) for `vinului` (wine), `Durante` for `Pe durata`, `stratul superios` etc. Quality lift if the corpus is cleaned; out of scope until/unless quality complaints persist after the verbosity patch lands.
11. **Email** — explicitly deferred. When needed: Resend / Postmark / SES / SendGrid via SMTP creds in `.env`. Never self-hosted (Hetzner blocks port 25 outbound; IPs blocklisted). No code yet.

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

## CPX62 Part 1 outcome (2026-04-29 evening)

Stack came up healthy on the CPX62 raw IP. Romanian chat + RAG retrieval verified via SSH tunnel. Three substantive divergences from the §"Prod deploy plan Part 1" runbook, all currently encoded in untracked `/opt/rag/docker-compose.amd-fix.yml` on the box:

1. **bge-reranker-v2-m3 segfaults on AMD EPYC under TEI.** TEI loads bge-reranker through Candle + Intel MKL because the model has no ONNX export; MKL's SGEMM trips on Parameter 13 on a non-Intel CPU and the container dies before serving a request. Fix: route rerank through `tei-shim/` (FastAPI + sentence-transformers, pure PyTorch, no MKL). Embed stays on real TEI cpu-1.7 because bge-m3 *does* have ONNX and TEI uses ONNX Runtime there — no MKL involvement.
2. **TEI cpu-1.7 image is distroless.** No shell, no wget, so the base compose's `wget`-based healthcheck cannot run. Override disables `tei-embed`'s healthcheck. Knock-on: `ingestion`'s `depends_on: tei-embed: {condition: service_healthy}` had to drop to `service_started` since there's no health to wait on. tei-embed warms in ~30s on EPYC, well before the first user request, so the looser dependency is fine in practice.
3. **`tei-rerank` `start_period` bumped to 600s** (was 120s in base). The shim downloads the model from HF on first boot.

Full content of `/opt/rag/docker-compose.amd-fix.yml` (folding target for open-work item 2):

```yaml
services:
  tei-rerank:
    image: tei-shim:latest
    build:
      context: ./tei-shim
    command: ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80", "--workers", "1"]
    environment:
      MODE: rerank
      MODEL_ID: ${RERANK_MODEL}
      HF_HUB_DISABLE_XET: "1"
      HF_HUB_DOWNLOAD_TIMEOUT: "60"
      HF_HUB_ENABLE_HF_TRANSFER: "0"
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import urllib.request,sys;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1/health').status==200 else 1)\" || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
      start_period: 600s

  tei-embed:
    healthcheck:
      disable: true

  ingestion:
    depends_on: !override
      qdrant:
        condition: service_healthy
      tei-embed:
        condition: service_started
      tei-rerank:
        condition: service_healthy
      ollama:
        condition: service_healthy
```

The HF_HUB_* env vars are already in `docker-compose.silver.yml`; cheap to also set on the rerank shim in base, or move them to `.env.example` defaults.

**Still TBD (user to confirm in next session):** model that actually loaded (qwen2.5:7b vs other), batch-token settings used (16384 vs 4096), LUKS route taken (Hetzner Volume vs file-backed loop), whether `tei-embed` `start_period` got raised on the box.

---

## CPX62 Part 2 outcome — DONE (2026-04-30)

Domain: **`marius.summitsec.cloud`**. Originally planned as `rag.summitsec.cloud`; user changed to `marius` mid-session. The apex (`summitsec.cloud`) is on Cloudflare with NS migrated from Hostinger.

### Final config

- **2.1 DNS + initial CF.** A record `marius` → CPX62 IP, Proxied (orange). SSL/TLS = Full (Strict). Always Use HTTPS = ON. **Bot Fight Mode = OFF** (see §"2026-04-30 follow-on" below). Scoped DNS-01 token (Zone:Zone:Read + Zone:DNS:Edit, scoped to `summitsec.cloud`).
- **2.2 LE cert.** `scripts/issue-cert.sh` issued cert: `notBefore=Apr 29 19:33 2026 GMT`, `notAfter=Jul 28 19:33 2026 GMT`. Files: `nginx/certs/{fullchain.pem,privkey.pem}` (root-owned). **Renewal cron not yet wired — manual reminder needed before mid-July.**
- **2.3 AOP / mTLS.** AOP toggle ON in CF dashboard (Global mode — shared cert across CF tenants; per-tenant isolation needs paid Custom Certificates). nginx enforces `ssl_verify_client on`.
- **2.4a CF v4 sync.** `scripts/sync-cloudflare-ips.sh` clean. CF v4 ranges current in `nginx/conf.d/cloudflare-realip.conf`.
- **2.4b Hetzner Cloud Firewall.** Inbound: `SSH 22 / Any IPv4`, `TCP 80 / CF v4 list`, `TCP 443 / CF v4 list`. Manual mode (automation deferred to open work item).
- **2.4c CF Rate Limit (free plan, 1 rule).** `auth-rate-limit`: matches `URI Path starts with "/auth/"`, **5 req per 10s per IP, Block, 10s duration**. Free plan caps period and duration at 10s; threshold tuned to 5 to allow typo+retry without blocking legitimate users while still throttling credential-stuffing.
- **2.4d CF WAF Custom Rule.** `login-page-challenge`: matches `URI Path eq "/login" and Hostname eq "marius.summitsec.cloud"`, action **Managed Challenge**. Originally scoped to `/auth/*` per the runbook, **moved to `/login` GET** because Managed Challenge returns an HTML challenge page that XHR POSTs to `/auth/login` cannot render — silent failure looked like wrong creds. Now the challenge fires on the full-page `/login` navigation where the browser can render it; the resulting `cf_clearance` cookie carries through to the subsequent XHR.
- **2.5 Browser smoke test — green.** Login (Romanian form) → land directly in Open-WebUI chat (cookie + localStorage seeded; nginx `/` is auth-aware). Romanian chat works. RAG works when docs ingested via `POST /ingest` (curl from box). `ENABLE_SIGNUP=false` flipped after admin signup.

### 2026-04-30 follow-on — five auth/routing bugs fixed end-to-end

Smoke test surfaced bugs that didn't show in unit tests because they were in the integration: cookie scope, browser cache, CF challenge interaction with XHRs, Open-WebUI's frontend auth-state model, and an invalid redirect target. All fixed in one commit on `silver-shim` (auth.py, login.js, nginx.conf, server.conf.template, test_auth.py):

1. **Open-WebUI 0.5.4's SPA reads `localStorage.token`, not the auth cookie**, to render chat vs. its native login. Cookie-only auth left users on OWU's login form, which is then unreachable through nginx (since we 403 `/api/v1/auths/signin`). Fix: FastAPI proxy now returns the JWT in the response body; login.js seeds localStorage before the redirect. Accepts the same XSS exposure OWU's stock setup already has.
2. **Redirect target was `/c/`, which 404s in OWU's SPA** (its chat URLs are `/c/{chat_id}`; bare `/c/` has no route). Changed to `/`, plus added auth-aware routing in nginx: `$cookie_token` map picks between `/__landing` (static) and `/__webui_root` (proxy). Both internal-only; URL bar stays at `/`.
3. **Browser cached the landing-page response** with no `Cache-Control` headers. Post-login navigation to `/` was served from disk cache, never reached nginx, defeated the cookie routing → login loop. Added `Cache-Control: no-store` on both auth-aware destinations.
4. **Cloudflare Bot Fight Mode (free plan, no XHR carve-out) returned a challenge on `/auth/login` POSTs** that login.js can't render. **Decision: BFM off.** Defense remains: rate limit + WAF challenge on `/login` GET + AOP + per-IP server-side limiter.
5. **WAF Managed Challenge originally on `/auth/*`** — same XHR problem. Moved to `/login` GET.

### Issues hit during the original Part 2 deploy (still relevant for fresh deploys)

1. **Bot Fight Mode location.** CF moved it from "Security → Bots" to "Security → Settings" in their recent dashboard redesign. If neither path works on a given account, the dashboard search bar (`bot fight`) finds the toggle.

2. **`.env` line 40 unquoted value with space** (`WEBUI_NAME=Asistent RAG`). The script sources `.env` via `set -a && . ./.env`; bash parses the unquoted value as `WEBUI_NAME=Asistent` followed by command `RAG`. Fix: quote any value containing whitespace. Worth flagging in `.env.example` so the next operator doesn't fall in.

3. **`scripts/issue-cert.sh` cred-file write bug.** Original: `install -m 0400 /dev/null "$CRED_FILE"` then `printf > "$CRED_FILE"` — mode 0400 has no write bit, so printf failed unless run as root. Fixed locally with `rm -f` + `( umask 077; printf … )` subshell. Box was hot-patched manually with nano.

4. **`docker-compose.yml` nginx missing tmpfs for `/etc/nginx/dynamic-conf.d`.** The nginx image's envsubst entrypoint writes rendered templates to that dir; without it being writable, envsubst silently bails ("dynamic-conf.d is not writable") and nginx starts with no server block for our domain — TLS handshake fails as `SSL_ERROR_SYSCALL`. Fixed locally by adding `tmpfs: [/etc/nginx/dynamic-conf.d]` to the nginx service. Box hot-patched.

5. **Cert install needs sudo on the host.** certbot inside Docker runs as root and writes `nginx/letsencrypt/live/<domain>/{fullchain,privkey}.pem` as root via the bind-mount. The script's subsequent `install` commands run as `al` and can't even `stat` the source files. Worked around manually with `sudo install`. Long-term fix: run the whole script with `sudo` (which also cleanly handles cert renewals via cron). Bake into the cert auto-renewal timer when wired.

6. **`nginx/templates/server.conf.template` deprecated `listen ... http2` directive.** Cosmetic warning since nginx 1.25; nginx still serves correctly. Fixed locally — split into `listen 443 ssl;` + `http2 on;` on both server blocks. No box patch needed.

---

## Doc-upload deploy outcome — DONE (2026-04-30)

Feature deployed end-to-end on `marius.summitsec.cloud`. Browser smoke-test confirmed `/upload` loads after login. Four real lessons came out of the deploy itself (the feature was clean; the recovery path wasn't):

1. **`git pull` as root in `/opt/rag` fails silently.** `/opt/rag` is owned by `al`, but the user was logged in as `root` and got `fatal: detected dubious ownership in repository`. `git pull` aborted, but `docker compose up -d --build` ran anyway — the build cache hit on every layer because the source hadn't actually changed, and a "successful" rebuild quietly produced an image with **none of the new code**. Trap: green `docker compose ps` despite stale code. **Always `sudo -i -u al` (or `sudo -u al git ...`) before pulling.** Update the runbook.

2. **Omitting `-f docker-compose.amd-fix.yml` kills the working stack.** I gave a deploy command without the override. With only the base compose, tei-rerank's expected image is the broken-on-AMD `text-embeddings-inference:cpu-1.7`. The `--force-recreate` propagation through dependencies recreated tei-rerank from spec, and it crash-looped on the MKL segfault, taking ingestion down with it (since ingestion's `depends_on` requires tei-rerank healthy). **Every compose command on this box must carry `-f docker-compose.yml -f docker-compose.amd-fix.yml`** until that file is folded into a tracked compose. This is now Open Work item #1 with full urgency.

3. **Build-cache verification.** If `[4/7] COPY requirements.txt` AND `[7/7] COPY app/` both report `CACHED` on a rebuild despite changes to those files, the source on disk wasn't actually updated. Quick post-deploy check: `docker exec romanian-rag-ingestion-1 grep -c "kb_upload" /app/app/main.py` — non-zero proves the new code reached the running container. Bake into the deploy.sh script when written.

4. **Hot patches on the box matched committed Part 2 fixes byte-for-byte** (commits `0db492d` + `95e3972`). Confirmed by `git diff origin/main -- <hot-patched-files> | grep '^\+' | grep -v '^+++'` — only two cosmetic blank lines came back. Stash without `-u` (keep the untracked `docker-compose.amd-fix.yml` in place), then `git checkout -B main origin/main`, then drop the stash post-verify. The stash from this deploy is `git stash list` entry `On silver-shim: hot-patches superseded by main` — drop after smoke confirms.

### State left on the box after deploy

- HEAD = `476600c` on local branch `main` (tracking `origin/main`).
- `silver-shim` deleted on origin and locally; box's old local `silver-shim` ref also gone (replaced via `checkout -B`).
- All 9 containers healthy under `-f docker-compose.yml -f docker-compose.amd-fix.yml`.
- `docker-compose.amd-fix.yml` still untracked at `/opt/rag/`. Untouched.
- One stash present: hot-patches superseded by main. Drop with `git stash drop` after final UI verify.

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

- **TEI cpu-1.5 hf-hub redirect bug — fixed by bumping to cpu-1.7 (committed in `d41149b`).** Confirmed on `opt` 2026-04-29: cpu-1.5 dies at first model-config download with `request error: builder error: relative URL without a base` (hf-hub-0.3.2 inside the image misparses HF Hub redirects). cpu-1.7 downloads fine. Don't downgrade.
- **AVX2 is required for TEI** at any version. Pre-Haswell CPUs (e.g. silver's Xeon X5650) cannot run TEI. Hetzner CX53 uses AMD EPYC = fine.
- **AMD EPYC + TEI rerank: Intel MKL segfault.** bge-reranker-v2-m3 has no ONNX export, so TEI falls into Candle+MKL, which segfaults on AMD CPUs (Parameter 13 to SGEMM, hit on CPX62 2026-04-29). Fix: route rerank through `tei-shim/`. Embed is fine on real TEI because bge-m3 has ONNX. Currently encoded only in untracked `/opt/rag/docker-compose.amd-fix.yml` on the CPX62 — see §"CPX62 Part 1 outcome". Same file disables `tei-embed`'s wget healthcheck because TEI cpu-1.7 is distroless and has no shell; dependents must drop from `service_healthy` to `service_started`.
- **Cert install needs sudo / root.** certbot in Docker writes the LE state directory as root (Docker bind-mount preserves uid). The host-side `install` commands at the end of `issue-cert.sh` then fail when run as `al` because they can't stat the root-owned source files. Manual workaround: `sudo install -m 0644 …/fullchain.pem …` + `sudo install -m 0640 …/privkey.pem …`. Long-term: run the whole script with sudo (also unblocks cert auto-renewal via systemd timer running as root).
- **AOP "Global" mode = shared CF cert.** Our `setup-origin-pulls.sh` downloads CF's shared origin-pull CA, which validates *any* CF tenant's edge — not just our account. Per-tenant isolation requires paid Advanced Certificate Manager + Custom Certificates. For our threat model (defense-in-depth via auth + Turnstile + rate limits behind CF), shared is acceptable.
- **nginx requires writable `/etc/nginx/dynamic-conf.d`** (a tmpfs in compose). The image's envsubst entrypoint renders `templates/*.template` into that dir at startup; without it being writable, nginx starts but loads no server block for our domain (TLS handshake fails as SSL_ERROR_SYSCALL). Already fixed in the local `docker-compose.yml`; bake into the next commit.
- **TEI healthcheck `start_period: 120s` is too short on slow CPUs.** Haswell needed ~7 min for bge-m3 warmup. `tei-embed` was marked `unhealthy` and `ingestion`'s `depends_on: tei-embed: {condition: service_healthy}` never resolved. Decide on the prod box whether to bump `start_period` to `300s` or just be patient on first boot.
- **Memory ceiling.** With FP32 default and `*_MAX_BATCH_TOKENS=16384`, the two TEI services together need ~10–12 GB live. Plus Ollama with gemma4:e4b (~10 GB), plus the rest of the stack and OS, the CX53's 32 GB is tight but workable on an idle host. If it OOMs, drop both batch-tokens vars to `4096` in `.env`.
- **RoLlama3.1 GGUF: pull works, but the GGUF ships the WRONG chat template.** Resolved 2026-05-02. Two layers of trap:
  - **(1) The original `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` repo doesn't exist** as a public HF repo. The 401 error from earlier attempts was a path-not-found. Use the **`mradermacher/RoLlama3.1-8b-Instruct-GGUF`** community mirror — faithful quantization of the FP16 `OpenLLM-Ro/RoLlama3.1-8b-Instruct`, full quant set including Q4_K_M.
  - **(2) The `hf.co` redirect bug from 2026-04-28 is fixed in current Ollama.** `ollama pull hf.co/mradermacher/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M` works clean.
  - **(3) The GGUF inherits OpenLLM-Ro's upstream `tokenizer_config.json`, which ships the Llama Guard 3 chat template, not the Llama 3.1 Instruct template.** Without an override, every prompt gets classified ("safe"/"unsafe") instead of answered — the model's first response will be the literal word `safe`. Override TEMPLATE in a Modelfile. `ollama/Modelfile.rollama3.1` in the repo has the corrected Llama 3.1 Instruct template + EOT stop tokens.
  - **Deploy flow (post-2026-05-02):** `ollama pull hf.co/mradermacher/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M`, then `ollama create rollama3.1:Q4_K_M -f /opt/rag/ollama/Modelfile.rollama3.1`, set `OLLAMA_MODEL=rollama3.1:Q4_K_M`. `scripts/bootstrap.sh` and `.env.example` still reference the old broken paths — open work item #3 to update them.
- **Local-dev mode is wired and working.** `docker-compose.local.yml` is the override; it skips `ollama` and `nginx` (both `profiles: [prod]` in the base compose) and points `ingestion` at the host's Ollama via `host.docker.internal:11434`. Requires the host's Ollama to listen on `0.0.0.0:11434` (default install binds 127.0.0.1, has to be edited via `systemctl edit ollama.service`). `gemma4:e4b` is the working default for the user's local box.
- **Production runbook now requires `--profile prod`** on every `docker compose` command (since adding the profile to ollama+nginx). README and ARCHITECTURE.md updated accordingly.
- **Single-worker assumption.** `ingestion/app/auth.py` rate limiter is in-memory per-process. Compose runs uvicorn with `--workers 1`. If we ever scale to >1 worker, the limiter must move to Redis.
- **`trivy-action@master`** in `.github/workflows/security.yml`. Not pinned to SHA. Dependabot may move it to a version once a release exists; until then, accept the supply-chain risk for simplicity.
- **Open-WebUI is pinned to 0.5.4.** Newer versions may change the `/api/v1/auths/signin` contract, the `token` cookie/localStorage key, or the bare `/c/` route behavior; our auth proxy + nginx auth-aware `/` depend on all of them. Bump cautiously.
- **Open-WebUI's frontend reads `localStorage.token`, not the auth cookie**, to decide whether to render chat or its login form. The FastAPI `/auth/login` proxy returns the JWT in the JSON body specifically so login.js can seed localStorage. Without it, you land on OWU's login form even with a valid cookie set. Keep this contract intact across any auth-flow refactor.
- **`/` is auth-aware in nginx** (replaces the original "landing always shows at `/`" model). nginx.conf's `$cookie_token` map routes `/` → `/__landing` (static) or `/__webui_root` (proxy). Both have `Cache-Control: no-store` because without it, the browser caches one branch and serves it stale on the next visit, breaking the cookie-based switch (login loop).
- **Cloudflare Bot Fight Mode is OFF — keep it off.** Free-plan BFM has no XHR carve-out; it returns a challenge HTML on `/auth/login` POSTs, which login.js cannot render — login fails silently with "network error." Edge defenses without BFM: Rate Limit on `/auth/*`, WAF Managed Challenge on `/login` GET, AOP, server-side rate limit. Sufficient for non-commercial.
- **Open-WebUI's UI upload (paperclip / `+`) bypasses our RAG — tell users to use `/upload` instead.** Files dropped via OWU's chat-UI paperclip land in OWU's own internal store, not our Qdrant, so chat answers about them come from OWU's built-in RAG (which is wrong — saw "Cotnari is in Ilfov" instead of Iași in 2026-04-30 testing). Our `/upload` page (commit `476600c`) is the right path for registered users; admin curl-to-`/ingest` is still the right path from the box.
- **Pre-doc_id chunks are invisible to `/upload` UI.** Docs ingested via `curl -F file=@... /ingest` before 2026-04-30 don't carry `doc_id`/`uploaded_by`/`uploaded_at` payload fields. Chat retrieval still includes them (no payload filter on `retrieve()`), but they don't show up in `GET /kb/documents` and can't be deleted via `DELETE /kb/documents/{id}`. Backfill is straightforward (scroll, group by `source`, re-payload with synthetic doc_ids) — open work item.
- **`-f docker-compose.amd-fix.yml` is mandatory on every `docker compose` command on the CPX62.** Forgetting it makes compose recreate `tei-rerank` from the broken-on-AMD base image (Intel MKL segfault), which crash-loops and takes ingestion down with it. Until the file is folded into a tracked `docker-compose.prod.yml` (open work item #1), every operation needs `docker compose -f docker-compose.yml -f docker-compose.amd-fix.yml --profile prod ...`. Bit us during the 2026-04-30 doc-upload deploy.
- **`git pull` as root in `/opt/rag` fails silently.** The repo is `al`-owned; root gets `fatal: detected dubious ownership in repository at '/opt/rag'` and the pull aborts. **A subsequent `docker compose ... up -d --build` will then succeed with all-CACHED layers** (since source didn't change), producing an image that contains none of the new code. Always `sudo -i -u al` (or `sudo -u al git ...`) before pulling. Bit us 2026-04-30.
- **Verify code actually reached the running container.** After a redeploy, `docker exec romanian-rag-ingestion-1 grep -c "<known-new-symbol>" /app/app/main.py` is the cheapest proof that the new source got into the image. Plus `curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/<new-route>` for a known new route — `404` means stale, `2xx`/`401` means live.
- **`main` is the only branch.** `silver-shim` was deleted on origin and locally on 2026-04-30 after merging. Don't recreate it for ad-hoc fixes — commit to `main`. The CPX62 box was switched from local `silver-shim` to local `main` via `git stash push -m ... && git checkout -B main origin/main` on the same date.
- **qwen2.5:7b is now the A/B fallback, not the primary.** RoLlama3.1 (via `rollama3.1:Q4_K_M`) is the running model as of 2026-05-02. qwen is kept on disk (~4.7GB) for side-by-side comparison while RoLlama proves itself in real use. Switch back is a one-liner: `sed -i 's|^OLLAMA_MODEL=.*|OLLAMA_MODEL=qwen2.5:7b|' .env && docker compose ... up -d --force-recreate ingestion`. Quality difference observed on 2026-05-02 smoke test: RoLlama produced cleaner Romanian (correct `superior` vs qwen's `superios` non-word, idiomatic article agreement, no Chinese drift). Verbosity is similar between the two — that's a prompt issue, not a model issue.
- **CF Rate Limit free-plan caps period and duration at 10 seconds.** Standard `5 req/min` advice from runbooks doesn't translate directly. We use 5 req per 10s per IP, Block, 10s duration — looser per-minute rate than ideal, but combined with the WAF challenge on `/login` GET it still meaningfully throttles credential stuffing.
- **Cert renewal is not yet automated.** Cert valid until **2026-07-28**. Before then: either run `sudo bash scripts/issue-cert.sh` manually, or wire a systemd timer running the script as root (the cert install steps need root regardless — see "Cert install needs sudo" entry above).
- **`embed_batch` must respect TEI's `--max-client-batch-size`.** Default is 32. Sending >32 chunks in one POST returns 413 from TEI, which surfaces as 500 from ingestion. Fixed in `fc4c012` via `EMBED_CLIENT_BATCH=32` constant in `embed.py`. If TEI is ever started with a different `--max-client-batch-size`, update the constant to match. The current TEI on the box runs with `--model-id=BAAI/bge-m3 --max-batch-tokens=16384 --pooling=cls` — no client-batch override, so 32 is correct.
- **`/upload` frontend reports any non-JSON server error as "Eroare de rețea la încărcare."** The `.then(r.json())` chain in `nginx/html/static/upload.js` throws on FastAPI's default HTML 500 page and the catch shows the generic network-error message. Status code, real detail, and stack trace are all hidden from the user. When debugging `/upload` failures, **always check ingestion logs first**, not the browser — the browser will mislead you. Open work item to fix the rendering, but until then this is the trap.
- **Verbosity guardrails are missing — applies to RoLlama too, not just qwen.** 2026-05-02 finding: swapping qwen → RoLlama produced near-identical long answers because both models faithfully reproduce the structured source context when told *"strict pe contextul furnizat"*. Real fix has two parts and is open work item #1: (a) tighten `INGEST_SYSTEM_PROMPT_RO` in `ingestion/app/config.py` to add concision + "no list-spam unless asked" + "don't reproduce source structure"; (b) add `"num_predict": 600` in `ollama_chat_stream` in `ingestion/app/llm.py`. Without these, neither model self-limits — both will reproduce the entire retrieved chunk verbatim with bullets and all.

---

## User profile (from session)

- GitHub org: `automatizari-cc`. Email: `al.expedient@gmail.com`. Timezone America/New_York.
- Decision style: makes architectural calls quickly when given clear options + a recommendation. Pushes back well ("look at server specs", "short", "give me your input first") when an answer feels generic. Reward: terse, decisive, rationale-led replies.
- Comfort: deploys infra, has Hetzner + Cloudflare in hand, runs Ollama locally on a personal server.
