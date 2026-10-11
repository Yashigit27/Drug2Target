"""
Shared httpx client factory with reliable TLS on Windows / corporate networks.

On many Windows + Anaconda setups the default Python CA bundle fails with
``CERTIFICATE_VERIFY_FAILED``. ``truststore`` injects the OS certificate store
so HTTPS works without disabling verification.
"""

from __future__ import annotations

import os
import warnings

import httpx

_truststore_applied = False


def _ensure_truststore() -> None:
    global _truststore_applied
    if _truststore_applied:
        return
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        pass
    finally:
        _truststore_applied = True


def ssl_verify_setting() -> str | bool:
    """Resolve verify= for httpx from env (optional overrides)."""
    _ensure_truststore()
    if (os.environ.get("HTTPX_SSL_VERIFY") or "").lower() in ("0", "false", "no"):
        warnings.warn(
            "HTTPX_SSL_VERIFY is disabled; TLS certificate verification is off.",
            stacklevel=2,
        )
        return False
    if path := os.environ.get("SSL_CERT_FILE") or os.environ.get("REQUESTS_CA_BUNDLE"):
        return path
    return True


def make_http_client(**kwargs) -> httpx.Client:
    """Create an httpx.Client with project TLS defaults."""
    _ensure_truststore()
    kwargs.setdefault("verify", ssl_verify_setting())
    return httpx.Client(**kwargs)
