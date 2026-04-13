"""
Tests for Amazon Catalog Items API enrichment pipeline.

Covers:
  - Catalog API response parsing
  - Content hash change detection
  - Listing content diffing
  - Embedding text building
"""
import hashlib
import json
import pytest


# ── Sample Catalog API response ──────────────────────────────────────────────

SAMPLE_CATALOG_RESPONSE = {
    "asin": "B09TEST001",
    "summaries": [
        {
            "marketplaceId": "A1F83G8C2ARO7P",
            "itemName": "Test Product Title - Premium Quality Widget",
            "brand": "OriginDesigned",
            "browseClassification": {
                "classificationId": "123456",
                "displayName": "Home & Garden > Widgets",
            },
            "listPrice": {
                "amount": "19.99",
                "currency": "GBP",
            },
            "brandRegistered": True,
        }
    ],
    "attributes": {
        "bullet_point": [
            {"value": "High quality materials for lasting durability"},
            {"value": "Easy to install with included hardware"},
            {"value": "Perfect size for home or office use"},
            {"value": "Available in multiple colours"},
            {"value": "30-day money back guarantee"},
        ],
        "product_description": [
            {"value": "This premium widget is designed for everyday use. Made from high-quality materials."}
        ],
    },
    "images": [
        {
            "marketplaceId": "A1F83G8C2ARO7P",
            "images": [
                {"variant": "MAIN", "link": "https://images.amazon.com/main.jpg", "width": 1000, "height": 1000},
                {"variant": "PT01", "link": "https://images.amazon.com/pt01.jpg", "width": 1000, "height": 1000},
                {"variant": "PT02", "link": "https://images.amazon.com/pt02.jpg", "width": 1000, "height": 1000},
            ],
        }
    ],
    "productTypes": [
        {"productType": "WIDGET"},
    ],
    "relationships": [
        {
            "marketplaceId": "A1F83G8C2ARO7P",
            "relationships": [
                {
                    "type": "VARIATION",
                    "parentAsins": [{"asin": "B09PARENT1"}],
                    "childAsins": [
                        {"asin": "B09TEST001"},
                        {"asin": "B09TEST002"},
                        {"asin": "B09TEST003"},
                    ],
                    "variationTheme": {"name": "COLOR", "attributes": ["color"]},
                },
            ],
        }
    ],
    "classifications": [
        {
            "marketplaceId": "A1F83G8C2ARO7P",
            "classificationId": "HOME_WIDGETS",
        }
    ],
}

SAMPLE_CATALOG_MINIMAL = {
    "asin": "B09EMPTY01",
    "summaries": [],
    "attributes": {},
    "images": [],
    "productTypes": [],
    "relationships": [],
    "classifications": [],
}


