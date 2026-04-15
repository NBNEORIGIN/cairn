# Cairn — Self-Hosted Sovereign AI Agent
# Version: 1.1
# This is CLAW's context for maintaining itself.

## What this is
CLAW (Coding and Language Agent Workbench) is a self-hosted AI coding agent
built at D:\claw. It replaces Cursor/Windsurf as the primary AI coding tool
for all NBNE projects. It runs on a Windows machine (Intel i5-10400F,
RTX 3050 8GB, 16GB RAM).

## Architecture
```
D:\claw\
├── api/              FastAPI server — entry point: api/main.py
│   ├── main.py       Routes: /chat, /projects, /debug/tools/{id}, /health
│   └── routes/       whatsapp.py proxy
├── core/
│   ├── agent.py      Main orchestrator — ClawAgent.process()
│   ├── channels/     MessageEnvelope, AgentResponse
│   ├── context/      engine.py (3-tier), indexer.py (pgvector)
│   ├── memory/       store.py (SQLite per project)
│   ├── models/       router.py, claude_client.py, ollama_client.py, openai_client.py
│   └── tools/        registry.py + all tool modules
├── projects/         Per-project config.json + core.md
│   ├── claw/         This project (self-referential)
│   ├── phloe/        Phloe WaaS platform
│   └── manufacturing/ Origin Designed manufacturing app
├── core/wiggum.py    WiggumOrchestrator — outer loop driving CLAW toward a goal
├── tests/            test_claw.py — 36 pytest tests (run: .venv\Scripts\python -m pytest tests/)
├── web/              Next.js chat UI — runs on port 3000 (next dev)
├── tray/             claw_tray.py — system tray process manager (replaces NSSM)
├── vscode-extension/ VS Code panel — Ctrl+Shift+A
└── scripts/          test_agent.py, index_project.py, new_project.py
```

## Running services
- CLAW API: managed by tray app — http://localhost:8765
- Web UI: managed by tray app — http://localhost:3000 (next dev mode)
- Both start automatically at login via the tray app (no NSSM, no admin required)
- To restart: right-click the tray icon → Restart API / Restart Web

## Current model config
- Default: Claude Sonnet (claude-sonnet-4-6) — used by all projects with force_model: "api"
- Fallback: gpt-4o on Claude 429/529
- Opus escalation: architecture/security/trade-off keywords → claude-opus-4-6
- DeepSeek (deepseek-chat): available but NOT auto-routed — must set force_model: "deepseek" in config.json to use
- Local model (disabled): qwen2.5-coder:7b via Ollama — re-enable after RTX 3090
- Routing logic: force_model in config → task_classifier tier → promote to next available tier

## WIGGUM loop
- POST /wiggum  {"goal": "...", "success_criteria": [...], "project": "claw"}
- GET  /wiggum/{run_id}  — poll for status (running | complete | max_iterations | error)
- GET  /wiggum           — list all runs
- Orchestrator iterates: assess (read_only) → plan (read_only) → execute → repeat
- read_only=True in envelope suppresses REVIEW/DESTRUCTIVE tools (assessment passes only)
- Human approval still required for REVIEW/DESTRUCTIVE tools even inside a WIGGUM run

## Indexing status
- CLAW self-index: ✅ BUILT — 69 files, 0 errors (pgvector, nomic-embed-text)
- Phloe index: ✅ BUILT — 1,902 chunks across 260 files, 0 errors
- Tier 2 semantic search is ACTIVE for both projects
- Re-index after major changes: python scripts/index_project.py --project claw

## Tool system
Tools registered for this project. Risk levels:
- SAFE (auto-execute): read_file, search_code, git_status, git_diff, git_log,
  web_fetch, web_check_status, web_search, check_server
- REVIEW (approval required): edit_file, create_file, git_add, git_commit,
  git_branch, git_stash, run_tests, run_migration
- DESTRUCTIVE (explicit confirm): run_command, git_push

## Key files to know
- core/agent.py — ClawAgent, tool dispatch, model routing, _get_api_client()
- core/models/claude_client.py — Anthropic API wrapper, tool_choice
- core/models/openai_client.py — OpenAI wrapper, tool format translation
- core/tools/registry.py — TOOL_SCHEMAS dict, ToolRegistry class
- core/context/engine.py — 3-tier context, pgvector Tier 2
- core/context/indexer.py — CodeIndexer, MAX_CHUNK_CHARS=1500
- .env — API keys, model config, API_PROVIDER, CLAW_FORCE_API
- tests/test_claw.py — 27 tests covering endpoints, tools, models, indexer

## Critical rules
1. Never modify .env directly — always show the change for approval
2. Never git push without explicit user confirmation
3. run_migration is not relevant here (no Django) — don't suggest it
4. The venv is at D:\claw\.venv — always use .\.venv\Scripts\activate on Windows
5. Ports: API=8765, Web UI=3000

