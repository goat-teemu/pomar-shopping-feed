---
name: google-shopping-feed
description: This skill should be used when the user wants to create, regenerate, update, or manage a Google Shopping product feed for a Shopify store. Triggers include mentions of shopping feed, product feed, Merchant Center feed, XML feed, Google Shopping, or regeneroi feedi.
---

# Google Shopping Feed - Shopify

## Overview
Generates a Google Merchant Center compatible XML feed from a Shopify store's public `products.json` endpoint. No API token required.

## Feed structure principles
- One item per product (not per variant) - sizes bundled
- Sizes: single `g:size` value as range (e.g. XS-XXL) - Google allows only one value
- Colors: max 3, separated by `/`
- `custom_label_0`: gender (female/male/unisex) - derived from product tags/type
- `custom_label_1`: price segment (outlet/sale/normal price)
- `item_group_id` not used - one item per product

## Key Google Shopping attributes
- `g:id` - product ID
- `g:title` - brand prefix + product title (e.g. "BRAND - Product Name")
- `g:description` - product description, keyword intro at the start (max 500 chars for search relevance)
- `g:link` - product URL
- `g:image_link` - main image
- `g:additional_image_link` - additional images
- `g:availability` - in stock / out of stock
- `g:price` - price with currency (e.g. 95.00 EUR)
- `g:brand` - brand name
- `g:condition` - new
- `g:google_product_category` - mapped from product_type
- `g:gender` - female/male/unisex
- `g:size` - size range (XS-XXL)
- `g:color` - up to 3 colors with / separator
- `g:custom_label_0` - gender
- `g:custom_label_1` - price segment

## Generating the feed

```bash
python3 generate_feed.py
```

After generating, report:
- Total products included
- Breakdown by custom_label_1 (outlet/sale/normal price)
- Breakdown by gender

## Hosting
Feed needs a public URL for Google Merchant Center to fetch. Options:
- **Shopify Files** (recommended): Admin → Content → Files → upload XML → get CDN URL
- Requires manual re-upload when feed is regenerated (or API automation)

## Common tasks

**"Luo feedi"** → write generate_feed.py for the store, run it, report stats
**"Regeneroi feedi"** → run existing script, report stats, remind about upload
**"Lisää kenttiä feediin"** → edit generate_feed.py
**"Miksi tuote X ei näy"** → check products.json for that product
