"""
Redis Session Manager for UC-Cloud
Replaces in-memory session storage with Redis-backed persistence
"""
import json
import logging
import redis
from typing import Optional, Dict, Any
import os
from urllib.parse import unquote, urlsplit, urlunsplit

logger = logging.getLogger(__name__)


class RedisSessionUnavailable(RuntimeError):
    """Raised when Redis cannot serve a request-time session lookup."""


def _env_float(name: str, default: float) -> float:
    """Read a non-negative float setting without making startup fragile."""
    try:
        return max(0.0, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _extract_redis_password(url: Optional[str] = None) -> Optional[str]:
    """Extract a URL-encoded password from a Redis URL when configured."""
    url = url if url is not None else os.getenv("REDIS_URL", "")
    if not url:
        return None
    try:
        parsed_url = urlsplit(url)
        return unquote(parsed_url.password) if parsed_url.password is not None else None
    except ValueError:
        # A malformed URL will be reported by redis-py when the client is built.
        return None


class RedisSessionManager:
    """Manages user sessions in Redis with TTL support"""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        db: Optional[int] = None,
        ttl: int = 7200,  # 2 hours in seconds
        key_prefix: str = "session:",
        password: Optional[str] = None,
        redis_url: Optional[str] = None,
    ):
        """
        Initialize Redis session manager

        Args:
            host: Redis host (default: unicorn-redis)
            port: Redis port (default: 6379)
            db: Redis database number (default: 0)
            ttl: Session time-to-live in seconds (default: 7200 = 2 hours)
            key_prefix: Prefix for session keys (default: "session:")
        """
        # REDIS_URL is authoritative when the caller did not provide an
        # explicit host/port/db. This supports URL-based deployments and the
        # older split env settings with the same singleton.
        configured_url = redis_url or (os.getenv("REDIS_URL") if host is None else None)
        if configured_url:
            parsed_url = urlsplit(configured_url)
            self.host = parsed_url.hostname or os.getenv("REDIS_HOST", "unicorn-redis")
            self.port = parsed_url.port or int(os.getenv("REDIS_PORT", "6379"))
            url_db = parsed_url.path.lstrip("/")
            self.db = int(url_db) if url_db.isdigit() else int(os.getenv("REDIS_DB", "0"))
            self.redis_url = configured_url
        else:
            self.host = host or os.getenv("REDIS_HOST", "unicorn-redis")
            self.port = port if port is not None else int(os.getenv("REDIS_PORT", "6379"))
            self.db = db if db is not None else int(os.getenv("REDIS_DB", "0"))
            self.redis_url = f"redis://{self.host}:{self.port}/{self.db}"
        self.ttl = ttl
        self.key_prefix = key_prefix
        self.password = password or os.getenv("REDIS_PASSWORD") or _extract_redis_password(self.redis_url)

        # Build exactly one configured client. Request handlers only use this
        # client and never enter the startup retry loop.
        self._client: Optional[redis.Redis] = self._create_client()
        self._connect(startup=True)

    def _create_client(self) -> redis.Redis:
        """Create the one Redis client used by this session manager."""
        parsed_url = urlsplit(self.redis_url)
        # Pass URL credentials explicitly so REDIS_PASSWORD can override a
        # stale password embedded in REDIS_URL without logging either value.
        url_without_credentials = urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc.rsplit("@", 1)[-1],
                parsed_url.path,
                parsed_url.query,
                parsed_url.fragment,
            )
        )
        kwargs = {
            "decode_responses": True,
            "socket_connect_timeout": _env_float("REDIS_SOCKET_CONNECT_TIMEOUT", 0.5),
            "socket_timeout": _env_float("REDIS_SOCKET_TIMEOUT", 0.5),
            "retry_on_timeout": False,
        }
        if parsed_url.username is not None:
            kwargs["username"] = unquote(parsed_url.username)
        if self.password is not None:
            kwargs["password"] = self.password
        return redis.Redis.from_url(url_without_credentials, **kwargs)

    def _connect(self, *, startup: bool = True):
        """Establish Redis connection.

        Bounded retry so a transient startup race (Redis still booting, or its
        DNS name not yet resolvable because the container is mid-restart) does
        NOT hard-crash the whole app at import time. Without this, a brief Redis
        blip cascades into a self-sustaining ops-center crash-loop. Retries for
        a bounded startup window, then raises (a genuine, sustained Redis outage
        still surfaces loud). Request handlers never call this method.
        """
        import time as _time
        try:
            configured_attempts = int(os.getenv("REDIS_CONNECT_ATTEMPTS", "15"))
        except (TypeError, ValueError):
            configured_attempts = 15
        attempts = max(1, configured_attempts) if startup else 1
        delay = _env_float("REDIS_CONNECT_RETRY_DELAY", 2.0) if startup else 0.0
        last_err = None
        for attempt in range(1, attempts + 1):
            try:
                # The client is created once above; retries only re-ping it.
                self._client.ping()
                logger.info(f"Redis session manager connected to {self.host}:{self.port}")
                return
            except Exception as e:
                last_err = e
                logger.warning(
                    f"Redis connect attempt {attempt}/{attempts} failed "
                    f"({self.host}:{self.port}): {e}"
                )
                if attempt < attempts:
                    _time.sleep(delay)
        logger.error(f"Failed to connect to Redis after {attempts} attempts: {last_err}")
        raise last_err

    def _get_key(self, session_id: str) -> str:
        """Generate full Redis key for session"""
        return f"{self.key_prefix}{session_id}"

    def set(self, session_id: str, session_data: Dict[str, Any]) -> bool:
        """
        Store session data in Redis with TTL

        Args:
            session_id: Unique session identifier
            session_data: Session data dictionary

        Returns:
            True if successful, False otherwise
        """
        try:
            key = self._get_key(session_id)
            value = json.dumps(session_data)
            self._client.setex(key, self.ttl, value)
            logger.debug(f"Session stored: {session_id[:10]}... (TTL: {self.ttl}s)")
            return True
        except Exception as e:
            logger.error(f"Failed to store session {session_id}: {e}")
            return False

    def get(self, session_id: str, *, fail_fast: bool = False) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data from Redis

        Args:
            session_id: Unique session identifier

        Returns:
            Session data dictionary or None if not found/expired
        """
        try:
            key = self._get_key(session_id)
            value = self._client.get(key)

            if value is None:
                logger.debug(f"Session not found or expired: {session_id[:10]}...")
                return None

            session_data = json.loads(value)
            logger.debug(f"Session retrieved: {session_id[:10]}...")
            return session_data
        except Exception as e:
            logger.error(f"Failed to retrieve session {session_id}: {e}")
            if fail_fast:
                raise RedisSessionUnavailable("Redis session store unavailable") from e
            return None

    def get_for_request(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Read a session once for an HTTP request, without retry or sleep."""
        return self.get(session_id, fail_fast=True)

    def delete(self, session_id: str) -> bool:
        """
        Delete session from Redis

        Args:
            session_id: Unique session identifier

        Returns:
            True if deleted, False otherwise
        """
        try:
            key = self._get_key(session_id)
            result = self._client.delete(key)
            if result:
                logger.debug(f"Session deleted: {session_id[:10]}...")
                return True
            else:
                logger.debug(f"Session not found for deletion: {session_id[:10]}...")
                return False
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            return False

    def exists(self, session_id: str) -> bool:
        """
        Check if session exists in Redis

        Args:
            session_id: Unique session identifier

        Returns:
            True if exists, False otherwise
        """
        try:
            key = self._get_key(session_id)
            return bool(self._client.exists(key))
        except Exception as e:
            logger.error(f"Failed to check session existence {session_id}: {e}")
            return False

    def refresh(self, session_id: str) -> bool:
        """
        Refresh session TTL (reset expiration timer)

        Args:
            session_id: Unique session identifier

        Returns:
            True if refreshed, False otherwise
        """
        try:
            key = self._get_key(session_id)
            result = self._client.expire(key, self.ttl)
            if result:
                logger.debug(f"Session TTL refreshed: {session_id[:10]}...")
                return True
            else:
                logger.debug(f"Session not found for refresh: {session_id[:10]}...")
                return False
        except Exception as e:
            logger.error(f"Failed to refresh session {session_id}: {e}")
            return False

    def count(self) -> int:
        """
        Count total active sessions

        Returns:
            Number of active sessions
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = self._client.keys(pattern)
            return len(keys)
        except Exception as e:
            logger.error(f"Failed to count sessions: {e}")
            return 0

    def clear_all(self) -> int:
        """
        Clear all sessions (use with caution!)

        Returns:
            Number of sessions cleared
        """
        try:
            pattern = f"{self.key_prefix}*"
            keys = self._client.keys(pattern)
            if keys:
                deleted = self._client.delete(*keys)
                logger.warning(f"Cleared {deleted} sessions")
                return deleted
            return 0
        except Exception as e:
            logger.error(f"Failed to clear sessions: {e}")
            return 0

    def __contains__(self, session_id: str) -> bool:
        """Support 'in' operator: if session_id in session_manager"""
        return self.exists(session_id)

    def __getitem__(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Support dict-style access: session_manager[session_id]"""
        session_data = self.get(session_id)
        if session_data is None:
            raise KeyError(f"Session not found: {session_id}")
        return session_data

    def __setitem__(self, session_id: str, session_data: Dict[str, Any]):
        """Support dict-style assignment: session_manager[session_id] = data"""
        self.set(session_id, session_data)

    def __delitem__(self, session_id: str):
        """Support dict-style deletion: del session_manager[session_id]"""
        if not self.delete(session_id):
            raise KeyError(f"Session not found: {session_id}")

    def close(self):
        """Close Redis connection"""
        if self._client:
            self._client.close()
            logger.info("Redis session manager connection closed")


# Create the one shared instance with environment-based configuration. Its
# constructor performs the bounded startup connection once; request handlers
# must import and reuse this object rather than constructing another manager.
redis_session_manager = RedisSessionManager(
    ttl=int(os.getenv("SESSION_TTL", "7200")),  # 2 hours
    key_prefix=os.getenv("SESSION_KEY_PREFIX", "session:"),
)
