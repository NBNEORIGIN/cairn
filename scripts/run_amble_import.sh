#!/usr/bin/env bash
# =============================================================================
# Amble Pin Cushion — end-to-end scrape + import orchestrator
# =============================================================================
#
# Step 1: Run scraper locally (saves to data/amble_pincushion_products.json)
# Step 2: SCP JSON to Hetzner server
# Step 3: Copy management command into running container
# Step 4: Run the Django import command inside the container
#
# Usage:
#   bash run_amble_import.sh                  # full run (all products)
#   bash run_amble_import.sh --max-pages 3   # test scrape (first 3 pages only)
#   bash run_amble_import.sh --dry-run        # scrape + dry-run import
#   bash run_amble_import.sh --limit 50       # scrape all, import first 50
#
# Prerequisites (local):
#   pip install requests beautifulsoup4 lxml
#
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
PHLOE_ROOT="/d/nbne_business/nbne_platform"

HETZNER_HOST="root@178.104.1.152"
CONTAINER="amble-pincushion-backend-1"
REMOTE_JSON="/tmp/amble_pincushion_products.json"
LOCAL_JSON="$REPO_ROOT/data/amble_pincushion_products.json"

# Parse args
MAX_PAGES=""
DRY_RUN=""
LIMIT=""
SKIP_SCRAPE=""
SKIP_IMAGES=""
TENANT="amble-pincushion"

while [[ $# -gt 0 ]]; do
    case $1 in
        --max-pages)   MAX_PAGES="--max-pages $2"; shift 2 ;;
        --dry-run)     DRY_RUN="--dry-run"; shift ;;
        --limit)       LIMIT="--limit $2"; shift 2 ;;
        --skip-scrape) SKIP_SCRAPE=1; shift ;;
        --skip-images) SKIP_IMAGES="--skip-images"; shift ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

# ── Step 1: Scrape ────────────────────────────────────────────────────────────
if [[ -z "$SKIP_SCRAPE" ]]; then
    echo ""
    echo "=== Step 1: Scraping amblepincushion.co.uk ==="
    python "$SCRIPT_DIR/scrape_amble_pincushion.py" \
        --out "$LOCAL_JSON" \
        $MAX_PAGES

    PRODUCT_COUNT=$(python -c "import json; d=json.load(open('$LOCAL_JSON')); print(len(d.get('products', [])))")
    echo "Products scraped: $PRODUCT_COUNT"
else
    echo "=== Step 1: Skipped (--skip-scrape) ==="
    PRODUCT_COUNT=$(python -c "import json; d=json.load(open('$LOCAL_JSON')); print(len(d.get('products', [])))" 2>/dev/null || echo "?")
    echo "Existing products in JSON: $PRODUCT_COUNT"
fi

# ── Step 2: Copy JSON to server ───────────────────────────────────────────────
echo ""
echo "=== Step 2: Uploading JSON to Hetzner ==="
scp "$LOCAL_JSON" "$HETZNER_HOST:$REMOTE_JSON"
echo "Uploaded to $HETZNER_HOST:$REMOTE_JSON"

# ── Step 3: Copy management command into container ───────────────────────────
echo ""
echo "=== Step 3: Syncing management command into container ==="
CMD_SRC="$PHLOE_ROOT/backend/shop/management/commands/import_woocommerce.py"
CMD_DEST="/app/shop/management/commands/import_woocommerce.py"

# Upload the .py to server first, then docker cp into container
scp "$CMD_SRC" "$HETZNER_HOST:/tmp/import_woocommerce.py"
ssh "$HETZNER_HOST" "docker cp /tmp/import_woocommerce.py $CONTAINER:$CMD_DEST"
echo "Management command installed in container"

# Copy JSON into container
ssh "$HETZNER_HOST" "docker cp $REMOTE_JSON $CONTAINER:/tmp/amble_pincushion_products.json"
echo "JSON copied into container"

# ── Step 4: Run import ────────────────────────────────────────────────────────
echo ""
echo "=== Step 4: Running Django import inside container ==="
ssh "$HETZNER_HOST" "docker exec $CONTAINER python manage.py import_woocommerce \
    --json /tmp/amble_pincushion_products.json \
    --tenant $TENANT \
    $DRY_RUN \
    $LIMIT \
    $SKIP_IMAGES"

echo ""
echo "=== Done ==="
