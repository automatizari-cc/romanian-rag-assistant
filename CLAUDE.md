# CLAUDE.md

Working notes for future sessions on **automatizari-cc/romanian-rag-assistant**. Read this first; defer to `ARCHITECTURE.md` for detailed design and `README.md` for runbook.

---

## What this is

Self-hosted Romanian-language RAG (ingestion + semantic search + chat). Target host: a single **Hetzner CPX62** (16 dedicated AMD EPYC vCPU / 32 GB / 640 GB / 20 TB / no GPU). Status: **internal / research / non-commercial**.

(Originally planned for CX53. Switched to CPX62 because CX wasn't available; CPX62 is strictly better for this workload — dedicated AMD EPYC cores, AVX2/AVX-512, 2× the disk, same RAM.)

GitHub: <https://github.com/automatizari-cc/romanian-rag-assistant> (public).

---

## What it does — short presentation (for sharing)

**Asistent RAG** is a Romanian-language document assistant. The user uploads documents — PDF, Word files, plain text, Markdown, HTML, or **web pages** (any public URL) — and asks questions about them in Romanian. The assistant searches the content of the uploaded library, generates an answer in plain Romanian, and cites the exact file and page (or URL) each piece of information came from.

### Features

- **Answers strictly from your documents.** The system retrieves the most relevant passages from your library, hands them to the LLM as context, and instructs the model to answer only from that context. If the answer isn't in your library, it returns *"Nu am găsit informații despre acest subiect în baza de cunoștințe."* instead of inventing one. A relevance threshold gates the LLM call on clearly off-topic questions, so abstains return in seconds without burning generation time.
- **Sources after every answer.** Each response ends with a `Surse:` footer listing `[1] filename, p. 42`, `[2] https://example.ro/article`, etc., matching the `[N]` citations in the answer text. Sources for the wine corpus link directly to the right page of the source PDF.
- **Multi-format ingestion.** PDF, Word (.docx), plain text, Markdown, HTML — drag-and-drop on `/upload` for uploaded users, or paste a URL into the same form to ingest a web page. Extraction is server-side (pypdf, python-docx, BeautifulSoup); HTML stripping removes scripts/styles/nav before storage.
- **Romanian-first, multilingual sources.** UI, prompt, and model output are always Romanian. Source documents can be in any language: embeddings (BAAI/bge-m3) and reranker (BAAI/bge-reranker-v2-m3) are multilingual, and RoLlama 3.1 retains enough of Llama 3.1's multilingual understanding to handle non-Romanian context. **Verified 2026-05-04** with an English Wikipedia article ("Cabernet Sauvignon") and a Romanian question — top rerank score 0.722, fluent Romanian answer, English source correctly cited. **Trade-off**: ~75% latency penalty on crosslingual queries (~70s vs ~40s native-Romanian) because the model spends more compute bridging languages.
- **Document management.** A list view shows every uploaded document with size, chunk count, upload time, and a delete button. Single shared library — every logged-in user sees and can manage every document.
- **Mobile-friendly.** Upload page reflows as cards on phones; document list stacks; URL form gets full-width buttons with proper touch targets.

### Privacy

All data — uploaded files, generated chunks, embedding vectors, chat history, retrieved passages — stays on the host server (Hetzner Cloud, Falkenstein DE). **Nothing is ever sent to external AI providers** (no OpenAI, Anthropic, Google, etc.). Inference runs locally inside Docker containers using **RoLlama 3.1-8B-Instruct** (Romanian-primary LLM by OpenLLM-Ro), **BAAI/bge-m3** for embeddings, and **BAAI/bge-reranker-v2-m3** for ranking. Network edge: Cloudflare WAF + rate limit + Authenticated Origin Pulls (mTLS to the box). The host is single-tenant — only invited accounts can sign in.

### Honest limitations

- **CPU-only inference.** ~30–40 seconds to first answer token for native-Romanian queries against the wine corpus (CPX62, 16 vCPU EPYC, no GPU). **~70 seconds for crosslingual queries** (English source + Romanian question — verified 2026-05-04). Off-topic questions return the abstain message in ~4 seconds (no LLM call). GPU pivot would collapse all of these to seconds.
- **Single-tenant shared knowledge base.** All logged-in users see and can edit the same document library. Per-user isolation is feasible (filter retrieval on `uploaded_by`) but not yet implemented.
- **License: non-commercial only.** RoLlama 3.1 is CC-BY-NC-4.0. Commercial use requires swapping to Llama 3.1 (Llama Community License) or Mistral-Nemo-12B (Apache 2.0); architecture supports this without changing embeddings/reranker.
- **Open-WebUI version pinned to 0.5.4.** UI customizations (hide mic/headphones/+ buttons, "Adaugă Documente" shortcut, hero rewrite) are tied to OWU's current DOM/aria-label structure; an OWU upgrade may require re-tightening selectors.

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
| `31d7444` | ollama: ship RoLlama3.1 Modelfile that overrides Llama Guard chat template | Two traps on the model swap: (a) `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` doesn't exist as a public HF repo — use `mradermacher/RoLlama3.1-8b-Instruct-GGUF` mirror instead. (b) The GGUF inherits OpenLLM-Ro's upstream `tokenizer_config.json`, which ships the **Llama Guard 3** chat template, not Llama 3.1 Instruct — without an override, every prompt gets classified as "safe"/"unsafe" instead of answered. Fix: `ollama/Modelfile.rollama3.1` overrides TEMPLATE + EOT stop tokens. Build: `ollama create rollama3.1:Q4_K_M -f ollama/Modelfile.rollama3.1`. Smoke test 2026-05-02: cleaner Romanian than qwen, no Chinese drift, "super fast" generation. qwen2.5:7b kept on disk as A/B fallback. |
| `712638b` | chat: constrain answer length via prompt + num_predict | Verbosity patch: tightened `INGEST_SYSTEM_PROMPT_RO` (3-7 sentences, no list-spam, don't reproduce source structure) + added `num_predict: 600` in `ollama_chat_stream`. Both qwen and RoLlama were faithfully reproducing structured source chunks. |
| `1f16d5c` | chat: break inherited temp=0; tighten no-bullets rule | Two follow-on observations from `712638b` smoke test: (a) repeated chats produced bit-identical output because the mradermacher GGUF inherits `PARAMETER temperature 0` from OpenLLM-Ro's upstream — overridden in Modelfile with `PARAMETER temperature 0.5`. (b) Model still used bullets despite "lists only if asked" — strengthened prompt with explicit "Răspunde în propoziții complete" + capitalized DOAR + concrete trigger words `listează`/`enumerează`. Curl-direct A/B (2026-05-02) proved both fixes work; OWU was just showing cached browser thread. |
| `5b8c8c8` | scripts: terminal chat client for admin/debug use | `scripts/chat.py` — pure-stdlib Python, talks directly to `127.0.0.1:8000/v1/chat/completions`, streams tokens, Romanian UX, exits on `ieși`/`exit`/Ctrl+C. **Surprising A/B finding (2026-05-02):** chat.py is NOT meaningfully faster than OWU — both took ~60s to first token on the same question. The dominant cost is LLM prefill on CPU, not UI rendering. Kept as ops/debug tool, not promoted as a "fast lane" for end users. Setup on box: `echo "alias chat='python3 /opt/rag/scripts/chat.py'" >> ~/.bashrc`. |
| `c660455` | chat: instrument /v1/chat/completions with per-stage timings | Per-stage timing instrumentation: `retrieve()` gains optional `timings: dict \| None` out-param (captures `embed_ms`/`search_ms`/`rerank_ms`); chat handler logs two structured `chat rid=<8hex>` lines (post-retrieval and post-stream) and emits `: rag-timings={...}` SSE comment line before `data: [DONE]` for raw-curl visibility. Comment lines are ignored by OWU/OpenAI clients. Foundation for the latency-reduction commits below. |
| `de434f8` | chat: lower INGEST_TOP_K 20→10 to cut rerank latency in half | First profiled run on prod (2026-05-03) surfaced rerank as the **unexpected #2 cost** at 9–13s/req — second only to Ollama prefill (~50s). Root cause structural: bge-reranker-v2-m3 has no ONNX export, so the AMD-shim path (pure PyTorch, single-worker) is genuinely slow vs real TEI's Candle+ONNX. Halving candidates ~halves rerank time. Two clean A/B runs: rerank 9.3s / 12.8s → 3.8s / 4.0s, total 73–84s → 64–73s. |
| `101d39f` | chat: lower INGEST_TOP_N 5→3 — 38% latency cut, quality holds on 10-Q A/B | After TOP_K landed, Ollama prefill at ~50s was the remaining dominant cost. Napkin: 5→3 chunks drops prompt by ~1024 context tokens, prefill ~31s. Confirmed via 10-question wine-corpus A/B (single-run each, sequential to avoid shim contention): mean total 62.6s → 38.6s (-38%). User's independent quality scoring: 6 wins TOP_N=3, 3 wins TOP_N=5, 1 tie. **Counter-intuitive lesson:** chunks 4–5 were noise diluting attention; multi-aspect questions sometimes got *richer* with fewer chunks. |
| `39e46bd` | chat: tighten prompt faithfulness — drop source paths, forbid verbatim, harden no-bullets | Three orthogonal prompt-faithfulness bugs from the 10-Q review: (1) `[N] (file.pdf#pNN)` citation headers leaked verbatim into prose (Q8/Q9); (2) Q8 TOP_N=5 returned a near-verbatim chunk dump; (3) Q3 TOP_N=3 used bullet lists despite existing rule. **Investigation surfaced a major latent deploy bug:** box's `.env` was bootstrapped on 2026-04-29 with the 1-sentence short prompt; yesterday's verbosity patch (712638b + 1f16d5c) updated `config.py` but never re-synced `.env.example`, so `.env` shadowed the new prompt and *all of today's A/B was unknowingly against the old short prompt*. Three changes here: (a) `config.py` adds no-verbatim + no-citation-leak rules + harder no-bullets ("even if the question seems to suggest enumeration"); (b) `.env.example` re-synced (was 4 days drifted); (c) `build_context_block` emits just `[N]\n{text}` — source filename/page stays server-side, eliminates header-leak at the source. Box `.env` patched manually post-push since pulling the repo doesn't update existing `.env`. Smoke test post-fix: Q3 prose without bullets ✓, Q8 no citation header leak ✓. |
| `b20e05a` | compose: pipe BYPASS_MODEL_ACCESS_CONTROL through to open-webui | Found while creating the first non-admin user (marius@test.com) on 2026-05-03: OWU 0.5.4 default-denies runtime-discovered (non-table) models for non-admin users — the gate is `routers/openai.py:477` (`if user.role == "user" and not BYPASS_MODEL_ACCESS_CONTROL`). When the `model` table is empty (we discover models from `/v1/models`, never define managed entries), the filter returns an empty list to non-admins, so the chat dropdown is empty for everyone except admin. Setting the env var in `.env` was a no-op because `docker-compose.yml` only forwards an explicit env allowlist to `open-webui` and the var wasn't on it. Fix: add `BYPASS_MODEL_ACCESS_CONTROL: ${BYPASS_MODEL_ACCESS_CONTROL:-false}` to compose's open-webui environment block; default `true` in `.env.example` (single-tenant posture). Verified post-recreate: marius@test.com `/api/models` returns 2 entries (rollama3.1:Q4_K_M + arena-model). |
| `47558f5` | compose: fold AMD-host overrides into tracked docker-compose.prod.yml | Open-work item #2 done. New tracked file replaces the untracked `/opt/rag/docker-compose.amd-fix.yml` on the box (tei-rerank → tei-shim, tei-embed healthcheck disabled, ingestion depends_on loosened). Box-side: pulled, switched the deploy command, deleted `amd-fix.yml`. Merged config byte-identical, `up -d` was a no-op (uptimes preserved). Removes the "every compose command must carry `-f docker-compose.amd-fix.yml`" footgun. README and ARCHITECTURE.md runbook updated to use `-f docker-compose.yml -f docker-compose.prod.yml --profile prod` as the default. |
| `f316675` | bootstrap: switch to Modelfile-driven Ollama builds; fix broken HF repo path | Open-work item #3 done. `scripts/bootstrap.sh` now drives `ollama create -f <Modelfile>` instead of `ollama pull`+`ollama cp`, generalised via a `MODELFILE` env var (set → build via Modelfile; empty → `ollama pull` for stock tags). `.env.example` default is now `OLLAMA_MODEL=rollama3.1:Q4_K_M` + `MODELFILE=./ollama/Modelfile.rollama3.1`. Old script referenced `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` (doesn't exist as a public HF repo) — would have failed on a fresh deploy. |
| `0bd1181` | kb: add /kb/url for ingesting web pages with SSRF guard | New `POST /kb/url` accepts `{url}` JSON, JWT-verified via shared `WEBUI_SECRET_KEY`, fetches via httpx, hands bytes to existing parsers, stores chunks under a fresh doc_id with the URL itself as the displayed source. SSRF defenses: scheme allowlist (http/https), reject userinfo, resolve hostname and reject if ANY IP is private/loopback/link-local/multicast/reserved/unspecified (covers round-robin DNS), `follow_redirects=False`, streamed body cap at `MAX_USER_UPLOAD_BYTES`, content-type allowlist, connect/read timeouts. UI: small URL form on `/upload` between dropzone and document list. 21 new tests in `tests/test_url_fetch.py`. Smoke-tested in prod with `https://example.com/` (528 B / 1 chunk) and `https://ro.wikipedia.org/wiki/Vin_rom%C3%A2nesc` (118 KB / 5 chunks); all four SSRF probes (file://, private IP literal, private IP via DNS, localhost-by-name) return 400. |
| `89523cd` | nginx: drop /static/ TTL — revalidate via ETag | Static assets had `expires 1h` + `Cache-Control: public, max-age=3600`. After deploying `0bd1181` upload.js, a user got the new HTML (no-store) but the stale JS, so the new URL form's submit handler wasn't wired and the form silently fell back to default GET. Switched to `Cache-Control: no-cache` so the browser revalidates via `If-None-Match` on every load (304 if unchanged, fresh if changed). Cheap because `/static/` total is <10KB. |
| `857150b` | nginx: cache-bust static assets via ?v=N — Cloudflare overrides origin TTL | Origin started sending `Cache-Control: no-cache` after `89523cd` but **Cloudflare's free-plan default Browser Cache TTL of 4 hours rewrites the header at the edge** to `max-age=14400` — verified via cf-cache-status: MISS request returning the rewritten value. Origin no-cache is necessary but not sufficient. Add `?v=2` to all `<script>`/`<link>` static-asset references in `index.html`/`login.html`/`upload.html`; bump `v` on every JS or CSS change. Recommended one-time CF dashboard fix: Caching → Configuration → Browser Cache TTL → "Respect Existing Headers". Without that flip, the `?v=N` ritual is mandatory for every static-asset change. |
| `81920f5` | chat: gate generation on rerank score + emit Surse footer + harden abstain prompt | Three orthogonal fixes for the "model hallucinates and never cites sources" failure surfaced 2026-05-04 (a Veuve Clicquot question — not in the wine corpus — got a fluent generic answer from pretraining with no [N] citations). (1) `INGEST_RELEVANCE_THRESHOLD` (default 0.55, sigmoid-scale) — if hits empty or top rerank score below threshold, return fixed `INGEST_ABSTAIN_MESSAGE_RO` without invoking Ollama; ~4s round-trip vs ~40s hallucination. (2) `format_sources(hits)` builds a markdown footer mapping each [N] citation to filename or URL (PDFs include page when > 1); emitted as additional content delta chunks between the model's last token and the finish marker, so OWU renders it as part of the same message. (3) `INGEST_SYSTEM_PROMPT_RO` strengthened with a "REGULĂ ABSOLUTĂ" abstain rule at the start. Refactor side-effect: `to_openai_chunk` now suppresses Ollama's empty `done=true` terminator and the caller emits the finish chunk explicitly so the Surse footer can slot in BEFORE the finish_reason. 11 new tests in `tests/test_chat.py`. |
| `b11779a` | compose: forward INGEST_RELEVANCE_THRESHOLD and INGEST_ABSTAIN_MESSAGE_RO to ingestion | Same trap as `b20e05a` (BYPASS_MODEL_ACCESS_CONTROL) — `docker-compose.yml`'s ingestion service has an explicit env allowlist; vars in `.env` don't reach the container unless listed. Without these wired through, the previous commit's threshold and abstain-message settings would have stayed at their `config.py` defaults regardless of `.env` content. Inline default fallback `${INGEST_RELEVANCE_THRESHOLD:-0.55}` so a fresh deploy with no `.env` entry still gets sane behavior. |
| `ed0aceb` | chat: bump INGEST_RELEVANCE_THRESHOLD default 0.3 → 0.55 | First production smoke test of the abstain gate showed 0.3 too permissive against a wine-domain corpus: off-topic "Veuve Clicquot" reranked 0.503 (passed gate, model hallucinated); on-topic "etapele fermentației vinului" reranked 0.729. bge-reranker-v2-m3 returns moderate scores ~0.5 for any domain-adjacent query — the wine-product-catalog page (tepaso.ro) especially elevates wine-brand queries because the brand names appear in product list nav text. 0.55 splits cleanly. Verified post-deploy: Veuve → abstain in 4.2s; "etapele fermentației" → answer with `**Surse:**` footer. |
| `660aff1` | landing: revise hero copy and drop English footer line | User-facing rewrite of the hero paragraph. Switched from formal plural ("Întrebați documentele dumneavoastră") to informal singular ("Vorbește cu documentele tale"), merged paragraphs, changed "se trimit" → "se transmit". Dropped the bilingual footer ("utilizare internă · internal use only") to a single Romanian line. |
| `805f5ab`/`d28913b`/`dd6535f` | nginx: inject OWU UI overrides via sub_filter (hide mic/headphones/+) | OWU 0.5.4 has no admin- or per-user-Custom-CSS field, and the audio-engine dropdowns have no "None" option. Inject a small CSS override into every OWU response via `sub_filter` adding `<link rel="stylesheet" href="/static/owu-overrides.css">` before `</head>`. Hides mic + headphones via aria-label substring matches (covers EN+RO). The `+` attach menu turned out to be a button-inside-a-button: outer `<button data-melt-dropdown-menu-trigger>` → wrapper `<div aria-label="Mai multe"/"More">` → inner `<button aria-label="More">`. Hiding only the inner button left the outer click-area visible; final selector uses `:has()` on the outer trigger plus the wrapper div plus the inner button — covers all three layers. Also disabled upstream gzip (`proxy_set_header Accept-Encoding ""`) so sub_filter sees raw HTML. Three commits because two attempts to find the right `+` selector before landing on the layered approach. |
| `ab8eb77` | nginx: inject 'Adaugă Documente' floating link on every OWU page | Originally bottom-right pill linking to `/upload`. Discoverable shortcut for KB management without typing the URL. Same sub_filter mechanism as `805f5ab` — adds an `<a>` element before `</body>` plus inline CSS for positioning. SVG document icon. |
| `39194f3` | ui: make upload + landing + injected OWU shortcut mobile-friendly | Three areas hit by `(max-width: 640px)` media query: (1) `/upload` body padding reduced, top-aligned (avoid soft-keyboard centering issues), URL form stacks vertically with full-width submit, documents table reflows as labeled stacked cards via `data-label::before` (`upload.js` updated to stamp `data-label` on each `<td>`), delete button widens to ≥44px touch target. (2) Card paddings tightened across landing/login/upload. (3) Floating link moves to bottom-left on phones. |
| `201d34e`/`87db9c5`/`bd3c0c4` | nginx: failed JS-relocate attempts — keep as breadcrumb only | User asked for the "Adaugă Documente" link to sit directly under the chat input, "or at least in mobile." Three iterations of a JS file that finds OWU's chat input form and moves the nginx-injected `<a>` to be a sibling immediately after it. Failed: **OWU 0.5.4 uses ProseMirror, not `<textarea>`**, for the chat input — `document.querySelectorAll('textarea')` returned zero matches and the relocation silently no-op'd. Then: even when the form was found via a different selector, the chat input form's parent is a flex-row container WITHOUT `flex-wrap: wrap`, so a sibling-with-`flex-basis: 100%` doesn't break to a new line; the link sat horizontally beside the form. Approach abandoned in `4a6d515`. |
| `4a6d515` | nginx: place 'Adaugă Documente' fixed top-right, drop JS relocation entirely | Pivoted to a single-position no-JS placement: fixed top-right, just left of the user avatar, z-index 1000. Replaced 📄 emoji with inline SVG document icon (no font dependency, no missing-glyph flash). Deleted `nginx/html/static/owu-upload-link.js`. Trade-off vs. "under the chat box" as originally requested: top-right is durable but not under-input. After two days of failed re-parenting attempts, accepting top-right as the answer. |
| `712ee21` | nginx: inline critical link CSS in <head> to kill FOUC; lower mobile position | Until external `<link>` finished loading, the `<a>` rendered as plain inline text in document body for one paint frame before snapping to its corner — classic FOUC. Inlining the critical positioning rules in a `<style>` block injected by sub_filter ensures the link is at its final position from frame 1. Mobile placement also moved from `top: 0.65rem` (overlapped OWU's header model name) to `top: 3.5rem` (below header band). |
| `96ffe3c` | nginx: desktop pill back to bottom-right; suppress OWU broken-image flash | User reported top-right placement covered OWU's chat-settings/sliders icon. Reverted desktop to `bottom: 1.5rem; right: 1.5rem`. Mobile keeps `top: 3.5rem`. Also added `img { font-size: 0 }` to the inline `<style>` to suppress the browser's broken-image placeholder + alt text — visible as a brief purple/pink fragment in the empty-chat center. **User reports the broken-image flash is STILL visible after this commit** — see open-work item; root cause not identified. |

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

> **🔔 Last session (2026-05-04) — surface these first thing next session:**
>
> **Big wins shipped, all smoke-tested in prod on `marius.summitsec.cloud`:**
> - **URL ingestion** — `POST /kb/url` with full SSRF guard (`0bd1181`). UI form on `/upload` next to the file dropzone. 21 tests. Smoke-tested with `https://example.com/` and `https://ro.wikipedia.org/wiki/Vin_rom%C3%A2nesc`; private-IP / file:// / localhost-by-name probes all return 400.
> - **Hard abstain on low rerank score + Surse footer + hardened prompt** (`81920f5` + `b11779a` + `ed0aceb`). Off-topic queries return "Nu am găsit informații despre acest subiect în baza de cunoștințe." in ~4s without invoking Ollama; on-topic queries get a `**Surse:**` footer mapping `[N]` to filename+page (or URL). Default threshold 0.55 (sigmoid scale on bge-reranker-v2-m3); tuned against the wine corpus where off-topic-but-domain-adjacent (Veuve Clicquot, Liliac) reranked ~0.50 and genuine on-topic (etapele fermentației) reranked ~0.73. 11 new tests.
> - **Open-work items #2 and #3 done.** `47558f5` folds `amd-fix.yml` into tracked `docker-compose.prod.yml` (deletes the "always remember the override flag" footgun); `f316675` updates `bootstrap.sh` to drive `ollama create -f Modelfile` via a `MODELFILE` env var, fixes the broken `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` reference.
> - **OWU UI customizations via nginx `sub_filter`** (`805f5ab` chain): hide mic / headphones / `+` attach buttons (CSS injection); inject "Adaugă Documente" floating link to `/upload`; landing copy rewrite (`660aff1`); language switched to Romanian per-user via OWU admin UI. The `+` button has a wrapped 3-layer DOM (outer `data-melt-dropdown-menu-trigger` + middle `<div aria-label="Mai multe"/"More">` + inner `<button aria-label="More">`); selectors must hit all three.
> - **Mobile-friendly `/upload`** (`39194f3`) — body padding, URL form stacks, document list reflows as cards via `data-label::before`, ≥44px touch targets.
> - **Static-asset cache strategy fixed** (`89523cd` + `857150b`). Origin sends `Cache-Control: no-cache` with ETag revalidation; HTML uses `?v=N` query strings as cache-bust because Cloudflare's free-plan default Browser Cache TTL of 4 hours rewrites origin headers at the edge.
>
> **Surprises worth carrying forward:**
> - **OWU 0.5.4 uses ProseMirror, not `<textarea>`**, for the chat input. Anyone trying to wire JS into the chat input must use `.ProseMirror` or `.input-prose [contenteditable]` — `document.querySelector('textarea')` returns zero matches. Two days lost on a JS-relocate attempt that silently no-op'd because of this.
> - **OWU 0.5.4 chat input form's parent is flex-row WITHOUT `flex-wrap: wrap`.** A sibling-with-`flex-basis: 100%` doesn't break to a new line; it sits horizontally beside the form. Bottom-line: re-parenting the floating link to flow under the chat input doesn't work without modifying OWU's CSS. After three failed iterations, abandoned the attempt and pivoted to a fixed-position pill (`4a6d515`).
> - **OWU's `+` button aria-label is the literal English string `"More"`** — not i18n'd, no Romanian translation. Selector `button[aria-label="More"]` works regardless of UI language.
> - **Cloudflare free-plan Browser Cache TTL = 4h overrides origin headers.** Origin `Cache-Control: no-cache` is necessary but not sufficient — at the edge it gets rewritten to `max-age=14400`. Either flip CF dashboard → Caching → Configuration → Browser Cache TTL → "Respect Existing Headers" (one-time, recommended), or use `?v=N` cache-bust query strings on every static-asset edit.
> - **`docker-compose.yml`'s ingestion service has an explicit env allowlist.** Adding a setting to `.env` does NOT make it reach the container unless the var is also listed in the `environment:` block. Same trap as `BYPASS_MODEL_ACCESS_CONTROL` was for OWU. Fixed for `INGEST_RELEVANCE_THRESHOLD` and `INGEST_ABSTAIN_MESSAGE_RO` in `b11779a`.
> - **bge-reranker-v2-m3 returns moderate scores ~0.5 for any domain-adjacent query**, even when the specific entity isn't in substantive content. The wine product catalog (`tepaso.ro`) elevates wine-brand queries to ~0.50 because the brand names appear in product list nav text. The 0.55 threshold sits cleanly above this noise floor and below genuine on-topic scores (~0.7+).
> - **Inline critical CSS in `<style>` blocks beats external `<link>` for above-the-fold elements** — until external CSS loads, the element renders unstyled. Classic FOUC. `712ee21` moved the `.rag-upload-link` positioning rules to an inline style block; the link is at its final position from frame 1.
>
> **Still open from this session — pick up here:**
> - **Loading glitch — broken-image flash (purple/pink fragment in empty-chat center) STILL VISIBLE** despite `img { font-size: 0 }` global rule (`96ffe3c`). Root cause not identified. The `font-size: 0` trick suppresses `<img>` broken-image placeholders + alt text in most browsers, but the user reports the flash persists. Could be a CSS background-image, an `<svg>` referencing a missing href, an Open-WebUI loader animation, or something else entirely. Next-session diagnostic: open the chat page in Firefox/Chrome DevTools → Network tab → reload → look for any 4xx response or any image-type resource that takes >100ms; OR Performance tab → record page load → find what paints in the center early.
> - **"Adaugă Documente" placement is bottom-right desktop / top-right mobile**, NOT under-chat-input as user originally requested. After three failed JS-relocate attempts (ProseMirror selector miss, then flex-row no-wrap), accepted top-right/bottom-right as the durable answer. If user wants under-input later, the right path is either (a) wait for an OWU upgrade with a stable extension hook, (b) inject CSS that adds `flex-wrap: wrap` to OWU's chat-input parent (risky — could break OWU's intended layout), or (c) fork OWU.
>
> **Still open from prior sessions:**
> - **Misleading `/upload` "Eroare de rețea la încărcare"** error message — cheap UX fix; not blocking.
> - **First-token latency** — current floor is ~38–40s on CPX62 (Ollama prefill on CPU). Cheap levers exhausted. Remaining: ONNX rerank export (~2.5d, throwaway if GPU lands), smaller chunk size, GPU pivot.

---

> **🔔 Last session (2026-05-03) — kept for breadcrumb:**
>
> **Yesterday's top priority is substantially DONE.** Total wall-clock dropped ~75–85s → ~38–40s on CPX62 (~50% reduction). Five commits land it: `c660455` (per-stage timing instrumentation) → `de434f8` (TOP_K 20→10, rerank 9–13s → ~4s) → `101d39f` (TOP_N 5→3, prefill cut, 38% wall-clock saving) → `39e46bd` (prompt-faithfulness — drops source paths, forbids verbatim, harder no-bullets) → `b20e05a` (compose wiring for `BYPASS_MODEL_ACCESS_CONTROL` so non-admins see models).
>
> **Surprises worth carrying forward:**
> - **Rerank was the hidden #2 cost** — 9–13s/req on the AMD-shim path, second only to Ollama prefill. Halving TOP_K halved rerank. Real TEI ONNX path would be sub-second; that's the structural ceiling on the AMD-shim shape.
> - **Fewer chunks ≠ worse quality.** 10-Q wine-corpus A/B on TOP_N=3 vs TOP_N=5 came out 6 wins / 3 losses / 1 tie favoring TOP_N=3 (user's score). Multi-aspect questions (process, comparison, factor list) didn't degrade — sometimes got *better* because chunks 4–5 were noise diluting attention.
> - **`.env` shadows `config.py` defaults — yesterday's verbosity patch never reached prod.** Box `.env` was bootstrapped on 2026-04-29 with the 1-sentence short system prompt. The 2026-05-02 prompt fix only touched `config.py`, never re-synced `.env.example`, so the long prompt never actually applied in prod. Today's A/B was unknowingly against the SHORT prompt — which is why bullets and chunk-dumps survived "the fix." Going forward: any change to env-overridable settings (`INGEST_*`, prompt, model, etc.) MUST be patched into the box's `.env` directly; `git pull` doesn't update existing `.env`.
> - **OWU 0.5.4 stores `enable_signup` in postgres `config` JSON, not env.** ENABLE_SIGNUP env only seeds initial state on a fresh DB. After admin is created, the runtime value is `config.data->ui->enable_signup`. Flip via `UPDATE config SET data = jsonb_set(...)` then restart open-webui.
> - **OWU 0.5.4 default-denies runtime-discovered models for non-admin users.** When the `model` table is empty (we discover models from `/v1/models`), `routers/openai.py:477` filters non-admins to an empty list. Fix: `BYPASS_MODEL_ACCESS_CONTROL=true` in `.env` AND wired through `docker-compose.yml`'s explicit env allowlist. Both required.
> - **Ollama prefill is the new floor on first-token latency.** Today's win shrank prompt size; it didn't speed up CPU prefill itself. Remaining levers (Ollama `num_thread`, Q3_K_M quant, ONNX rerank export) tracked in open-work #1.
>
> **Today's wins shipped + smoke-tested in prod:**
> - **Per-stage timing instrumentation** (`c660455`) — `chat rid=<8hex>` log lines (one post-retrieval, one post-stream) + SSE `: rag-timings={...}` comment for raw-curl visibility. Foundation for all profiling work.
> - **TOP_K 20→10** (`de434f8`) — rerank ~9–13s → ~4s.
> - **TOP_N 5→3** (`101d39f`) — total wall-clock 62.6s → 38.6s mean (10-Q A/B), quality ≥ baseline by user's review.
> - **Prompt-faithfulness tightening** (`39e46bd`) — drops source path from prompt context, forbids verbatim quoting, hardens no-bullets rule. Box `.env` patched manually since pulling repo doesn't update existing `.env`. Smoke-test post-fix: bullets gone, citation header leak gone.
> - **Marius user account** — first non-admin user (marius@test.com, role=user) now able to log in and use chat. Promoted from default `pending` role via DB UPDATE. Required two DB tweaks (config.enable_signup flip + user.role flip) + `BYPASS_MODEL_ACCESS_CONTROL` + compose wiring before model dropdown populated.
>
> **Still open from prior sessions:**
> - **Misleading `/upload` "Eroare de rețea la încărcare"** error message — cheap UX fix; not blocking.
> - **Source-document OCR errors** (corpus-side `vântului`/`vinului` etc.) — quality lift if cleaned, but lower priority now that latency is addressed.

> **🔔 Same-day follow-on (2026-05-03 evening) — read AFTER the latency block above:**
>
> **Two cheap latency levers TESTED, both rejected** (no commits, working tree clean):
> - **`num_thread: 16`** in `ollama_chat_stream` options → 10-Q A/B mean BEFORE 40.3s / AFTER 40.5s. **No-op.** Ollama already uses `runtime.NumCPU()` = 16 on dedicated 16-vCPU EPYC; explicit override does nothing. Don't bother.
> - **Q3_K_M quant** (built `Modelfile.rollama3.1.q3`, ran 10-Q A/B against Q4_K_M) → Q4 40.3s vs Q3 **46.3s mean — +15% SLOWER**. Q3 also showed minor quality regressions (Q6 typo "flavonoli și flavonoli", Q8 off-topic). Counter-intuitive but well-known on CPU: Q3_K's mixed-bit dequant has more arithmetic per byte than Q4_K's; on AMD without specific AVX-512 paths in llama.cpp, dequant overhead exceeds bandwidth savings from smaller weights. Q4_K_M is one of the most CPU-optimized quants. **On GPU this would reverse.** Q3 model + GGUF deleted from box; local `Modelfile.rollama3.1.q3` deleted.
>
> **Crisp prefill/decode breakdown captured for the first time** (mean over 10 questions on Q4_K_M baseline): **prefill 29.7s, decode 6.4s, rerank 4.1s.** Prefill is **~5× more expensive than decode** — confirms first-token latency, not generation, is the dominant remaining cost. *Trap: when writing ad-hoc SSE parsers, the JSON field in the `: rag-timings={...}` comment is `ollama_first_token_ms`, NOT `first_token_ms`. The log-line label uses the short form (see [main.py:262](ingestion/app/main.py#L262)) but the JSON key has the full `ollama_` prefix. A `dict.get('first_token_ms', 0)` parser silently returns 0 for every request and looks exactly like a broken instrumentation bug.*
>
> **Remaining latency levers, with GPU-pivot caveat:**
> - **(c) ONNX rerank export** — biggest structural CPU win (rerank ~4s → ~0.5–1s). Broken into phases A–D, ~2.5 days total: A research/HF-Hub-search/TEI-ONNX-compatibility (4h), B export+inference-parity (4h), C wire real TEI back in for rerank on CPX62 (8h), D 10-Q A/B + quality validation + decide (4h). **Phase A.1 = 30-min HF Hub search for existing `bge-reranker-v2-m3-onnx` community exports — cheapest possible win.** **Strategic catch:** ONNX export is a CPU-AMD-shim workaround. On GPU, TEI's stock `cuda-1.7` image runs `BAAI/bge-reranker-v2-m3` natively (Candle GPU, no MKL segfault — that's CPU-only). **If GPU lands within ~1–2 months, phases B–C are throwaway.** Only durable piece is **Phase C.5 (fold `amd-fix.yml` → `docker-compose.prod.yml`)** — that should be done as its own commit regardless (open-work #2).
> - **Smaller `INGEST_CHUNK_TOKENS` (256 vs 512)** — could halve prefill directly. Requires re-ingest of corpus; quality risk.
> - **GPU pivot** — would collapse Ollama prefill 30s → 1–3s; obsolete the AMD-shim and most of the ONNX work. Discussed 2026-05-03 evening; no hardware decision yet. ARCHITECTURE.md no-GPU posture predates this discussion. Concrete changes if pivoted: `runtime: nvidia` + `devices: gpu` on ollama service in compose; `tei-{embed,rerank}` swap from `cpu-1.7` → `cuda-1.7` images; `tei-shim/` and `docker-compose.amd-fix.yml` deleted; potentially relax quant from Q4_K_M to Q8_0 or FP16. Hardware options: Hetzner GPU Cloud box (replace CPX62), or split-host with GPU just for Ollama via remote `OLLAMA_URL`.
>
> **Other useful fallout:**
> - **Local workstation now has SSH ControlMaster for `46.224.118.59`** in `~/.ssh/config` (ControlPersist 30m). Solves the SSH-starvation-under-load problem; see new Things-to-watch entry below.
> - **Useful fixtures left on box** for next session: `/tmp/lat_run.sh` (10-Q wine-corpus harness), `/tmp/parse_timings.py` (per-stage breakdown extractor — uses correct `ollama_first_token_ms` key), `/tmp/extract_answers.py` (raw SSE → answer-text extractor). Plus `/tmp/lat-num-baseline/`, `/tmp/lat-num16/`, `/tmp/lat-q3/` directories with full SSE traces from today's runs.

Already done (kept here for breadcrumb only):
- **CPX62 Part 1** — DONE 2026-04-29 evening. See §"CPX62 Part 1 outcome".
- **CPX62 Part 2** — DONE 2026-04-30. See §"CPX62 Part 2 outcome".
- **Doc-upload UI for registered users** — DONE 2026-04-30, deployed and smoke-tested same day (see §"Doc-upload deploy outcome"). Commit `476600c`. Single-tenant shared KB at `/upload`.
- **`embed_batch` TEI batching fix** — DONE 2026-05-01, commit `fc4c012`. First real `/upload` end-to-end test exposed `embed_batch` not respecting TEI's `--max-client-batch-size`. Latent in `/ingest` too.
- **RoLlama3.1 GGUF unblock** — DONE 2026-05-02, commit `31d7444`. Mradermacher mirror works; the real trap was Llama Guard chat template upstream. Modelfile committed as `ollama/Modelfile.rollama3.1`. Running in prod.
- **Verbosity patch (prompt + num_predict + temp override)** — DONE 2026-05-02, commits `712638b` + `1f16d5c`. Tightened system prompt, added `num_predict: 600`, overrode silently-inherited `temperature 0` from parent Modelfile. Bullets gone, length appropriate, output varies between runs.
- **Terminal chat client** — DONE 2026-05-02, commit `5b8c8c8`. `scripts/chat.py` for admin/debug use. (Surprising A/B finding from this work moved latency reduction to top priority — see #1 below.)
- **First-token latency reduction (substantially DONE)** — 2026-05-03, four commits: `c660455` (instrumentation), `de434f8` (TOP_K 20→10), `101d39f` (TOP_N 5→3), `39e46bd` (prompt faithfulness). Total wall-clock 75–85s → 38–40s on CPX62 (~50% net). Remaining levers (Ollama `num_thread:16`, Q3_K_M quant, ONNX rerank export) tracked in open-work #1.
- **First non-admin user account created** — 2026-05-03, marius@test.com, role=user. Process turned out to need: enable_signup flipped in postgres config (env var alone doesn't do it after admin exists), user role manually promoted from default `pending` to `user` via DB UPDATE, then `BYPASS_MODEL_ACCESS_CONTROL=true` wired through `docker-compose.yml` (commit `b20e05a`) so non-admins see the model dropdown.

Highest leverage first (still open):

1. **First-token latency reduction (cheap levers exhausted).** 2026-05-03 daytime cut wall-clock 75–85s → 38–40s on CPX62 (~50% net) via three levers: TOP_K 20→10 (`de434f8`), TOP_N 5→3 (`101d39f`), prompt-faithfulness tightening (`39e46bd`). Per-stage breakdown on Q4_K_M baseline (mean 10-Q A/B): **prefill 29.7s, decode 6.4s, rerank 4.1s** — prefill dominates ~5× over decode. **Cheap levers TESTED 2026-05-03 evening, both rejected** (see same-day follow-on callout):
   - ~~Ollama `num_thread: 16`~~ — no-op. Already Ollama default on dedicated 16-vCPU EPYC.
   - ~~Q3_K_M quant~~ — **+15% slower** on AMD CPU (dequant overhead exceeds bandwidth savings; reverses on GPU).

   **Remaining levers, ranked by expected impact ÷ effort:**
   - **(c) ONNX export of bge-reranker-v2-m3** — biggest structural CPU win (~4s rerank floor → ~0.5–1s). ~2.5 days, broken into phases A–D in the same-day follow-on callout. **CPU-AMD-shim workaround; mostly throwaway if GPU lands.** Phase A.1 (30-min HF Hub search for existing exports) is cheapest first move. Phase C.5 (compose fold) overlaps with open-work #2 below — should be done independently.
   - **Smaller `INGEST_CHUNK_TOKENS`** (256 vs 512) — orthogonal lever; could halve prefill directly. Requires re-ingest of corpus; may interact with retrieval quality.
   - **GPU pivot** — would collapse Ollama prefill 30s → 1–3s and obsolete AMD-shim. Discussed 2026-05-03 evening; no hardware decision yet. See same-day follow-on callout for concrete compose changes if pivoted.
2. **Fold `amd-fix.yml` + remaining out-of-tree edits into a tracked compose file.** Until folded, every redeploy on an AMD host risks repeating the bge-reranker MKL segfault. Decision: prefer **(b) create `docker-compose.prod.yml`** that includes the AMD-specific overrides (rerank routed through `tei-shim`, tei-embed healthcheck disabled, ingestion `depends_on` switched to `service_started` for tei-embed) and update the runbook to make `-f docker-compose.yml -f docker-compose.prod.yml` the default. Bundle in the same commit: nothing else is dirty post-2026-04-30 reset (hot patches were equivalent to commits `0db492d` + `95e3972`).
3. **Update `scripts/bootstrap.sh` and `.env.example` to use the RoLlama Modelfile flow.** Bootstrap currently references the broken `OpenLLM-Ro/RoLlama3.1-8b-Instruct-GGUF` (doesn't exist as a public repo) and would fail on a fresh deploy. New flow: pull `hf.co/mradermacher/RoLlama3.1-8b-Instruct-GGUF:Q4_K_M`, then `ollama create rollama3.1:Q4_K_M -f /opt/rag/ollama/Modelfile.rollama3.1`. Update `.env.example` to set `OLLAMA_MODEL=rollama3.1:Q4_K_M` as the default. Skipped in 2026-05-02 per Surgical Changes — separate commit on its own merit.
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
- **Verbosity guardrails are now in place** (commits `712638b` + `1f16d5c`, 2026-05-02). `INGEST_SYSTEM_PROMPT_RO` includes concision + no-bullets-unless-asked + no-source-structure-reproduction. `ollama_chat_stream` sets `num_predict: 600`. Modelfile sets `temperature 0.5` (overrides inherited `0` from parent). If verbosity regresses after a model or prompt change, this is where to look.
- **First-token latency on CPX62 — current floor ~38–40s, bottleneck is Ollama CPU prefill.** As of 2026-05-03, total wall-clock per query is ~38–40s (was ~75–85s before today's three-lever cut). 10-Q A/B mean breakdown on Q4_K_M: **prefill 29.7s, decode 6.4s, rerank 4.1s, embed/search ~80ms.** Prefill is ~5× more expensive than decode — first-token latency, not generation, is the dominant cost. **When latency complaints come in, the UI is *not* the lever.** Cheap box-side levers exhausted (TESTED 2026-05-03 evening): `num_thread:16` is a no-op (Ollama default on dedicated EPYC); Q3_K_M quant is **+15% slower** on AMD CPU (CPU dequant cost beats bandwidth savings — reverses on GPU). Remaining levers: ONNX export of the reranker (escapes the AMD-shim 4s floor — but throwaway if GPU lands), smaller `INGEST_CHUNK_TOKENS` (re-ingest required, quality risk), or GPU pivot. Per-stage timings are in ingestion logs (`chat rid=<8hex> stage=...`) and in the SSE `: rag-timings={...}` comment line emitted before `data: [DONE]`. Open work item #1; same-day follow-on callout has phase-by-phase breakdown for ONNX rerank.
- **Ollama silently inherits parameters from the parent Modelfile via FROM.** 2026-05-02 trap: built `rollama3.1:Q4_K_M` from `hf.co/mradermacher/...:Q4_K_M`. The mradermacher GGUF metadata baked in `PARAMETER temperature 0` (set up for the Llama Guard safety classifier). Our Modelfile only overrode TEMPLATE + stop tokens, so temperature 0 silently carried through → bit-identical output across runs at chat time. Always run `ollama show <model> --parameters` after `ollama create` to verify the actual runtime config — `ollama show --modelfile` shows what *you* set, not what's effective. Currently overridden to `0.5` in `ollama/Modelfile.rollama3.1`.
- **Llama Guard chat template trap on OpenLLM-Ro models.** OpenLLM-Ro's upstream `tokenizer_config.json` for `RoLlama3.1-8b-Instruct` ships the **Llama Guard 3** chat template (a safety classifier with S1-S14 unsafe-content categories), not the Llama 3.1 Instruct template. mradermacher's GGUF mirror inherits this faithfully. Symptom: every prompt returns the literal word `safe` or `unsafe`. Fix: custom Modelfile overriding TEMPLATE — see `ollama/Modelfile.rollama3.1`. If we ever pull a different OpenLLM-Ro variant, expect the same trap.
- **Open-WebUI caches conversation threads in the browser.** 2026-05-02 confusion: identical chat output across runs in OWU after a model/prompt change, even though direct curl proved the new behavior was live. Cause: OWU was rendering a stale thread, not actually re-running. To verify behavioral changes after a deploy, **start a new chat thread in OWU** (don't just hit refresh on the existing one), or bypass with `scripts/chat.py` / curl to `/v1/chat/completions`.
- **`.env` shadows `config.py` defaults — patching the repo isn't enough to change runtime behavior in prod.** `/opt/rag/.env` was bootstrapped from `.env.example` at deploy time and is **not** updated by `git pull`. Editing the `config.py` default for any env-overridable setting (system prompt, INGEST_TOP_*, OLLAMA_MODEL, etc.) only changes the value picked up by a fresh deploy with no `.env`. Existing prod boxes still see the old `.env` value. Lesson learned the hard way: 2026-05-02 verbosity prompt fix (commits 712638b + 1f16d5c) only updated `config.py`, never re-synced `.env.example` and never patched the box's `.env`, so the new prompt didn't take effect until 2026-05-03 when the latency-investigation surfaced the drift. Going forward: any change to an env-overridable value must (a) update `config.py`, (b) update `.env.example`, AND (c) explicitly patch the box's `.env`. The 3-step ritual is the only reliable path.
- **OWU 0.5.4 stores `enable_signup` in postgres `config` JSON, not in env.** `ENABLE_SIGNUP` env var only seeds the initial state on a fresh DB. After admin is created, the runtime value is `config.data->ui->enable_signup` and the env var becomes a no-op. To open signup later: `UPDATE config SET data = jsonb_set(data::jsonb, '{ui,enable_signup}', 'true'::jsonb)::json WHERE id = (SELECT id FROM config ORDER BY id DESC LIMIT 1)` then `docker compose ... restart open-webui`. Same shape for closing it again. Bit us 2026-05-03 when creating Marius — env was true but signup still 403'd until the DB flip.
- **OWU 0.5.4 default user role is `pending`, not `user`.** New signups can authenticate but get a "pending activation" page until promoted. Promote via admin UI or directly: `UPDATE "user" SET role='user' WHERE email='<addr>'`. Per-request, no restart needed.
- **OWU 0.5.4 default-denies runtime-discovered models for non-admin users.** When the `model` table is empty (we don't define managed models — they come from our `/v1/models` endpoint), `routers/openai.py:477` returns `[]` to non-admins. Symptom: chat dropdown empty for everyone except the admin who configured connections. Fix: set `BYPASS_MODEL_ACCESS_CONTROL=true` in `.env` AND ensure it's in `docker-compose.yml`'s explicit `environment:` allowlist for `open-webui` (env-file alone is not enough — `.env` interpolation is separate from container env). Wired in commit `b20e05a`. **Caveat:** `BYPASS_MODEL_ACCESS_CONTROL=true` is a global override appropriate for single-tenant; if this ever goes multi-tenant, switch to per-model access via the `model` table or the OWU admin UI's model-permission flow instead.
- **Box's SSH starves under heavy LLM inference load.** When ingestion is processing a long-prefill request (concurrent or in flight after a force-recreate), SSH connections to port 22 time out for 1–5 minutes. fail2ban is configured with `sshd` jail, so *some* of this might be transient bans from rapid retries — but the clearer pattern is sshd losing its share of the dedicated EPYC vCPUs while Ollama saturates them. **When SSH timeouts happen during deploy/test work:** wait, don't hammer retries; box recovers on its own when the request finishes. If you're scripting the deploy, prefer `nohup ... > /tmp/x.out &` followed by `until grep -q DONE /tmp/x.out; do sleep 5; done` over keeping SSH session open during long-running work.
- **SSH ControlMaster neutralizes the starvation pain client-side.** User's `~/.ssh/config` (as of 2026-05-03 evening) has multiplexing for `46.224.118.59`: `ControlMaster auto` + `ControlPath ~/.ssh/cm-%r@%h:%p` + `ControlPersist 30m` + `ServerAliveInterval 30`. First connection still has to land while sshd is starved (so open the master *before* kicking off the inference storm: `ssh al@46.224.118.59 -fN`), but every subsequent `ssh` tunnels through the existing master without needing sshd to handshake — sub-second even when the box is hot. Verify the master is up via `ssh -O check al@46.224.118.59`. Drop-in cure for the symptom in the entry above; doesn't help during pure cold-start when sshd has zero CPU share.
- **Per-stage timings live in ingestion logs and in the SSE stream.** Two log lines per chat request, both prefixed `chat rid=<8hex>`: one after retrieval (`stage=retrieve embed_ms=... search_ms=... rerank_ms=... hits=N`) and one after stream completes (`stage=ollama first_token_ms=... ollama_total_ms=... total_ms=...`). Same dict is emitted as `: rag-timings={...}` SSE comment line right before `data: [DONE]` for raw-curl visibility. OWU and OpenAI Python clients ignore SSE comments. `scripts/chat.py` filters on `data: ` and skips them. Use `docker logs --tail 50 romanian-rag-ingestion-1 | grep "chat rid="` to grep, or capture raw SSE with `curl -sN .../v1/chat/completions ... > out.txt; grep rag-timings out.txt`.
- **`docker-compose.yml` only forwards an explicit env allowlist to `open-webui`.** Adding a var to `.env` does NOT make it reach the container unless the var is also listed in the `environment:` block of the open-webui service in `docker-compose.yml`. This is intentional (avoids leaking secrets) but easy to forget — see commit `b20e05a` for the BYPASS_MODEL_ACCESS_CONTROL case. To check what the container actually sees: `docker exec romanian-rag-open-webui-1 env | grep <VAR>`. Empty output = the var didn't make it through.
- **Same trap applies to the `ingestion` service.** Confirmed 2026-05-04 with `INGEST_RELEVANCE_THRESHOLD` and `INGEST_ABSTAIN_MESSAGE_RO` (`b11779a`). Any new `INGEST_*` setting added to `config.py`/`.env.example` must also be added to the `environment:` block of `ingestion` in `docker-compose.yml`, otherwise `.env` overrides are silently ignored. Inline default fallback `${VAR:-default}` so a fresh deploy with no `.env` entry still gets sane behavior.
- **OWU 0.5.4 uses ProseMirror, not `<textarea>`, for the chat input.** `document.querySelector('textarea')` returns zero on the chat page. Use `.ProseMirror` or `.input-prose [contenteditable]` if you need to wire JS into the input. Discovered 2026-05-04 after three failed iterations of a "relocate the floating link to sit under the chat input" attempt that silently no-op'd because of this.
- **OWU 0.5.4 chat input form's parent is flex-row WITHOUT `flex-wrap: wrap`.** A sibling-with-`flex-basis: 100%` (the standard "force a new line in a flex parent" trick) doesn't break to a new line in this layout — it sits horizontally beside the form. There's no clean way to flow content under the chat input via DOM-insertion alone. If you really need a UI element under the chat input, options are: (a) inject CSS that adds `flex-wrap: wrap` to OWU's chat-input parent (risky — could break OWU's intended layout in subtle ways), (b) use absolute positioning with `getBoundingClientRect()` measurements + scroll/resize listeners, or (c) fork OWU.
- **Cloudflare free-plan default Browser Cache TTL is 4 hours, overrides origin headers.** Origin sending `Cache-Control: no-cache` is necessary but not sufficient — at the edge it gets rewritten to `max-age=14400`. Verified via `cf-cache-status: MISS` request returning the rewritten value. Two paths: (1) **one-time CF dashboard fix** — Caching → Configuration → Browser Cache TTL → "Respect Existing Headers". Recommended; durable across all future static-asset edits. (2) **Cache-bust via `?v=N` query strings** in injected `<link>`/`<script>` references — bump on every JS or CSS change. Belt-and-suspenders alongside (1).
- **OWU 0.5.4 has no admin- or per-user-Custom-CSS field.** Any UI customization (hide buttons, inject elements, theme tweaks) has to come via nginx `sub_filter` injection. Pattern: `proxy_set_header Accept-Encoding "";` (disable upstream gzip so sub_filter sees raw HTML), then `sub_filter "</head>" "...";` for CSS/HTML injection. Applied in both `/__webui_root` (auth-aware home) and the catch-all `/` location to cover SPA deep-link refreshes.
- **OWU's `+` button is a button-inside-a-button-inside-a-div.** Outer `<button data-melt-dropdown-menu-trigger>` is the actual click target; middle `<div aria-label="Mai multe"/"More">` (i18n'd) wraps the icon; inner `<button aria-label="More">` (literal English, NOT i18n'd) holds the SVG. Hiding only the inner button leaves the outer trigger as a tiny clickable empty strip. Final selector uses `:has()` on the outer trigger PLUS the wrapper div PLUS the inner button — covers all three layers. See `nginx/html/static/owu-overrides.css` for the working selector chain.
- **OWU model-avatar `<img>` flashes a broken-image placeholder during load.** Visible as a small purple/pink fragment in the empty-chat center for one paint frame. Tried `img { font-size: 0 }` global rule (`96ffe3c`) which suppresses broken-image icon + alt text in most browsers; **user reports the flash is still visible**. Root cause not pinned as of 2026-05-04 evening. Could be a CSS background-image, an SVG `<use href>` to a missing sprite, or an OWU loader animation. Open work item.
- **CSS `<style>` block injection beats external `<link>` for above-the-fold elements.** Until external CSS finishes loading, the element renders unstyled — classic FOUC, visible as a brief jump from default-position to styled-position on page load. For nginx-injected elements (the `Adaugă Documente` link), inline the critical positioning rules in a `<style>` block injected before `</head>` via `sub_filter`. The element is at its final position from frame 1, no flash. Non-critical rules (hover, transitions) can stay in the external file.
- **Crosslingual retrieval works in practice — verified 2026-05-04.** Smoke test: ingested `https://en.wikipedia.org/wiki/Cabernet_Sauvignon` (266 KB → 34 chunks, all in English) via `/kb/url`, asked *"Care sunt principalele caracteristici ale soiului Cabernet Sauvignon?"* in Romanian. Result: top rerank score 0.722 (above 0.55 threshold), fluent Romanian answer with three correct citations to the English URL. **Latency ~75% higher** vs native-Romanian-on-Romanian (70.7s total here vs typical ~40s on the wine corpus); first_token_ms 49.7s vs typical ~30s. Quality fine on this English-Romanian pair; not yet tested on French/German/etc. or smaller languages. The architecture (bge-m3 embeddings + bge-reranker-v2-m3 + RoLlama 3.1's inherited Llama 3.1 multilinguality) explains why this works — but the crosslingual latency penalty is a real cost to flag if users expect native-speed answers on non-Romanian docs.

---

## User profile (from session)

- GitHub org: `automatizari-cc`. Email: `al.expedient@gmail.com`. Timezone America/New_York.
- Decision style: makes architectural calls quickly when given clear options + a recommendation. Pushes back well ("look at server specs", "short", "give me your input first") when an answer feels generic. Reward: terse, decisive, rationale-led replies.
- Comfort: deploys infra, has Hetzner + Cloudflare in hand, runs Ollama locally on a personal server.
