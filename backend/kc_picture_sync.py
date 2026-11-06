"""Sync a local Ops-Center avatar into the Keycloak picture claim.

The uchub realm already maps the user attribute ``picture`` onto the OIDC
``picture`` claim. Email-Ops also accepts ``avatar_url``, and
``get_keycloak_avatar_url`` reads that attribute first, so both are written
together.

The public URL is this deployment's configured origin plus the avatar route.
No host is hardcoded and no new environment name is introduced:

1. ``FEDERATION_ENDPOINT_URL`` — the node's externally reachable base.
2. ``EXTERNAL_PROTOCOL`` + ``EXTERNAL_HOST`` — the pair the profile avatar
   stamp already uses.

Writes go through the existing admin client in ``keycloak_integration``
(``get_user_by_id`` + ``get_admin_token``). Keycloak 26 rejects a partial
user PUT, so the full representation is sent back.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PICTURE_ATTR = "picture"
AVATAR_URL_ATTR = "avatar_url"

# Keycloak user ids are UUIDs. Anything else in the avatar directory is not a user file.
_USER_ID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_CUSTOM_SUFFIX = "-custom.png"
_PLAIN_SUFFIX = ".png"


def default_avatar_dir() -> Path:
    """Same directory ``avatar_storage`` writes. ``AVATAR_STORAGE_DIR`` already exists."""
    return Path(os.getenv("AVATAR_STORAGE_DIR", "/app/avatars"))


def public_base_url() -> Optional[str]:
    """Absolute public origin for this deployment, without a trailing slash.

    ``OPS_CENTER_URL`` is intentionally not consulted: its default is the
    in-cluster address, which is not a URL another app can render.
    """
    federation = (os.getenv("FEDERATION_ENDPOINT_URL") or "").strip().rstrip("/")
    if federation.startswith(("http://", "https://")):
        return federation

    host = (os.getenv("EXTERNAL_HOST") or "").strip()
    if not host:
        return None
    protocol = (os.getenv("EXTERNAL_PROTOCOL") or "https").strip() or "https"
    return f"{protocol}://{host}".rstrip("/")


def avatar_version(image_bytes: bytes) -> str:
    """Cache-busting suffix. Twelve hex chars of sha256 is enough to change with the bytes."""
    return hashlib.sha256(image_bytes).hexdigest()[:12]


def build_avatar_url(user_id: str, version: str, base: Optional[str] = None) -> Optional[str]:
    """Absolute avatar URL, or None when this deployment has no public origin."""
    if not user_id or not version or "/" in user_id or ".." in user_id:
        return None
    origin = public_base_url() if base is None else base.rstrip("/")
    if not origin or not origin.startswith(("http://", "https://")):
        return None
    return f"{origin}/api/v1/users/{user_id}/avatar?v={version}"


def is_ops_center_avatar_url(url: str, user_id: str) -> bool:
    """True when ``url`` points at the avatar this service itself serves.

    ``get_keycloak_avatar_url`` treats ``avatar_url`` / ``picture`` as an
    upstream to download. Once those attributes hold our own URL, following
    them would fetch this process again.
    """
    if not url or not user_id:
        return False
    path = url.split("?", 1)[0].rstrip("/")
    return path.endswith(f"/api/v1/users/{user_id}/avatar")


def first_attr(user: Optional[dict], key: str) -> Optional[str]:
    """First Keycloak attribute value. Attributes are stored as lists of strings."""
    if not user:
        return None
    raw = (user.get("attributes") or {}).get(key)
    if isinstance(raw, list):
        if raw and raw[0]:
            return str(raw[0])
        return None
    if isinstance(raw, str) and raw:
        return raw
    return None


def attributes_match(user: Optional[dict], picture_url: Optional[str]) -> bool:
    """True when picture and avatar_url already equal the desired state."""
    picture = first_attr(user, PICTURE_ATTR)
    avatar_url = first_attr(user, AVATAR_URL_ATTR)
    if picture_url:
        return picture == picture_url and avatar_url == picture_url
    return not picture and not avatar_url


def user_representation_with_picture(user: dict, picture_url: Optional[str]) -> dict:
    """Copy of ``user`` with picture and avatar_url set, or both removed.

    The copy is what gets PUT. The caller's dict is left alone. Other
    attributes and the rest of the representation (username included) stay.
    """
    rep = {
        key: value
        for key, value in user.items()
        if key != "attributes"
    }
    attrs = dict(user.get("attributes") or {})
    if picture_url:
        attrs[PICTURE_ATTR] = [picture_url]
        attrs[AVATAR_URL_ATTR] = [picture_url]
    else:
        attrs.pop(PICTURE_ATTR, None)
        attrs.pop(AVATAR_URL_ATTR, None)
    rep["attributes"] = attrs
    return rep


def local_avatar_index(avatar_dir: Path) -> dict[str, Path]:
    """Map user id → local file. ``{id}-custom.png`` wins over ``{id}.png``.

    Non-UUID filenames are ignored. Users with no file are simply absent.
    """
    plain: dict[str, Path] = {}
    custom: dict[str, Path] = {}
    if not avatar_dir.is_dir():
        return {}
    for path in avatar_dir.iterdir():
        if not path.is_file():
            continue
        lower_name = path.name.lower()
        if lower_name.endswith(_CUSTOM_SUFFIX):
            user_id = lower_name[: -len(_CUSTOM_SUFFIX)]
            bucket = custom
        elif lower_name.endswith(_PLAIN_SUFFIX):
            user_id = lower_name[: -len(_PLAIN_SUFFIX)]
            bucket = plain
        else:
            continue
        if _USER_ID_RE.fullmatch(user_id):
            bucket.setdefault(user_id, path)
    return {
        user_id: custom.get(user_id) or plain[user_id]
        for user_id in set(plain) | set(custom)
    }


class LiveKeycloakPictureAdmin:
    """Admin reads and writes using the Keycloak client the backend already has.

    No new credential and no new environment name. Failures propagate to the
    caller; this class never logs a token or a response body.
    """

    async def get_user(self, user_id: str) -> Optional[dict]:
        from keycloak_integration import get_user_by_id

        return await get_user_by_id(user_id)

    async def put_user(self, user_id: str, representation: dict) -> bool:
        import httpx
        from keycloak_integration import KEYCLOAK_REALM, KEYCLOAK_URL, get_admin_token

        token = await get_admin_token()
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.put(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=representation,
                timeout=10.0,
            )
        if response.status_code == 204:
            return True
        logger.warning(
            "Keycloak picture update failed for user %s: HTTP %s",
            user_id,
            response.status_code,
        )
        return False


async def sync_picture(admin, user_id: str, picture_url: Optional[str]) -> bool:
    """Set or clear ``picture`` and ``avatar_url``.

    Returns False when the user cannot be read or Keycloak rejects the write.
    Returns True without a PUT when both attributes already match, so a second
    apply is a no-op. ``picture_url=None`` clears both attributes.
    """
    user = await admin.get_user(user_id)
    if not user:
        return False
    if attributes_match(user, picture_url):
        return True
    target_id = user.get("id") or user_id
    if not target_id:
        return False
    representation = user_representation_with_picture(user, picture_url)
    return await admin.put_user(target_id, representation)
