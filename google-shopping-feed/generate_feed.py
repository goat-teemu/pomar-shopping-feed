#!/usr/bin/env python3
"""
Google Shopping Feed Generator – pomar.fi
Generates a Google Merchant Center compatible XML feed from Shopify products.json.
No API token required.

Usage:
    python3 generate_feed.py

Output:
    pomar_google_shopping_feed.xml
"""

import json
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from xml.dom import minidom

import gspread
from google.oauth2.service_account import Credentials

# ── Config ─────────────────────────────────────────────────────────────────────

G = "http://base.google.com/ns/1.0"
SPREADSHEET_ID = "1n5R9_Ae_T-9GuzuoTbymT7FgomrpM75Q_SWHCDYP51Q"
CREDENTIALS_FILE = os.path.join(os.path.dirname(__file__), "google-credentials.json")

MARKETS = [
    {
        "store_url": "https://pomar.fi",
        "sheet_tab": "FI",
        "spreadsheet_id": "1n5R9_Ae_T-9GuzuoTbymT7FgomrpM75Q_SWHCDYP51Q",
        "currency": "EUR",
        "output_file": "pomar_google_shopping_feed_fi.xml",
    },
    {
        "store_url": "https://www.pomarshoes.com",
        "sheet_tab": "EN",
        "spreadsheet_id": "1WG2tKwc34l3LimrYf343L3o4L4rKKk-ZAKl7C69L-Rk",
        "currency": "EUR",
        "output_file": "pomar_google_shopping_feed_en.xml",
    },
    {
        "store_url": "https://www.pomarshoes.de",
        "sheet_tab": "DE",
        "spreadsheet_id": "1fPj8CnTInnwvTT2BmDIuUJJqTQbM__FlHY_q_RpcfMA",
        "currency": "EUR",
        "output_file": "pomar_google_shopping_feed_de.xml",
    },
]

# Backwards compat — used by fetch_all_products and build_feed
STORE_URL = MARKETS[0]["store_url"]
OUTPUT_FILE = MARKETS[0]["output_file"]

# Map Finnish product types → Google taxonomy
CATEGORY_MAP = [
    ("nilkkuri",  "Apparel & Accessories > Shoes > Boots > Ankle Boots"),
    ("saapas",    "Apparel & Accessories > Shoes > Boots"),
    ("puolikenk", "Apparel & Accessories > Shoes"),
    ("kenk",      "Apparel & Accessories > Shoes"),
]

# ── Helpers ────────────────────────────────────────────────────────────────────

def fetch_all_products() -> list:
    products = []
    page = 1
    while True:
        url = f"{STORE_URL}/products.json?limit=250&page={page}"
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read().decode())
        batch = data.get("products", [])
        if not batch:
            break
        products.extend(batch)
        if len(batch) < 250:
            break
        page += 1
    return products


def strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", text).strip()


def parse_tags(raw) -> list:
    if isinstance(raw, list):
        return [t.strip() for t in raw]
    return [t.strip() for t in (raw or "").split(",")]


def get_gender(tags: list, product_type: str) -> str:
    tags_lower = [t.lower() for t in tags]
    pt_lower = product_type.lower()
    if "hidden:naiset" in tags_lower or "naisten" in pt_lower:
        return "female"
    if "hidden:miehet" in tags_lower or "miesten" in pt_lower:
        return "male"
    return "unisex"


def get_colors(tags: list) -> list:
    colors = []
    for tag in tags:
        if tag.startswith("Pääväri:"):
            colors.append(tag.split(":", 1)[1].strip())
    return colors[:3]


def get_price_segment(tags: list, price: float, compare_at) -> str:
    tags_lower = [t.lower() for t in tags]
    if any("outlet" in t for t in tags_lower):
        return "outlet"
    if compare_at and compare_at > price:
        return "sale"
    return "normal price"


