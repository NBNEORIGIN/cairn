"""
VAT handling for the margin engine.

Amazon's order reports give `item_price` as GROSS (VAT-inclusive) for EU and
UK marketplaces, where VAT is collected at point of sale and remitted either
by Amazon (via MFN/marketplace facilitator rules, EU) or by the seller (UK).
For US/CA/AU, no VAT applies (sales tax is handled separately by Amazon in
most cases; from NBNE's perspective the item_price is the net revenue).

Toby confirmed (2026-04-15): "think so, apart from maybe the us" — i.e. back
out VAT for everything EXCEPT the US (and by extension CA/AU, which don't
have a UK-style VAT system).

Net revenue convention (for margin calc):
    net_revenue = item_price / (1 + vat_rate)

For UK: rate = 0.20 (input VAT is reclaimed quarterly — handled separately
by Toby's accountant; the margin engine reports ex-VAT revenue).
For EU marketplaces (DE/FR/IT/ES/NL): Amazon deducts at source under the
EU marketplace facilitator rules, so the net figure is what hits the account
— but the item_price in reports is still the gross figure shown to the
buyer. Back it out at the local rate.

Rates are current as of 2026-04; update when governments change them.
"""
from decimal import Decimal

# Standard VAT rates per marketplace.
# Zero means "don't back anything out" (item_price already represents net).
VAT_RATE: dict[str, Decimal] = {
    'UK': Decimal('0.20'),
    'DE': Decimal('0.19'),
    'FR': Decimal('0.20'),
    'IT': Decimal('0.22'),
    'ES': Decimal('0.21'),
    'NL': Decimal('0.21'),
    'BE': Decimal('0.21'),
    'SE': Decimal('0.25'),
    'PL': Decimal('0.23'),
    # Non-VAT marketplaces — item_price is already net revenue for margin purposes.
    'US': Decimal('0'),
    'CA': Decimal('0'),
    'MX': Decimal('0'),
    'AU': Decimal('0'),
    'JP': Decimal('0'),
    'SG': Decimal('0'),
}


def vat_rate(marketplace: str) -> Decimal:
    """Return the VAT rate for a marketplace (0 if the marketplace is no-VAT)."""
    return VAT_RATE.get(marketplace.upper(), Decimal('0'))


def net_revenue(gross: Decimal, marketplace: str) -> Decimal:
    """
    Convert a gross price to net (ex-VAT) for the given marketplace.
    Returns gross unchanged for no-VAT marketplaces.
    """
    if gross is None:
        return None  # type: ignore[return-value]
    gross = Decimal(str(gross))
    rate = vat_rate(marketplace)
    if rate == 0:
        return gross.quantize(Decimal('0.01'))
    return (gross / (Decimal('1') + rate)).quantize(Decimal('0.01'))


def net_fees(gross: Decimal, marketplace: str) -> Decimal:
    """
    SP-API fee estimates are expressed in the marketplace's local currency.
    Amazon's referral and FBA fees are VAT-exclusive to UK-registered sellers
    (Amazon issues a tax invoice for the VAT separately, reclaimable). For
    margin purposes we treat SP-API fees as already-net — so this is a
    passthrough, kept as a function so the call sites are explicit and any
    future tweak (e.g. Germany seller-registered VAT) has one place to land.
    """
    if gross is None:
        return None  # type: ignore[return-value]
    return Decimal(str(gross)).quantize(Decimal('0.01'))