## Session Log

### Session 2026-03-24 — claw
- `force_model: "api"` in config.json now means Claude only — DeepSeek is never auto-selected for these projects
- DeepSeek DSML markup leaking as plain text was root cause of broken tool loop and garbled output
- `router.py`: `force_model: "api"` bypasses DeepSeek sub-routing entirely; use `force_model: "deepseek"` to opt in
- `deepseek_client.py`: added `_parse_dsml_tool_call()` fallback to parse DSML text when structured tool_calls absent
- `MessageBubble.tsx`: model label now shows actual provider (`🌊 deepseek` / `☁ claude` / `⚡ local`) not hardcoded "claude"
- Chat history, subproject scoping, token trimming/archiving implemented (sessions + subprojects + archived_sessions tables)
- SessionSidebar component added; ChatWindow integrates subproject dropdown and token bar
- 107 tests passing

## Known issues / recent changes
- Migrated from NSSM Windows services to tray-based process manager (no admin needed)
- OpenAI fallback added (API_PROVIDER=auto) — automatic failover to gpt-4o
- pgvector index built and active for both claw and phloe projects
- Indexer MAX_CHUNK_CHARS=1500 prevents nomic-embed-text 500 errors on dense files
- tool_choice: auto in claude_client.py ensures Claude uses tools reliably
- web_fetch uses verify=False (SSL) to handle Cloudflare-protected sites
- generate_video and generate_image registered but not in permissions (GPU-intensive)
- DeepSeek routing bug fixed 2026-03-24: was silently routing all "api" projects to DeepSeek

## Session 2026-03-28 — claw (bc3db364)
- Implement validation for empty or near-empty responses to prevent silent failures
- Add explicit error handling for validation checks to improve debugging
- Ensure all validation failures produce actionable error messages

## Session 2026-03-28 — claw (1973b4d9)
- Validation checks must handle empty responses as failure conditions
- Implement validation for response content completeness before processing
- System should flag near-empty outputs as quality control failures
- Establish minimum content thresholds for valid assistant responses
- Treat empty/near-empty outputs as critical validation failures requiring correction

## Session 2026-03-28 — claw (06985e28)
- Validation check for empty responses must be implemented to prevent silent failures.
- Near-empty responses should be treated as errors to maintain quality standards.
- Automated validation rules are required to catch incomplete outputs early.

## Session 2026-03-28 — claw (4aaf39ef)
- Use validation checks to detect empty or near-empty responses
- Ensure responses contain substantive content to pass validation
- Address validation failures by improving response completeness
- Monitor for empty outputs as a quality control measure
- Implement safeguards against generating insufficient content
- Treat validation errors as indicators of response quality issues
- Apply validation rules consistently across response generation
- Prioritize content completeness in response design
- Use validation feedback to refine response generation processes
- Maintain minimum content thresholds to avoid validation failures

## Session 2026-03-29 — claw (9adf340a)
- Developer decided to address validation failure for empty/near-empty responses
- Encountered validation system flagging empty content as problematic
- Identified need for robust content generation to pass validation checks
- Established pattern: validation systems require substantive output to succeed
- Discovered gotcha: automated checks can fail on minimal or placeholder content
- Architectural rule: implement meaningful fallback content to avoid validation failures

## Session 2026-03-30 — claw
- Fixed git_commit tool chain: _continue_with_tool_result now passes available tools to the model
- Root cause: after approving git_add, the continuation call passed tools=None, preventing the model from requesting git_commit as a follow-up
- Fix: continuation now provides tools, executes SAFE follow-ups inline, surfaces REVIEW/DESTRUCTIVE follow-ups for approval
- Prior fix (b1abfeb) was incomplete — it fed results back but without tools
- Appended Phloe strategic decisions to projects/phloe/core.md (booking paradigm insight, conversational AI direction)

## Session 2026-04-15 — claw (cairn_delegate Commit 6)
- D-102: Exposed `/api/delegation/` on cairn.nbnesigns.co.uk via nginx location block on Hetzner (178.104.1.152). Minimum-surface approach (Option 1).
- Change is on the Hetzner host in `/etc/nginx/sites-enabled/cairn-business.conf`, not in git. Mirrored in repo at `deploy/nginx/cairn-business.conf.snippet` for reviewability and reprovisioning recovery.
- Rejected: Option 2 (also expose `/ami/*`) — no current cross-module need, principle of minimum public surface. Option 3 (separate `api.` subdomain) — speculative refactor, no current scope justifies.
- Verified publicly: `POST https://cairn.nbnesigns.co.uk/api/delegation/call` returns 401 without `X-API-Key`, 422 with valid key + empty body. Auth uses `CLAW_API_KEY` (middleware env var) not `CAIRN_API_KEY`.