def get_size_range(variants: list):
    sizes = []
    for v in variants:
        # option2 = size for most products; option1 if there is no option2
        size = v.get("option2") or v.get("option1")
        if size and size not in ("Default Title",):
            sizes.append(size)
    if not sizes:
        return None
    unique = list(dict.fromkeys(sizes))  # preserve order
    try:
        sorted_sizes = sorted(set(unique), key=lambda x: float(x.replace(",", ".")))
    except ValueError:
        sorted_sizes = sorted(set(unique))
    if len(sorted_sizes) == 1:
        return sorted_sizes[0]
    return f"{sorted_sizes[0]}-{sorted_sizes[-1]}"


def get_availability(variants: list) -> str:
    return "in stock" if any(v.get("available") for v in variants) else "out of stock"


def get_min_price(variants: list):
    prices = [float(v["price"]) for v in variants if v.get("price")]
    return min(prices) if prices else None


def get_max_compare_at(variants: list):
    prices = [
        float(v["compare_at_price"])
        for v in variants
        if v.get("compare_at_price") and float(v["compare_at_price"]) > 0
    ]
    return max(prices) if prices else None


def get_google_category(product_type: str) -> str:
    pt_lower = product_type.lower()
    for key, category in CATEGORY_MAP:
        if key in pt_lower:
            return category
    return "Apparel & Accessories > Shoes"


# ── Feed builder ───────────────────────────────────────────────────────────────

def build_feed(products: list) -> tuple[ET.ElementTree, dict]:
    ET.register_namespace("g", G)
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = "Pomar"
    ET.SubElement(channel, "link").text = STORE_URL
    ET.SubElement(channel, "description").text = "Pomar Google Shopping Feed"

    stats: dict = {
        "total": 0,
        "outlet": 0, "sale": 0, "normal price": 0,
        "female": 0, "male": 0, "unisex": 0,
    }

    def g_el(parent, tag: str, text: str) -> None:
        """Add a g-namespaced element with text."""
        if text is None:
            return
        ET.SubElement(parent, f"{{{G}}}{tag}").text = text

    for product in products:
        variants = product.get("variants", [])
        tags = parse_tags(product.get("tags", []))

        price = get_min_price(variants)
        if price is None:
            continue  # skip products without price

        compare_at = get_max_compare_at(variants)
        gender = get_gender(tags, product.get("product_type", ""))
        price_segment = get_price_segment(tags, price, compare_at)
        colors = get_colors(tags)
        size_range = get_size_range(variants)
        availability = get_availability(variants)
        images = product.get("images", [])
        brand = product.get("vendor", "Pomar")

        stats["total"] += 1
        stats[price_segment] = stats.get(price_segment, 0) + 1
        stats[gender] = stats.get(gender, 0) + 1

        item = ET.SubElement(channel, "item")

        # ── Required ──────────────────────────────────────────────────────────
        g_el(item, "id", str(product["id"]))
        g_el(item, "title", f"Pomar {product['title']}")

        desc = strip_html(product.get("body_html", ""))
        if len(desc) > 500:
            desc = desc[:497] + "..."
        g_el(item, "description", desc or product["title"])

        g_el(item, "link", f"{STORE_URL}/products/{product['handle']}")

        if images:
            g_el(item, "image_link", images[0]["src"])
            for img in images[1:5]:  # up to 4 additional images
                g_el(item, "additional_image_link", img["src"])

        g_el(item, "availability", availability)
        g_el(item, "condition", "new")
        g_el(item, "brand", brand)

        # ── Price ─────────────────────────────────────────────────────────────
        # When on sale: g:price = original, g:sale_price = discounted
        if compare_at and compare_at > price:
            g_el(item, "price", f"{compare_at:.2f} EUR")
            g_el(item, "sale_price", f"{price:.2f} EUR")
        else:
            g_el(item, "price", f"{price:.2f} EUR")

        # ── Category & attributes ─────────────────────────────────────────────
        g_el(item, "google_product_category", get_google_category(product.get("product_type", "")))
        g_el(item, "gender", gender)

        if size_range:
            g_el(item, "size", size_range)

        if colors:
            g_el(item, "color", "/".join(colors))

        # ── Custom labels ─────────────────────────────────────────────────────
        g_el(item, "custom_label_0", gender)
        g_el(item, "custom_label_1", price_segment)

    return ET.ElementTree(rss), stats


