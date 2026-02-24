# Field Sync Matrix

How each editable field propagates across platforms when changed through the app.

## Sync Behavior by Field

| Field | Local Metadata | eBay (Trading API) | Shopify (REST API) | Description Rebuild | Notes |
|-------|:-:|:-:|:-:|:-:|-------|
| **Title** | ✅ Immediate | ✅ ReviseItem | ✅ Product update | ✅ Full rebuild | Triggers GetItem → rebuild → ReviseItem pipeline |
| **Price** | ✅ Immediate | ✅ ReviseItem | ✅ Variant update | — | Also syncs `ebay_last_price`, `variant_price` |
| **SKU** | ✅ Immediate | ✅ ReviseItem | ✅ Variant update | — | Custom label field |
| **MPN** | ✅ Immediate | ✅ Item Specifics | ⚠️ Skipped | — | Shopify would need metafields (not implemented) |
| **Brand** | ✅ Immediate | ✅ Item Specifics | ⚠️ Skipped | — | Same metafields limitation |
| **Inventory** | ✅ Immediate | ✅ ReviseItem | ✅ Inventory Levels API | — | Uses separate Shopify endpoint |
| **Weight** | ✅ Immediate | ✅ ReviseItem | — | — | Updates ShippingPackageDetails |
| **Shipping Tier** | ✅ Immediate | ✅ ReviseItem | — | — | Maps tier → policy → dimensions |
| **Status** | ✅ Immediate | ✅ EndItem (if archived) | ✅ Published flag | — | Active/archived/draft |
| **Photos** | ✅ Immediate | ✅ ReviseItem | — | ✅ Re-embedded | PictureDetails + description hero images |

## Title Change Pipeline (Detailed)

```
1. User clicks title in any UI surface → window.editField()
2. Edit dialog shown → user types new title → clicks Save
3. POST /update_metadata_field { field: "title", value: "New Title" }
4. Server updates local metadata entry
5. Calls sync_item_to_ebay(entry, "title", new_value, old_value)
6.   → Detects title change → enters special pipeline:
7.     a. GetItem(item_id) → extracts existing PictureURL list
8.     b. _build_revised_description(new_title, brand, mpn, ..., photos)
9.     c. ReviseItem(item_id, Title + Description + PictureDetails)
10. Calls sync_item_to_shopify(entry, "title", new_value, old_value)
11.   → Updates product title on Shopify
12. Returns success response to client
```

## Account Resolution

When syncing to eBay, the system determines which account to use:

1. **Stored account** — Check `entry['ebay_account']` field
2. **Fallback scan** — Try all configured accounts if stored account fails
3. **Rate limit detection** — If Error 518, stop retrying (shared API quota)

## Bulk Operations

| Operation | eBay Sync | Mechanism |
|-----------|:-:|---------|
| Price Floor | Via CSV | Updated locally, pushed via File Exchange CSV |
| Price Bake | Via CSV | Same CSV workflow for bulk efficiency |
| Bulk SKU Assignment | Optional | `/bulk_update_metadata` (local only) or per-item `/update_metadata_field` |
| Batch Listing Create | ✅ Direct | Background thread with throttled AddFixedPriceItem calls |
| Snapshot Push | ✅ Direct | Background thread with AddFixedPriceItem + policy resolution |