class TestCatalogParsing:
    """Test parse_catalog_item with various API responses."""

    def test_parse_full_response(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        result = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')

        assert result['asin'] == 'B09TEST001'
        assert result['marketplace'] == 'UK'
        assert result['region'] == 'EU'
        assert result['title'] == 'Test Product Title - Premium Quality Widget'
        assert result['bullet1'] == 'High quality materials for lasting durability'
        assert result['bullet2'] == 'Easy to install with included hardware'
        assert result['bullet5'] == '30-day money back guarantee'
        assert 'premium widget' in result['description'].lower()
        assert result['main_image_url'] == 'https://images.amazon.com/main.jpg'
        assert len(result['image_urls']) == 3
        assert result['image_count'] == 3
        assert result['brand'] == 'OriginDesigned'
        assert result['brand_registered'] is True
        assert result['parent_asin'] == 'B09PARENT1'
        assert result['variation_type'] == 'VARIATION'
        assert len(result['child_asins']) == 3
        assert result['product_type'] == 'WIDGET'
        assert result['list_price_amount'] == 19.99
        assert result['list_price_currency'] == 'GBP'
        assert result['content_hash']  # non-empty
        assert result['catalog_json'] == SAMPLE_CATALOG_RESPONSE

    def test_parse_minimal_response(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        result = parse_catalog_item(SAMPLE_CATALOG_MINIMAL, 'NA')

        assert result['asin'] == 'B09EMPTY01'
        assert result['marketplace'] == 'US'
        assert result['title'] == ''
        assert result['bullet1'] is None
        assert result['description'] == ''
        assert result['image_count'] == 0
        assert result['parent_asin'] is None
        assert result['product_type'] == ''

    def test_parse_na_region(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        response = {
            **SAMPLE_CATALOG_RESPONSE,
            "asin": "B09NA0001",
            "summaries": [{
                "marketplaceId": "ATVPDKIKX0DER",
                "itemName": "US Market Product",
                "brand": "TestBrand",
            }],
        }
        result = parse_catalog_item(response, 'NA')
        assert result['marketplace'] == 'US'
        assert result['title'] == 'US Market Product'

    def test_parse_fe_region(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        result = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'FE')
        assert result['marketplace'] == 'AU'


class TestContentHash:
    """Test content hash change detection."""

    def test_same_content_same_hash(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        result1 = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')
        result2 = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')
        assert result1['content_hash'] == result2['content_hash']

    def test_different_title_different_hash(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        modified = json.loads(json.dumps(SAMPLE_CATALOG_RESPONSE))
        modified['summaries'][0]['itemName'] = 'Completely Different Title'
        result1 = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')
        result2 = parse_catalog_item(modified, 'EU')
        assert result1['content_hash'] != result2['content_hash']

    def test_different_bullets_different_hash(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        modified = json.loads(json.dumps(SAMPLE_CATALOG_RESPONSE))
        modified['attributes']['bullet_point'][0]['value'] = 'Changed bullet point'
        result1 = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')
        result2 = parse_catalog_item(modified, 'EU')
        assert result1['content_hash'] != result2['content_hash']

    def test_hash_is_sha256(self):
        from core.amazon_intel.spapi.catalog import parse_catalog_item
        result = parse_catalog_item(SAMPLE_CATALOG_RESPONSE, 'EU')
        assert len(result['content_hash']) == 64  # SHA-256 hex digest


class TestBulletExtraction:
    """Test bullet point parsing from various attribute formats."""

    def test_standard_bullets(self):
        from core.amazon_intel.spapi.catalog import _extract_bullets
        attrs = {
            'bullet_point': [
                {'value': 'Bullet 1'},
                {'value': 'Bullet 2'},
                {'value': 'Bullet 3'},
            ]
        }
        bullets = _extract_bullets(attrs)
        assert len(bullets) == 3
        assert bullets[0] == 'Bullet 1'

    def test_max_five_bullets(self):
        from core.amazon_intel.spapi.catalog import _extract_bullets
        attrs = {
            'bullet_point': [{'value': f'Bullet {i}'} for i in range(8)]
        }
        bullets = _extract_bullets(attrs)
        assert len(bullets) == 5

    def test_empty_bullets(self):
        from core.amazon_intel.spapi.catalog import _extract_bullets
        assert _extract_bullets({}) == []
        assert _extract_bullets({'bullet_point': []}) == []

    def test_string_bullets(self):
        from core.amazon_intel.spapi.catalog import _extract_bullets
        attrs = {'bullet_point': ['Plain string bullet']}
        bullets = _extract_bullets(attrs)
        assert bullets == ['Plain string bullet']


class TestDescriptionExtraction:
    """Test product description parsing."""

    def test_standard_description(self):
        from core.amazon_intel.spapi.catalog import _extract_description
        attrs = {
            'product_description': [{'value': 'Product description text'}]
        }
        assert _extract_description(attrs) == 'Product description text'

    def test_empty_description(self):
        from core.amazon_intel.spapi.catalog import _extract_description
        assert _extract_description({}) == ''
        assert _extract_description({'product_description': []}) == ''

    def test_string_description(self):
        from core.amazon_intel.spapi.catalog import _extract_description
        attrs = {'product_description': 'Plain string description'}
        assert _extract_description(attrs) == 'Plain string description'


class TestVariationExtraction:
    """Test variation relationship parsing."""

    def test_variation_with_parent_and_children(self):
        from core.amazon_intel.spapi.catalog import _extract_variations
        rel_set = {
            'relationships': [
                {
                    'type': 'VARIATION',
                    'parentAsins': [{'asin': 'B09PARENT1'}],
                    'childAsins': [
                        {'asin': 'B09CHILD1'},
                        {'asin': 'B09CHILD2'},
                    ],
                    'variationTheme': {'name': 'SIZE'},
                }
            ]
        }
        result = _extract_variations(rel_set)
        assert result['parent_asin'] == 'B09PARENT1'
        assert result['variation_type'] == 'VARIATION'
        assert len(result['child_asins']) == 2

    def test_no_variations(self):
        from core.amazon_intel.spapi.catalog import _extract_variations
        assert _extract_variations({}) == {}
        assert _extract_variations(None) == {}
        assert _extract_variations({'relationships': []}) == {}


class TestEmbeddingTextBuilding:
    """Test the text building for embeddings."""

    def test_build_texts_full(self):
        from core.amazon_intel.spapi.embeddings import _build_texts
        row = {
            'title': 'Product Title',
            'bullet1': 'Feature 1',
            'bullet2': 'Feature 2',
            'bullet3': None,
            'bullet4': None,
            'bullet5': None,
            'description': 'Full description here.',
        }
        texts = _build_texts(row)
        assert 'title' in texts
        assert 'bullets' in texts
        assert 'description' in texts
        assert 'combined' in texts
        assert texts['title'] == 'Product Title'
        assert 'Feature 1\nFeature 2' == texts['bullets']
        assert 'Product Title' in texts['combined']
        assert 'Full description here.' in texts['combined']

    def test_build_texts_title_only(self):
        from core.amazon_intel.spapi.embeddings import _build_texts
        row = {
            'title': 'Just A Title',
            'bullet1': None, 'bullet2': None, 'bullet3': None,
            'bullet4': None, 'bullet5': None,
            'description': None,
        }
        texts = _build_texts(row)
        assert 'title' in texts
        assert 'bullets' not in texts
        assert 'description' not in texts
        assert 'combined' in texts

    def test_build_texts_empty(self):
        from core.amazon_intel.spapi.embeddings import _build_texts
        row = {
            'title': None,
            'bullet1': None, 'bullet2': None, 'bullet3': None,
            'bullet4': None, 'bullet5': None,
            'description': None,
        }
        texts = _build_texts(row)
        assert len(texts) == 0

    def test_text_hash_deterministic(self):
        from core.amazon_intel.spapi.embeddings import _text_hash
        h1 = _text_hash("same text")
        h2 = _text_hash("same text")
        assert h1 == h2

    def test_text_hash_different(self):
        from core.amazon_intel.spapi.embeddings import _text_hash
        h1 = _text_hash("text one")
        h2 = _text_hash("text two")
        assert h1 != h2


class TestMarketplaceFinder:
    """Test marketplace-specific entry finder."""

    def test_find_matching_marketplace(self):
        from core.amazon_intel.spapi.catalog import _find_for_marketplace
        items = [
            {'marketplaceId': 'ATVPDKIKX0DER', 'data': 'US'},
            {'marketplaceId': 'A1F83G8C2ARO7P', 'data': 'UK'},
        ]
        result = _find_for_marketplace(items, 'A1F83G8C2ARO7P')
        assert result['data'] == 'UK'

    def test_find_no_match(self):
        from core.amazon_intel.spapi.catalog import _find_for_marketplace
        items = [{'marketplaceId': 'ATVPDKIKX0DER'}]
        result = _find_for_marketplace(items, 'A1F83G8C2ARO7P')
        assert result is None

    def test_find_empty_list(self):
        from core.amazon_intel.spapi.catalog import _find_for_marketplace
        assert _find_for_marketplace([], 'A1F83G8C2ARO7P') is None
