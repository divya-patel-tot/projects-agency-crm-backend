from slowapi import Limiter
from slowapi.util import get_remote_address

# In-memory rate limits — no Redis required (suitable for single-process / small scale).
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    default_limits=["200/minute"],
)

# Tighter limits for auth mutations — wired in Phase 1 login/refresh resolvers.
AUTH_RATE_LIMIT = "10/minute"
AUTH_REFRESH_RATE_LIMIT = "20/minute"
