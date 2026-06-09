"""HTTP middleware."""

from app.middleware.proxy_path import ProxyPathPrefixMiddleware

__all__ = ["ProxyPathPrefixMiddleware"]
