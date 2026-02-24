# ebay-listing-automation

A production-grade Python framework for managing eBay listings at scale across multiple seller accounts. Built to automate listing creation, revision, and synchronization — including automatic description rebuilds when titles change, multi-account OAuth token management, and atomic data protection.

**This system actively manages 11,000+ SKUs across 3 eBay seller accounts.**

---

## 🎯 Problem

Managing thousands of eBay listings manually is unsustainable. Title changes require description updates. Price changes need to propagate across platforms. Photos need to stay synchronized. And all of this has to work reliably across multiple seller accounts without data loss.

Commercial tools like InkFrog handle some of this, but lack the flexibility for custom business logic — strategic pricing, visual search integration, and cross-platform sync with specific field-level control.

## ✅ Solution

A unified Python pipeline where **any field edit from any UI surface** flows through the same code path:

```
User edits title → editField() → /update_metadata_field → sync_item_to_ebay()
                                                              ↓
                                                    GetItem (fetch photos)
                                                              ↓
                                                    _build_revised_description()
                                                              ↓
                                                    ReviseItem (title + description + photos)
```

One pipeline. Every edit. Every modal. Every account.

---

## 🏗 Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Flask Application                     │
│                     (137 routes)                         │
├─────────────┬──────────────┬───────────────┬────────────┤
│  Listing    │  Sync        │  Pricing      │  Search    │
│  Builder    │  Engine      │  Engine       │  Engine    │
├─────────────┼──────────────┼───────────────┼────────────┤
│             │              │               │            │
│ AddFixed    │ ReviseItem   │ Black Swan    │ FAISS      │
│ PriceItem   │ GetItem      │ Margin Health │ OpenCV     │
│ Description │ Multi-Acct   │ Price Bake    │ Competitive│
│ Builder     │ Token Mgmt   │ Price Floor   │ Matching   │
├─────────────┴──────────────┴───────────────┴────────────┤
│                  Data Layer                              │
│  Atomic JSON writes │ Rotating backups │ Metadata index │
├─────────────────────────────────────────────────────────┤
│              External APIs                               │
│  eBay Trading API │ Shopify REST │ Firebase Realtime DB  │
└─────────────────────────────────────────────────────────┘
```

## ✨ Key Features

### Multi-Account eBay Management
- OAuth 2.0 token refresh with automatic expiry handling
- Account auto-detection: tries cached account first, falls back to scanning all accounts
- Rate limit detection (Error 518) stops retries across accounts sharing the same API quota

### Automatic Description Rebuild on Title Change
When a title is revised, the system:
1. Calls `GetItem` to fetch existing `PictureURL`s from eBay
2. Rebuilds the full HTML description with the new title, brand, MPN, condition, and hero images
3. Pushes `Title + Description + PictureDetails` in a single `ReviseItem` call

This ensures the listing description always matches the title — no manual updates needed.

### Listing Creation Pipeline
- `AddFixedPriceItem` with full business policy resolution (shipping, payment, return)
- Automatic shipping tier → package dimensions → policy mapping
- Psychological pricing: configurable price-point snapping with minimum floor enforcement
- Hero image HTML generation embedded in description
- UPS dimensional weight cap enforcement

### Atomic Data Protection
- All metadata writes use temp-file-then-rename pattern
- Rotating `.bak` / `.bak2` backups on every write
- Zero data loss incidents in production

### Batch Operations
- Background thread workers with pause/resume/stop controls
- Throttled API calls to respect eBay rate limits
- Per-item result tracking with comprehensive error capture

---

## 📁 Project Structure

```
ebay-listing-automation/
├── ebay_automation/
│   ├── __init__.py
│   ├── auth.py              # OAuth 2.0 token management, multi-account support
│   ├── trading_api.py       # eBay Trading API client (ReviseItem, GetItem, AddItem)
│   ├── description.py       # HTML description builder with hero images
│   ├── listing_builder.py   # Full listing creation pipeline
│   ├── sync_engine.py       # Field-level sync with account auto-detection
│   ├── atomic_io.py         # Atomic JSON read/write with rotating backups
│   └── rate_limiter.py      # Route-level rate limiting decorator
├── tests/
│   ├── test_description.py
│   ├── test_atomic_io.py
│   └── test_sync_engine.py
├── docs/
│   ├── api_flow.md          # Detailed API call sequences
│   └── field_sync_matrix.md # Which fields sync to which platforms
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## 🛠 Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ |
| Web Framework | Flask |
| eBay Integration | Trading API (XML/SOAP) via `requests` |
| Authentication | OAuth 2.0 with automatic token refresh |
| Data Storage | JSON metadata with atomic writes |
| Image Processing | OpenCV, base64 encoding |
| Background Jobs | `threading.Thread` with lock-protected state files |