def get_sheets_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        import json as _json
        creds = Credentials.from_service_account_info(_json.loads(creds_json), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    return gspread.authorize(creds)


def push_to_sheets(products: list, store_url: str, sheet_tab: str, currency: str, spreadsheet_id: str) -> None:
    print(f"Pushataan Google Sheetsiin ({sheet_tab})...")

    client = get_sheets_client()
    spreadsheet = client.open_by_key(spreadsheet_id)

    try:
        sheet = spreadsheet.worksheet(sheet_tab)
    except gspread.exceptions.WorksheetNotFound:
        sheet = spreadsheet.add_worksheet(title=sheet_tab, rows=2000, cols=20)

    headers = [
        "id", "title", "description", "link", "image_link",
        "additional_image_link", "availability", "price", "sale_price",
        "brand", "condition", "google_product_category",
        "gender", "age_group", "size", "color", "custom_label_0", "custom_label_1",
    ]

    rows = [headers]

    for product in products:
        variants = product.get("variants", [])
        tags = parse_tags(product.get("tags", []))

        price = get_min_price(variants)
        if price is None:
            continue

        compare_at = get_max_compare_at(variants)
        gender = get_gender(tags, product.get("product_type", ""))
        price_segment = get_price_segment(tags, price, compare_at)
        colors = get_colors(tags)
        size_range = get_size_range(variants)
        availability = get_availability(variants)
        images = product.get("images", [])
        brand = product.get("vendor", "Pomar")

        desc = strip_html(product.get("body_html", ""))
        if len(desc) > 500:
            desc = desc[:497] + "..."

        additional_imgs = ",".join(img["src"] for img in images[1:5])

        if compare_at and compare_at > price:
            price_str = f"{compare_at:.2f} {currency}"
            sale_price_str = f"{price:.2f} {currency}"
        else:
            price_str = f"{price:.2f} {currency}"
            sale_price_str = ""

        rows.append([
            str(product["id"]),
            f"Pomar {product['title']}",
            desc or product["title"],
            f"{store_url}/products/{product['handle']}",
            images[0]["src"] if images else "",
            additional_imgs,
            availability,
            price_str,
            sale_price_str,
            brand,
            "new",
            get_google_category(product.get("product_type", "")),
            gender,
            "adult",
            size_range or "",
            "/".join(colors) if colors else "",
            gender,
            price_segment,
        ])

    sheet.clear()
    sheet.update(rows)
    print(f"Google Sheets päivitetty ({sheet_tab}): {len(rows) - 1} tuotetta")


def prettify(tree: ET.ElementTree) -> bytes:
    rough = ET.tostring(tree.getroot(), encoding="unicode")
    return minidom.parseString(rough).toprettyxml(indent="  ", encoding="UTF-8")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    for market in MARKETS:
        store_url = market["store_url"]
        sheet_tab = market["sheet_tab"]
        currency = market["currency"]
        output_file = market["output_file"]

        print(f"\n{'='*50}")
        print(f"Markkina: {sheet_tab} ({store_url})")
        print(f"{'='*50}")

        # Patch global so fetch_all_products and build_feed use right URL
        global STORE_URL, OUTPUT_FILE
        STORE_URL = store_url
        OUTPUT_FILE = output_file

        print(f"Fetching products from {store_url}…")
        products = fetch_all_products()
        print(f"Found {len(products)} products\n")

        tree, stats = build_feed(products)

        with open(output_file, "wb") as fh:
            fh.write(prettify(tree))

        print(f"Feed written to: {output_file}")
        print(f"Total items:     {stats['total']}")

        push_to_sheets(products, store_url, sheet_tab, currency, market["spreadsheet_id"])


if __name__ == "__main__":
    main()
