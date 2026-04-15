"""
Amble Pin Cushion — WooCommerce shop scraper
============================================

Scrapes https://amblepincushion.co.uk/shop/ and saves product data to a JSON
checkpoint file.  Designed to be resumable: already-scraped product URLs are
skipped on re-run.

Usage:
    python scrape_amble_pincushion.py
    python scrape_amble_pincushion.py --max-pages 5       # limit for testing
    python scrape_amble_pincushion.py --out my_data.json

Output: data/amble_pincushion_products.json  (configurable with --out)

Each product record:
{
    "url": "https://amblepincushion.co.uk/shop/...",
    "name": "...",
    "slug": "...",
    "price": "4.99",
    "compare_at_price": null,
    "categories": ["Fabric", "Cotton"],
    "short_description": "...",
    "images": ["https://...jpg", ...]
}
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://amblepincushion.co.uk"
SHOP_URL = f"{BASE_URL}/shop/"
PAGE_DELAY = 0.5    # seconds between listing page requests
PRODUCT_DELAY = 0.4  # seconds between product page requests
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36 Phloe-Import/1.0"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-GB,en;q=0.9",
}

DEFAULT_OUT = Path(__file__).parent.parent / "data" / "amble_pincushion_products.json"


def get_page(url: str, session: requests.Session) -> BeautifulSoup | None:
    try:
        r = session.get(url, headers=HEADERS, timeout=30)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except requests.RequestException as e:
        print(f"  [WARN] GET failed: {url} — {e}", file=sys.stderr)
        return None


def parse_price(text: str) -> str | None:
    """Extract first decimal price from text like £4.99 or £4.99–£9.99."""
    if not text:
        return None
    m = re.search(r"[\d,]+\.\d{2}", text.replace(",", ""))
    if m:
        return m.group(0).replace(",", "")
    return None


def scrape_product_page(url: str, session: requests.Session) -> dict | None:
    soup = get_page(url, session)
    if not soup:
        return None

    # ---------- name ----------
    h1 = soup.find("h1", class_=lambda c: c and "product_title" in (c if isinstance(c, str) else " ".join(c)))
    name = h1.get_text(strip=True) if h1 else None
    if not name:
        return None

    # ---------- slug ----------
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]

    # ---------- price ----------
    price_str = None
    compare_str = None
    price_block = soup.find("p", class_="price")
    if price_block:
        ins = price_block.find("ins")
        dels = price_block.find("del")
        if ins:
            price_str = parse_price(ins.get_text())
            compare_str = parse_price(dels.get_text()) if dels else None
        else:
            price_str = parse_price(price_block.get_text())

    # ---------- categories ----------
    categories = []
    cat_block = soup.find("span", class_="posted_in")
    if cat_block:
        for a in cat_block.find_all("a"):
            cat_text = a.get_text(strip=True)
            if cat_text:
                categories.append(cat_text)

    # ---------- short description ----------
    short_desc = ""
    # Theme-dependent: try both the standard div and a summary paragraph
    sd_div = (
        soup.find("div", class_="woocommerce-product-details__short-description")
        or soup.find("div", class_=lambda c: c and "short-description" in (c if isinstance(c, str) else " ".join(c)))
    )
    if sd_div:
        short_desc = sd_div.get_text(" ", strip=True)[:500]
    # Fallback: meta description
    if not short_desc:
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            short_desc = meta["content"].strip()[:500]

    # ---------- images ----------
    images = []
    gallery = soup.find("div", class_=lambda c: c and "woocommerce-product-gallery" in (c if isinstance(c, str) else " ".join(c)))
    if gallery:
        for img in gallery.find_all("img"):
            src = (
                img.get("data-large_image")
                or img.get("data-src")
                or img.get("src")
                or ""
            ).strip()
            if src and src not in images and "placeholder" not in src:
                # Strip WooCommerce size suffix e.g. -300x300.jpg → .jpg
                src = re.sub(r"-\d+x\d+(\.[a-zA-Z]+)$", r"\1", src)
                images.append(src)

    # Fallback: og:image
    if not images:
        og = soup.find("meta", property="og:image")
        if og and og.get("content"):
            images.append(og["content"])

    return {
        "url": url,
        "name": name,
        "slug": slug,
        "price": price_str or "0.00",
        "compare_at_price": compare_str,
        "categories": categories,
        "short_description": short_desc,
        "images": images,
    }


def scrape_listing_page(page_num: int, session: requests.Session) -> tuple[list[str], bool]:
    """
    Scrape one shop listing page.
    Returns (product_urls, has_next_page).
    """
    url = SHOP_URL if page_num == 1 else f"{BASE_URL}/shop/page/{page_num}/"

    soup = get_page(url, session)
    if not soup:
        return [], False

    # This theme uses div.product-small items (not standard ul.products li.product)
    urls = []
    seen = set()
    for item in soup.find_all("div", class_="product-small"):
        # First link inside each product card is the product URL
        a = item.find("a", href=True)
        if a:
            href = a["href"].strip()
            if href and href not in seen:
                seen.add(href)
                urls.append(href)

    # Check for next page — theme uses <a class="next page-number">
    nav = soup.find("nav", class_=lambda c: c and "pagination" in (c if isinstance(c, str) else " ".join(c)))
    has_next = False
    if nav:
        next_a = nav.find("a", class_=lambda c: c and "next" in (c if isinstance(c, str) else " ".join(c)))
        has_next = next_a is not None

    return urls, has_next


def load_checkpoint(path: Path) -> dict:
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
                print(f"Loaded checkpoint: {len(data.get('products', []))} products already scraped")
                return data
        except (json.JSONDecodeError, KeyError):
            pass
    return {"products": [], "scraped_urls": []}


def save_checkpoint(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def main():
    parser = argparse.ArgumentParser(description="Scrape Amble Pin Cushion WooCommerce shop")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON file path")
    parser.add_argument("--max-pages", type=int, default=0, help="Limit listing pages (0 = all)")
    parser.add_argument("--max-products", type=int, default=0, help="Limit products scraped (0 = all)")
    args = parser.parse_args()

    out_path = Path(args.out)
    data = load_checkpoint(out_path)
    scraped_urls = set(data["scraped_urls"])
    products = data["products"]

    session = requests.Session()

    print(f"Starting scrape of {SHOP_URL}")

    # ── Phase 1: collect all product URLs ────────────────────────────────────
    print("\n--- Phase 1: collecting product URLs from listing pages ---")
    all_product_urls: list[str] = []
    seen_listing_urls: set[str] = set()
    page = 1

    while True:
        if args.max_pages and page > args.max_pages:
            print(f"Reached --max-pages {args.max_pages}, stopping listing scrape")
            break

        print(f"  Listing page {page}...", end=" ", flush=True)
        page_urls, has_next = scrape_listing_page(page, session)

        new_urls = [u for u in page_urls if u not in seen_listing_urls]
        seen_listing_urls.update(new_urls)
        all_product_urls.extend(new_urls)
        print(f"{len(new_urls)} products (total: {len(all_product_urls)})")

        if not has_next:
            print(f"  No next page — listing complete at page {page}")
            break

        page += 1
        time.sleep(PAGE_DELAY)

    print(f"\nTotal product URLs collected: {len(all_product_urls)}")
    already = sum(1 for u in all_product_urls if u in scraped_urls)
    print(f"Already scraped: {already}  |  To scrape: {len(all_product_urls) - already}")

    # ── Phase 2: scrape product detail pages ─────────────────────────────────
    print("\n--- Phase 2: scraping product detail pages ---")
    new_count = 0
    fail_count = 0

    for i, url in enumerate(all_product_urls, 1):
        if args.max_products and new_count >= args.max_products:
            print(f"Reached --max-products {args.max_products}, stopping")
            break

        if url in scraped_urls:
            continue

        short_slug = url.rstrip("/").split("/")[-1]
        print(f"  [{i}/{len(all_product_urls)}] {short_slug[:55]}", end=" ... ", flush=True)

        product = scrape_product_page(url, session)
        if product:
            products.append(product)
            scraped_urls.add(url)
            data["products"] = products
            data["scraped_urls"] = list(scraped_urls)
            new_count += 1
            cat = product["categories"][0] if product["categories"] else "—"
            print(f"OK  £{product['price']}  cat={cat[:20]}  imgs={len(product['images'])}")
        else:
            fail_count += 1
            print("FAIL")

        # Checkpoint every 25 new products
        if new_count % 25 == 0 and new_count > 0:
            save_checkpoint(out_path, data)
            print(f"  [checkpoint — {len(products)} total saved]")

        time.sleep(PRODUCT_DELAY)

    save_checkpoint(out_path, data)
    print(f"\nDone. New: {new_count} | Failed: {fail_count} | Total in file: {len(products)}")
    print(f"Output: {out_path}")


if __name__ == "__main__":
    main()
