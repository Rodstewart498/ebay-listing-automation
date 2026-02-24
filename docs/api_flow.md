# API Call Flow

Detailed sequence for each major operation.

## Single Field Revision (Non-Title)

```
Client → POST /update_metadata_field
    ├── Update local metadata entry
    ├── SyncEngine.sync_field(entry, field, new_value, old_value)
    │   ├── _resolve_account_token(entry)
    │   │   ├── Try entry['ebay_account'] → auth.get_token()
    │   │   └── Fallback: scan all accounts
    │   └── _sync_simple_field(item_id, token, **field_kwargs)
    │       └── revise_item(item_id, token, price=new_value)
    │           ├── Build ReviseItem XML (only changed field)
    │           ├── POST api.ebay.com/ws/api.dll
    │           └── Parse response → check Ack
    └── Return {success, message, account}
```

## Title Change (With Description Rebuild)

```
Client → POST /update_metadata_field { field: "title" }
    ├── Update local metadata entry
    ├── SyncEngine.sync_field(entry, "title", new_title, old_title)
    │   ├── _resolve_account_token(entry)
    │   └── _sync_title(entry, item_id, new_title, token)
    │       ├── GetItem(item_id) → extract PictureURLs
    │       ├── build_description(new_title, brand, mpn, condition, photos)
    │       └── ReviseItem(item_id, Title + Description + PictureDetails)
    └── Return {success, message, account}
```

## New Listing Creation

```
Client → POST /create_listing
    ├── Resolve business policies (shipping, payment, return)
    ├── get_package_specs(shipping_tier)
    │   └── _enforce_dim_weight_cap(specs)
    ├── snap_to_psychological_price(raw_price)
    ├── build_description(title, brand, mpn, condition, photos)
    ├── build_listing_xml(all_params)
    │   └── Construct AddFixedPriceItem XML
    ├── POST api.ebay.com/ws/api.dll
    ├── Parse response → extract new ItemID
    └── Return {success, item_id}
```

## Token Refresh Flow

```
EbayAuthManager.get_token(account_name)
    ├── Check cached token → is_token_valid?
    │   ├── Yes → return cached access_token
    │   └── No → _refresh_token(account)
    │       ├── Build Basic auth: base64(app_id:cert_id)
    │       ├── POST api.ebay.com/identity/v1/oauth2/token
    │       │   └── grant_type=refresh_token
    │       ├── Cache new token + expiry timestamp
    │       └── Return access_token
    └── On failure → return None
```

## Error Handling

| Error | Code | Response |
|-------|------|----------|
| Rate Limited | 518 | Stop retrying all accounts (shared quota) |
| Invalid Token | 21917 | Trigger token refresh, retry once |
| Item Not Found | 17 | Return failure, log warning |
| Request Timeout | — | Return failure after 30s timeout |