---

## 🔧 Setup

### Prerequisites
- Python 3.10+
- eBay Developer Account with Trading API access
- OAuth credentials (App ID, Cert ID, Dev ID)

### Installation

```bash
git clone https://github.com/Rodstewart498/ebay-listing-automation.git
cd ebay-listing-automation
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your eBay credentials
```

### Configuration

```bash
# .env.example
EBAY_APP_ID=your_app_id
EBAY_CERT_ID=your_cert_id
EBAY_DEV_ID=your_dev_id
EBAY_REDIRECT_URI=your_redirect_uri
```

Each eBay account requires a JSON config file with refresh token:
```json
{
  "username": "YourSellerAccount",
  "refresh_token": "v^1.1#i^1#...",
  "access_token": "",
  "access_token_expiry": 0
}
```

---

## 📊 Field Sync Matrix

| Field | Local Metadata | eBay (Trading API) | Description Rebuild |
|-------|:-:|:-:|:-:|
| Title | ✅ | ✅ ReviseItem | ✅ Full rebuild |
| Price | ✅ | ✅ ReviseItem | — |
| SKU | ✅ | ✅ ReviseItem | — |
| MPN | ✅ | ✅ ReviseItem | — |
| Brand | ✅ | ✅ ReviseItem | — |
| Inventory | ✅ | ✅ ReviseItem | — |
| Weight | ✅ | ✅ ReviseItem | — |
| Shipping Policy | ✅ | ✅ ReviseItem | — |
| Photos | ✅ | ✅ ReviseItem | ✅ Re-embedded |

---

## 🧪 Example Usage

### Revise a listing title (triggers description rebuild)

```python
from ebay_automation.sync_engine import SyncEngine
from ebay_automation.auth import EbayAuthManager

auth = EbayAuthManager("./config/accounts", app_id, cert_id)
engine = SyncEngine(auth)

entry = {
    "ebay_item_id": "123456789012",
    "title": "Replacement Exhaust Manifold Assembly 2004-2008",
    "brand": "OEM",
    "mpn": "ABC-12345-00-00",
    "condition": "Used - Good",
    "quality_grade": "B"
}

result = engine.sync_field(
    entry=entry,
    field="title",
    new_value="Replacement Exhaust Manifold Header Pipe Assembly 2004-2008",
    old_value=entry["title"]
)

print(result)
# {'success': True, 'message': 'Synced (MySellerAccount)', 'account': 'MySellerAccount'}
```

### Create a new listing

```python
from ebay_automation.listing_builder import build_listing_xml

xml = build_listing_xml(
    title="Replacement Water Pump Assembly 2001-2002",
    price="89.95",
    brand="OEM",
    mpn="XYZ-98765",
    image_urls=["https://i.ebayimg.com/images/g/.../s-l1600.jpg"],
    fulfillment_policy_id="your_policy_id",
    payment_policy_id="your_payment_id",
    return_policy_id="your_return_id",
)
```

---

## ⚡ Performance

- **Token refresh**: < 1s with automatic caching until expiry
- **Single field revision**: 1-3s (API call + description rebuild)
- **Batch listing creation**: ~2s per item (throttled to respect rate limits)
- **Atomic JSON write**: < 50ms for 11K-entry metadata file

---

## 📝 License

© 2025 Rod Stewart. All Rights Reserved. This code is provided for portfolio demonstration purposes only. No permission is granted to use, copy, modify, or distribute this software.

---

## 🙋‍♂️ Author

**Rod Stewart** — [GitHub](https://github.com/Rodstewart498)

Built to solve real problems in high-volume ecommerce operations. If you're managing hundreds or thousands of eBay listings and drowning in manual work, this architecture might help.
