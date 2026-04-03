"""
Diagnosis rules — assign actionable diagnosis codes to listing snapshots.

Each rule has:
  - code: machine-readable identifier
  - condition: lambda that checks the snapshot
  - label: human-readable description
  - action: recommended next step
"""
from core.amazon_intel.scoring import CONTENT_CHECKS


DIAGNOSIS_RULES = [
    {
        'code': 'CONTENT_WEAK',
        'condition': lambda s: (
            s.get('sessions_30d') is not None and s['sessions_30d'] > 100
            and s.get('conversion_rate') is not None and s['conversion_rate'] < 0.08
        ),
        'label': 'Good traffic, weak conversion — listing content is the problem',
        'action': 'Review title, bullets, images. Add description if missing.',
    },
    {
        'code': 'KEYWORD_POOR',
        'condition': lambda s: (
            s.get('acos') is not None and s['acos'] > 0.30
            and (s.get('sessions_30d') is None or s['sessions_30d'] < 100)
        ),
        'label': 'High ad spend, low visibility — wrong keywords',
        'action': 'Audit keyword targeting. Pause underperforming keywords.',
    },
    {
        'code': 'VISIBILITY_LOW',
        'condition': lambda s: (
            s.get('conversion_rate') is not None and s['conversion_rate'] > 0.12
            and s.get('sessions_30d') is not None and s['sessions_30d'] < 80
        ),
        'label': 'Good conversion, low sessions — visibility problem',
        'action': 'Increase ad budget or improve organic ranking. Product converts well when seen.',
    },
    {
        'code': 'MARGIN_CRITICAL',
        'condition': lambda s: (
            s.get('gross_margin') is not None and s['gross_margin'] < 0.15
            and s.get('acos') is not None and s['acos'] > 0.20
        ),
        'label': 'Margin too thin for current ad spend',
        'action': 'Reduce ad spend or increase price. Flag for cost review in Ledger.',
    },
    {
        'code': 'QUICK_WIN_IMAGES',
        'condition': lambda s: (
            s.get('conversion_rate') is not None and s['conversion_rate'] > 0.10
            and s.get('image_count', 0) < 6
        ),
        'label': 'Strong conversion with few images — easy improvement',
        'action': 'Add more product images. Expect conversion uplift.',
    },
    {
        'code': 'QUICK_WIN_BULLETS',
        'condition': lambda s: (
            s.get('sessions_30d') is not None and s['sessions_30d'] > 50
            and s.get('bullet_count', 0) < 5
        ),
        'label': 'Getting traffic but missing bullet points',
        'action': 'Fill all 5 bullet points with keyword-rich content.',
    },
    {
        'code': 'BUYBOX_LOST',
        'condition': lambda s: (
            s.get('buy_box_pct') is not None and s['buy_box_pct'] < 0.85
        ),
        'label': 'Losing Buy Box — check price or fulfilment',
        'action': 'Review competitor pricing. Check FBA inventory levels.',
    },
    {
        'code': 'ZERO_SESSIONS',
        'condition': lambda s: (
            s.get('sessions_30d') is not None and s['sessions_30d'] == 0
        ),
        'label': 'No traffic at all — listing may be suppressed or invisible',
        'action': 'Check listing status in Seller Central. May need keyword overhaul.',
    },
    {
        'code': 'NO_PERFORMANCE_DATA',
        'condition': lambda s: s.get('sessions_30d') is None,
        'label': 'No business report data — cannot assess performance',
        'action': 'Ensure this ASIN appears in the next Business Report download.',
    },
]


def run_diagnosis(snapshot: dict) -> dict:
    """
    Run all diagnosis rules and content checks against a snapshot.
    Returns {issues: [...], diagnosis_codes: [...], recommendations: [...]}.
    """
    issues = []
    diagnosis_codes = []
    recommendations = []

    # Content checks
    for code, check in CONTENT_CHECKS.items():
        try:
            if check(snapshot):
                issues.append(code)
        except Exception:
            pass

    # Diagnosis rules
    for rule in DIAGNOSIS_RULES:
        try:
            if rule['condition'](snapshot):
                diagnosis_codes.append(rule['code'])
                recommendations.append(f"[{rule['code']}] {rule['action']}")
        except Exception:
            pass

    return {
        'issues': issues,
        'diagnosis_codes': diagnosis_codes,
        'recommendations': recommendations,
    }
