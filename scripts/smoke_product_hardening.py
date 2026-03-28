"""
CLAW product-hardening smoke + light stress test.

Runs against the FastAPI app in-process with model calls mocked so the script is
deterministic and does not spend API credits.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("API_PROVIDER", "claude")
os.environ.setdefault("CLAW_API_KEY", "claw-dev-key-change-in-production")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres123@localhost:5432/claw")
os.environ.setdefault("CLAW_DATA_DIR", tempfile.mkdtemp(prefix="claw-smoke-data-"))
os.environ.setdefault("OLLAMA_BASE_URL", "http://localhost:11434")
os.environ.setdefault("OLLAMA_MODEL", "qwen2.5-coder:7b")
os.environ.setdefault("CLAW_FORCE_API", "true")
os.environ.setdefault("CLAW_ENABLE_WATCHER", "false")
os.environ.setdefault("CLAUDE_MODEL", "claude-sonnet-4-6")
os.environ.setdefault("CLAUDE_OPUS_MODEL", "claude-opus-4-6")

ARCHITECTURE_PROMPT = (
    "Read the CLAW codebase and explain how chat requests flow from the web UI "
    "to the model response. Name the main files involved and point out where "
    "model routing, context retrieval, validation, and streaming happen."
)


def _mock_context_prompt(*_args, **_kwargs):
    return (
        "mock system prompt",
        {
            "context_files": ["core/agent.py", "api/main.py"],
            "context_file_count": 2,
            "retrieved_chunk_count": 6,
            "retrieval_mode": "hybrid",
            "resolved_mention_count": 1,
            "match_quality_counts": {
                "exact": 1,
                "semantic": 3,
                "exact+semantic": 2,
            },
            "retrieved_files": ["core/agent.py", "api/main.py"],
        },
    )


def _extract_sse_json(payload: str) -> list[dict]:
    events: list[dict] = []
    for line in payload.splitlines():
        if not line.startswith("data: "):
            continue
        chunk = line.removeprefix("data: ").strip()
        if not chunk:
            continue
        try:
            events.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return events


def _read_stream_events(client: TestClient, headers: dict[str, str]) -> list[dict]:
    chunks: list[str] = []
    with client.stream(
        "GET",
        "/chat/stream",
        headers=headers,
        params={
            "project": "claw",
            "session_id": f"stream-{uuid.uuid4().hex[:8]}",
            "message": ARCHITECTURE_PROMPT,
            "model_override": "sonnet",
        },
    ) as response:
        for text in response.iter_text():
            if not text:
                continue
            chunks.append(text)
            break
    return _extract_sse_json(''.join(chunks))


def run() -> dict:
    headers = {"X-API-Key": os.environ["CLAW_API_KEY"]}
    fake_response = (
        (
            "Chat requests start in web/src/components/ChatWindow.tsx, go through "
            "the Next.js proxies in web/src/app/api/chat/route.ts or "
            "web/src/app/api/chat/stream/route.ts, then into api/main.py. "
            "The backend wraps the request in MessageEnvelope, calls core/agent.py, "
            "retrieves context through core/context/engine.py, routes models through "
            "core/models/router.py, validates the answer with "
            "core/models/output_validator.py, and streams via process_streaming()."
        ),
        None,
        {"input_tokens": 120, "output_tokens": 48, "total_tokens": 168},
    )

    with patch(
        "core.models.claude_client.ClaudeClient.chat",
        new_callable=AsyncMock,
    ) as mock_chat, patch(
        "core.context.engine.ContextEngine.build_context_prompt",
        side_effect=_mock_context_prompt,
    ):
        mock_chat.return_value = fake_response
        import api.main as main
        from core.agent import ClawAgent

        @asynccontextmanager
        async def _noop_lifespan(_app):
            yield

        main.app.router.lifespan_context = _noop_lifespan
        main._agents.clear()
        config = json.loads((ROOT / "projects" / "claw" / "config.json").read_text())
        main._agents["claw"] = ClawAgent("claw", config)
        main._ollama_status_fast = AsyncMock(return_value={
            "available": False,
            "active_model": None,
            "installed_models": [],
            "vram_warning": False,
        })
        main._project_index_count = AsyncMock(return_value=42)

        client = TestClient(main.app)
        health = client.get("/health", headers=headers)
        status = client.get("/status/summary", headers=headers)

        session_id = f"smoke-{uuid.uuid4().hex[:8]}"
        chat = client.post(
            "/chat",
            headers=headers,
            json={
                "project_id": "claw",
                "session_id": session_id,
                "content": ARCHITECTURE_PROMPT,
                "model_override": "sonnet",
            },
        )

        stream_events = _read_stream_events(client, headers)

        stop = client.post(
            "/chat/stop",
            headers=headers,
            json={"project_id": "claw", "session_id": session_id},
        )

        stress_results = []
        for i in range(8):
            sid = f"stress-{i}-{uuid.uuid4().hex[:6]}"
            resp = client.post(
                "/chat",
                headers=headers,
                json={
                    "project_id": "claw",
                    "session_id": sid,
                    "content": f"smoke message {i}",
                },
            )
            stress_results.append(resp.status_code)

    chat_json = chat.json()
    stream_complete = next((ev for ev in stream_events if ev.get("type") == "complete"), {})
    architecture_markers = [
        "ChatWindow.tsx",
        "api/main.py",
        "core/agent.py",
        "core/context/engine.py",
        "core/models/router.py",
        "core/models/output_validator.py",
    ]
    architecture_prompt_ok = all(
        marker in str(chat_json.get("content", ""))
        for marker in architecture_markers
    )
    return {
        "health_ok": health.status_code == 200 and health.json().get("status") == "ok",
        "status_ok": status.status_code == 200 and "projects" in status.json(),
        "chat_ok": chat.status_code == 200 and bool(chat_json.get("content")),
        "architecture_prompt_ok": architecture_prompt_ok,
        "chat_memory": chat_json.get("metadata", {}).get("memory", {}),
        "stream_ok": bool(stream_complete.get("response")),
        "stop_ok": stop.status_code == 200 and stop.json().get("status") == "stopping",
        "stress_count": len(stress_results),
        "stress_ok": all(code == 200 for code in stress_results),
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
    if not all([
        result["health_ok"],
        result["status_ok"],
        result["chat_ok"],
        result["architecture_prompt_ok"],
        result["stream_ok"],
        result["stop_ok"],
        result["stress_ok"],
    ]):
        raise SystemExit(1)
