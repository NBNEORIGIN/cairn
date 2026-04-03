"""
Health scoring engine (0-10 scale).

Deductions applied for performance, ad efficiency, margin, and content issues.
Score starts at 10.0 and gets reduced based on issues found.

Calibrated from real NBNE data:
  - Only 1% have all 5 bullets → softer deduction for missing bullets
  - 92% have main image, avg 4.2 images → LOW_IMAGE_COUNT catches most
  - Score child ASINs; parents are containers
"""


# Content quality checks — each returns True if the issue is present
CONTENT_CHECKS = {
    'TITLE_TOO_SHORT': lambda s: len(s.get('title') or '') < 80,
    'TITLE_TOO_LONG': lambda s: len(s.get('title') or '') > 200,
    'MISSING_BULLETS': lambda s: s.get('bullet_count', 0) < 5,
    'NO_DESCRIPTION': lambda s: not s.get('has_description'),
    'LOW_IMAGE_COUNT': lambda s: 0 < s.get('image_count', 0) < 6,
    'NO_IMAGES': lambda s: s.get('image_count', 0) == 0,
    'NO_KEYWORDS': lambda s: s.get('keyword_count', 0) == 0,
    'WRONG_BRAND': lambda s: (
        s.get('brand') and
        s['brand'].lower().replace(' ', '') not in ('origindesigned', '')
    ),
}


def calculate_health_score(snapshot: dict) -> float:
    """
    Calculate a 0-10 health score for a listing snapshot.
    Higher is better. Deductions for issues found.
    """
    score = 10.0

    # ── Performance deductions (only if business report data exists) ──
    sessions = snapshot.get('sessions_30d')
    if sessions is not None:
        conv = snapshot.get('conversion_rate')
        if conv is not None:
            if conv < 0.05:
                score -= 3.0   # below 5% is critical
            elif conv < 0.08:
                score -= 2.0   # below 8% is poor
        if sessions < 50:
            score -= 1.0       # low visibility

        buy_box = snapshot.get('buy_box_pct')
        if buy_box is not None and buy_box < 0.90:
            score -= 1.5       # losing Buy Box

    # ── Ad performance deductions ──
    acos = snapshot.get('acos')
    if acos is not None:
        if acos > 0.40:
            score -= 2.5       # ACOS above 40% is critical
        elif acos > 0.25:
            score -= 1.5       # above 25% is concerning

    # ── Margin deductions ──
    margin = snapshot.get('gross_margin')
    if margin is not None:
        if margin < 0.15:
            score -= 2.0       # margin below 15% critical
        elif margin < 0.20:
            score -= 1.0       # below 20% concerning

    # ── Content deductions ──
    if snapshot.get('image_count', 0) == 0:
        score -= 1.0
    elif snapshot.get('image_count', 0) < 6:
        score -= 0.5

    if snapshot.get('bullet_count', 0) < 5:
        score -= 0.25          # softer — 99% of listings hit this

    title = snapshot.get('title') or ''
    if len(title) < 80:
        score -= 0.5

    if not snapshot.get('has_description'):
        score -= 0.5

    return max(0.0, min(10.0, round(score, 1)))
