"""
ebay_automation — Production eBay listing management framework.

Multi-account listing creation, revision, and synchronization with
automatic description rebuilds, OAuth token management, and atomic
data protection.

Modules:
    auth             Multi-account OAuth 2.0 token management
    trading_api      eBay Trading API client (ReviseItem, GetItem, AddItem)
    description      HTML description builder with hero images
    listing_builder  Full listing creation pipeline
    sync_engine      Field-level sync with account auto-detection
    atomic_io        Atomic JSON read/write with rotating backups
    rate_limiter     Route-level rate limiting decorator
"""

__version__ = "1.0.0"
