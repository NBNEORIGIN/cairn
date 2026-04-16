"""Cross-module delegation API.

Mounted at ``/api/delegation/*`` in the Deek FastAPI app.

``POST /api/delegation/call`` — invoked by the ``deek_delegate`` MCP tool.
Routes a single one-shot request to Grok 4 Fast (generate) or Claude Haiku 4.5
(review / extract / classify) via OpenRouter, with call-level cost logging
into ``cairn_delegation_log`` (SQLite, ``CLAW_DATA_DIR/claw.db``).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import verify_api_key
from core.delegation import log as delegation_log
from core.delegation.cost import compute_cost_gbp
from core.delegation.openrouter_client import OpenRouterError, call as openrouter_call
from core.delegation.router import (
    VALID_TASK_TYPES,
    VALID_TIER_OVERRIDES,
    route,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/delegation",
    tags=["Delegation"],
    dependencies=[Depends(verify_api_key)],
)


class DelegateRequest(BaseModel):
    task_type: str = Field(..., description="generate | review | extract | classify")
    instructions: str = Field(..., min_length=1)
    context: Optional[str] = None
    output_schema: Optional[dict[str, Any]] = None
    max_tokens: int = Field(4000, ge=1, le=32000)
    tier_override: Optional[str] = Field(
        None, description="grok_fast | haiku | null — overrides task_type routing"
    )
    delegating_session: str = Field(..., min_length=1)
    rationale: str = Field(..., min_length=1)


class DelegateResponse(BaseModel):
    response: str
    parsed: Optional[Any] = None
    model_used: str
    tokens_in: int
    tokens_out: int
    cost_gbp: float
    duration_ms: int
    schema_valid: bool
    warnings: list[str] = []


def _try_parse_and_validate(
    response_text: str, output_schema: dict[str, Any] | None
) -> tuple[Any, bool, list[str]]:
    """Parse JSON and (if schema given) validate. Returns (parsed, schema_valid, warnings).

    - No schema: schema_valid is True (vacuously). parsed is None.
    - Schema + unparsable JSON: schema_valid False, parsed None.
    - Schema + parsed + invalid: schema_valid False, parsed holds the object.
    - Schema + parsed + valid: schema_valid True, parsed holds the object.
    """
    warnings: list[str] = []
    if output_schema is None:
        return None, True, warnings

    # Attempt to strip markdown code fences that LLMs sometimes add.
    stripped = response_text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # drop first fence line and any trailing closing fence
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
        warnings.append("stripped markdown code fences from response before JSON parse")

    try:
        parsed = json.loads(stripped)
    except ValueError as exc:
        return None, False, [f"response was not valid JSON: {exc}"]

    try:
        import jsonschema  # type: ignore

        jsonschema.validate(instance=parsed, schema=output_schema)
        return parsed, True, warnings
    except Exception as exc:  # jsonschema.ValidationError, SchemaError, etc.
        return parsed, False, [*warnings, f"schema validation failed: {exc}"]


def _log_safely(**kwargs: Any) -> None:
    """Insert a log row, swallowing errors so log failures don't break the caller."""
    try:
        delegation_log.insert_log(**kwargs)
    except Exception:  # noqa: BLE001 — deliberate broad catch at log boundary
        logger.exception("cairn_delegation_log insert failed")


@router.post("/call", response_model=DelegateResponse)
async def delegation_call(body: DelegateRequest) -> DelegateResponse:
    # Explicit validation beyond pydantic's type checks.
    if body.task_type not in VALID_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"task_type must be one of {sorted(VALID_TASK_TYPES)}; "
                f"got {body.task_type!r}"
            ),
        )
    if body.tier_override is not None and body.tier_override not in VALID_TIER_OVERRIDES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"tier_override must be one of {sorted(VALID_TIER_OVERRIDES)} "
                f"or null; got {body.tier_override!r}"
            ),
        )

    delegation_log.ensure_table()
    model = route(body.task_type, body.tier_override)

    try:
        result = openrouter_call(
            model=model,
            instructions=body.instructions,
            context=body.context,
            max_tokens=body.max_tokens,
        )
    except OpenRouterError as exc:
        _log_safely(
            delegating_session=body.delegating_session,
            rationale=body.rationale,
            task_type=body.task_type,
            model_used=model,
            tokens_in=0,
            tokens_out=0,
            cost_gbp=0.0,
            duration_ms=0,
            schema_valid=None,
            outcome=exc.kind,
            output_excerpt=str(exc)[:500],
        )
        # Surface as 502 for upstream API errors, 504 for timeout, 422 for refusal.
        status_map = {"timeout": 504, "refusal": 422, "api_error": 502}
        raise HTTPException(
            status_code=status_map.get(exc.kind, 502),
            detail={"outcome": exc.kind, "error": str(exc)},
        ) from exc

    response_text = result["response"]
    tokens_in = result["tokens_in"]
    tokens_out = result["tokens_out"]
    duration_ms = result["duration_ms"]
    cost_gbp = compute_cost_gbp(model, tokens_in, tokens_out)

    parsed, schema_valid, warnings = _try_parse_and_validate(
        response_text, body.output_schema
    )
    outcome = "success" if schema_valid else "schema_failure"

    _log_safely(
        delegating_session=body.delegating_session,
        rationale=body.rationale,
        task_type=body.task_type,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_gbp=cost_gbp,
        duration_ms=duration_ms,
        schema_valid=(schema_valid if body.output_schema is not None else None),
        outcome=outcome,
        output_excerpt=response_text[:500],
    )

    return DelegateResponse(
        response=response_text,
        parsed=parsed,
        model_used=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_gbp=cost_gbp,
        duration_ms=duration_ms,
        schema_valid=schema_valid,
        warnings=warnings,
    )
