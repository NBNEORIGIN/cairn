"""Smoke test for the Commit 1 OpenRouter wrapper.

Run from the deek root with the venv Python:

    D:\\deek\\.venv\\Scripts\\python.exe D:\\deek\\scripts\\delegation_smoke.py

Hits both models with a tiny prompt and prints token counts + cost. Loads
OPENROUTER_API_KEY from D:\\deek\\.env if not already in the environment.
Key value is NEVER echoed.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _load_dotenv(env_path: Path) -> None:
    """Minimal .env loader — enough for smoke testing, no dependency on python-dotenv."""
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    claw_root = Path(__file__).resolve().parents[1]
    _load_dotenv(claw_root / ".env")
    sys.path.insert(0, str(claw_root))

    if not os.getenv("OPENROUTER_API_KEY"):
        print("FAIL: OPENROUTER_API_KEY not set (checked env + D:\\deek\\.env)")
        return 2

    from core.delegation import cost as delegation_cost
    from core.delegation import openrouter_client
    from core.delegation.router import GROK_FAST, HAIKU

    scenarios = [
        (GROK_FAST, "Say the single word 'pong' and nothing else."),
        (HAIKU, "Reply with the JSON object {\"status\":\"ok\"} and nothing else."),
    ]

    total_gbp = 0.0
    for model, prompt in scenarios:
        print(f"\n— {model}")
        try:
            result = openrouter_client.call(
                model=model,
                instructions=prompt,
                max_tokens=64,
            )
        except openrouter_client.OpenRouterError as exc:
            print(f"  ERROR ({exc.kind}): {exc}")
            return 1

        gbp = delegation_cost.compute_cost_gbp(
            model, result["tokens_in"], result["tokens_out"]
        )
        total_gbp += gbp
        preview = (result["response"] or "").strip().replace("\n", " ")[:120]
        print(f"  tokens_in  = {result['tokens_in']}")
        print(f"  tokens_out = {result['tokens_out']}")
        print(f"  duration   = {result['duration_ms']} ms")
        print(f"  cost_gbp   = £{gbp:.6f}")
        print(f"  response   = {preview}")

    print(f"\nTotal smoke-test cost: £{total_gbp:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
