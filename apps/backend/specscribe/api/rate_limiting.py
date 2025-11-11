import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class RateLimiter:
    """Simple in-memory rate limiter."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.requests: dict[str, deque] = defaultdict(deque)

    def is_allowed(self, identifier: str) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed, reset_time)."""
        now = time.time()
        window_start = now - self.window_seconds

        # Clean old requests
        request_times = self.requests[identifier]
        while request_times and request_times[0] < window_start:
            request_times.popleft()

        # Check if under limit
        if len(request_times) < self.max_requests:
            request_times.append(now)
            return True, int(now + self.window_seconds)
        else:
            # Return when the oldest request will expire
            return False, int(request_times[0] + self.window_seconds)

    def cleanup_expired(self):
        """Clean up expired entries."""
        now = time.time()
        window_start = now - self.window_seconds

        for identifier in list(self.requests.keys()):
            request_times = self.requests[identifier]
            while request_times and request_times[0] < window_start:
                request_times.popleft()

            if not request_times:
                del self.requests[identifier]


class RateLimitMiddleware:
    """Rate limiting middleware for specific endpoints."""

    def __init__(self, oauth_rate_limiter: RateLimiter, refresh_rate_limiter: RateLimiter | None = None):
        self.oauth_rate_limiter = oauth_rate_limiter
        self.refresh_rate_limiter = refresh_rate_limiter or refresh_token_rate_limiter
        self.trusted_proxies = self._get_trusted_proxies()

    def _get_trusted_proxies(self) -> set[str]:
        """Get list of trusted proxy IPs from environment."""
        trusted_proxies_env = os.getenv("TRUSTED_PROXIES", "")
        if not trusted_proxies_env:
            return set()
        return {ip.strip() for ip in trusted_proxies_env.split(",") if ip.strip()}

    def get_client_identifier(self, request: Request) -> str:
        """Get client identifier for rate limiting with proxy spoofing protection."""
        # Only use X-Forwarded-For if request comes from trusted proxy
        if self.trusted_proxies and hasattr(request.client, "host"):
            client_host = request.client.host if request.client else "unknown"  # type: ignore[union-attr]
            if client_host in self.trusted_proxies:
                forwarded_for = request.headers.get("X-Forwarded-For")
                if forwarded_for:
                    # Take the first IP in the chain and validate format
                    client_ip = forwarded_for.split(",")[0].strip()
                    if self._is_valid_ip(client_ip):
                        return client_ip

        # Fallback to direct client IP
        return getattr(request.client, "host", "unknown")

    def _is_valid_ip(self, ip: str) -> bool:
        """Basic IP format validation."""
        parts = ip.split(".")
        if len(parts) != 4:
            return False
        try:
            return all(0 <= int(part) <= 255 for part in parts)
        except ValueError:
            return False

    def check_oauth_rate_limit(self, request: Request):
        """Check rate limit for OAuth endpoints."""
        path = str(request.url.path)
        if not (path.startswith("/api/v1/auth/login/") or path.startswith("/api/v1/auth/callback/")):
            return

        identifier = self.get_client_identifier(request)
        allowed, reset_time = self.oauth_rate_limiter.is_allowed(identifier)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "Too many OAuth requests. Please try again later.",
                    "details": [{"type": "rate_limit", "message": f"Rate limit reset at {reset_time}"}],
                    "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                },
                headers={"Retry-After": str(reset_time - int(time.time()))},
            )

    def check_refresh_token_rate_limit(self, request: Request):
        """Check rate limit for token refresh endpoint."""
        identifier = self.get_client_identifier(request)
        allowed, reset_time = self.refresh_rate_limiter.is_allowed(identifier)

        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "rate_limit_exceeded",
                    "message": "Too many token refresh requests. Please try again later.",
                    "details": [{"type": "rate_limit", "message": f"Rate limit reset at {reset_time}"}],
                    "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
                },
                headers={"Retry-After": str(reset_time - int(time.time()))},
            )


# Rate limiting configuration
# OAuth endpoints: 5 requests per minute per IP
# - Protects against OAuth abuse and brute force attacks
# - Allows legitimate retries while preventing excessive requests
OAUTH_MAX_REQUESTS = int(os.getenv("OAUTH_RATE_LIMIT_MAX_REQUESTS", "5"))
OAUTH_WINDOW_SECONDS = int(os.getenv("OAUTH_RATE_LIMIT_WINDOW_SECONDS", "60"))

# Refresh token endpoint: 10 requests per hour per IP
# - Prevents token refresh abuse
# - Higher limit than OAuth since legitimate apps refresh tokens periodically
# - 1 hour window provides good balance between security and usability
REFRESH_MAX_REQUESTS = int(os.getenv("REFRESH_RATE_LIMIT_MAX_REQUESTS", "10"))
REFRESH_WINDOW_SECONDS = int(os.getenv("REFRESH_RATE_LIMIT_WINDOW_SECONDS", "3600"))

