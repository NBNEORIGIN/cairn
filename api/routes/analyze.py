"""
Enquiry Analysis API route.

POST /api/deek/analyze — wraps the existing _analyze_enquiry() tool
so the CRM (and other consumers) can request strategy briefs over HTTP.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
import re

from api.middleware.auth import verify_api_key


router = APIRouter(
    prefix="/api/deek",
    tags=["Deek Analyze"],
    dependencies=[Depends(verify_api_key)],
)


class AnalyzeRequest(BaseModel):
    enquiry: str
    focus: Optional[str] = None


class AnalyzeResponse(BaseModel):
    brief: str
    job_size: str


def _extract_brief_body(raw: str) -> str:
    """Strip the strict-verbatim wrapper and sentinel markers."""
    match = re.search(
        r'<<<ANALYZER_BRIEF_START>>>\s*(.*?)\s*<<<ANALYZER_BRIEF_END>>>',
        raw, re.DOTALL,
    )
    return match.group(1).strip() if match else raw.strip()


def _extract_job_size(raw: str) -> str:
    """Pull job_size from the provenance footer."""
    match = re.search(r'job_size:\s*(small|mid|large)', raw)
    return match.group(1) if match else 'mid'


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_enquiry(req: AnalyzeRequest):
    """Run the enquiry analyzer and return a strategy brief."""
    if not req.enquiry or not req.enquiry.strip():
        raise HTTPException(status_code=400, detail="enquiry is required")

    from core.tools.enquiry_analyzer import _analyze_enquiry

    raw = _analyze_enquiry(
        project_root='',
        enquiry=req.enquiry,
        focus=req.focus,
    )

    # Check for error messages (they don't contain sentinel markers)
    if raw.startswith('analyze_enquiry:'):
        raise HTTPException(status_code=500, detail=raw)

    brief = _extract_brief_body(raw)
    job_size = _extract_job_size(raw)

    return AnalyzeResponse(brief=brief, job_size=job_size)
