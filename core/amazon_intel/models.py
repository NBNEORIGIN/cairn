"""Pydantic request/response models for Amazon Intelligence endpoints."""
from pydantic import BaseModel
from typing import Optional
from datetime import date, datetime


class UploadResponse(BaseModel):
    upload_id: int
    filename: str
    file_type: str
    row_count: int
    skip_count: int
    error_count: int
    errors: list[str]
    status: str


class SkuMappingStats(BaseModel):
    total_skus: int
    unique_m_numbers: int
    unique_asins: int
    by_country: dict[str, int]


class SnapshotSummary(BaseModel):
    asin: str
    sku: Optional[str] = None
    m_number: Optional[str] = None
    title: Optional[str] = None
    health_score: Optional[float] = None
    diagnosis_codes: list[str] = []
    sessions_30d: Optional[int] = None
    conversion_rate: Optional[float] = None
    acos: Optional[float] = None
    your_price: Optional[float] = None
    bullet_count: int = 0
    image_count: int = 0


class ReportSummary(BaseModel):
    report_date: date
    marketplace: Optional[str] = None
    total_asins: int
    avg_health_score: Optional[float] = None
    critical_count: int = 0
    attention_count: int = 0
    healthy_count: int = 0
    no_data_count: int = 0
    summary: Optional[str] = None


class CairnContext(BaseModel):
    module: str = 'amazon_intelligence'
    generated_at: datetime
    data_freshness: dict
    summary: dict
    top_issues: list[dict]
    quick_wins: dict
    margin_alerts: int
    summary_text: str