# Retry requirements endpoint: 5 requests per 10 minutes per session
# - Prevents excessive API costs
# - Protects against abuse/spam
# - 10 minute window allows legitimate retries without excessive waiting
RETRY_MAX_REQUESTS = int(os.getenv("RETRY_RATE_LIMIT_MAX_REQUESTS", "5"))
RETRY_WINDOW_SECONDS = int(os.getenv("RETRY_RATE_LIMIT_WINDOW_SECONDS", "600"))

# Retry requirements per user: 15 requests per 10 minutes
# - Prevents users from bypassing per-session limit by creating multiple sessions
# - Higher than per-session limit (15 vs 5) to allow legitimate multi-session use
# - Same 10 minute window as per-session limiting
RETRY_USER_MAX_REQUESTS = int(os.getenv("RETRY_USER_RATE_LIMIT_MAX_REQUESTS", "15"))
RETRY_USER_WINDOW_SECONDS = int(os.getenv("RETRY_USER_RATE_LIMIT_WINDOW_SECONDS", "600"))

# CRUD operations: 30 requests per minute per user
# - Protects against spam and abuse of create/update/delete operations
# - Allows legitimate bulk operations while preventing excessive API use
# - 1 minute window for quick throttling of abusive behavior
CRUD_MAX_REQUESTS = int(os.getenv("CRUD_RATE_LIMIT_MAX_REQUESTS", "30"))
CRUD_WINDOW_SECONDS = int(os.getenv("CRUD_RATE_LIMIT_WINDOW_SECONDS", "60"))

# Billing checkout: 5 requests per hour per user
# - Prevents abuse of Stripe checkout session creation
# - Allows legitimate retries while preventing spam
# - 1 hour window to prevent excessive Stripe API costs
BILLING_CHECKOUT_MAX_REQUESTS = int(os.getenv("BILLING_CHECKOUT_RATE_LIMIT_MAX_REQUESTS", "5"))
BILLING_CHECKOUT_WINDOW_SECONDS = int(os.getenv("BILLING_CHECKOUT_RATE_LIMIT_WINDOW_SECONDS", "3600"))

# Billing portal: 10 requests per hour per user
# - Prevents abuse of Stripe portal session creation
# - Higher limit than checkout as portal access is more common
# - 1 hour window for reasonable access control
BILLING_PORTAL_MAX_REQUESTS = int(os.getenv("BILLING_PORTAL_RATE_LIMIT_MAX_REQUESTS", "10"))
BILLING_PORTAL_WINDOW_SECONDS = int(os.getenv("BILLING_PORTAL_RATE_LIMIT_WINDOW_SECONDS", "3600"))

# Global rate limiters
oauth_rate_limiter = RateLimiter(max_requests=OAUTH_MAX_REQUESTS, window_seconds=OAUTH_WINDOW_SECONDS)
refresh_token_rate_limiter = RateLimiter(max_requests=REFRESH_MAX_REQUESTS, window_seconds=REFRESH_WINDOW_SECONDS)
retry_requirements_rate_limiter = RateLimiter(max_requests=RETRY_MAX_REQUESTS, window_seconds=RETRY_WINDOW_SECONDS)
retry_user_rate_limiter = RateLimiter(max_requests=RETRY_USER_MAX_REQUESTS, window_seconds=RETRY_USER_WINDOW_SECONDS)
crud_rate_limiter = RateLimiter(max_requests=CRUD_MAX_REQUESTS, window_seconds=CRUD_WINDOW_SECONDS)
billing_checkout_rate_limiter = RateLimiter(
    max_requests=BILLING_CHECKOUT_MAX_REQUESTS, window_seconds=BILLING_CHECKOUT_WINDOW_SECONDS
)
billing_portal_rate_limiter = RateLimiter(
    max_requests=BILLING_PORTAL_MAX_REQUESTS, window_seconds=BILLING_PORTAL_WINDOW_SECONDS
)
rate_limit_middleware = RateLimitMiddleware(oauth_rate_limiter)


def check_billing_rate_limit(user_id: str, limiter: RateLimiter, endpoint_name: str) -> None:
    """Check rate limit for billing endpoints."""
    allowed, reset_time = limiter.is_allowed(user_id)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "rate_limit_exceeded",
                "message": f"Too many {endpoint_name} requests. Please try again later.",
                "details": [{"type": "rate_limit", "message": f"Rate limit reset at {reset_time}"}],
                "status_code": status.HTTP_429_TOO_MANY_REQUESTS,
            },
            headers={"Retry-After": str(reset_time - int(time.time()))},
        )
