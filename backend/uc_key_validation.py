"""Pure helpers for UC API-key permission checks."""

import json
from typing import Callable, Optional


def parse_permissions(raw_permissions) -> list[str]:
    """Normalize list, JSON-string, and other iterable permission columns."""
    if raw_permissions is None:
        return []

    if isinstance(raw_permissions, str):
        try:
            raw_permissions = json.loads(raw_permissions)
        except (TypeError, ValueError):
            return []
        if isinstance(raw_permissions, str):
            return [raw_permissions] if raw_permissions else []

    if isinstance(raw_permissions, (bytes, bytearray)):
        return []

    try:
        values = list(raw_permissions)
    except TypeError:
        return []
    return [str(permission) for permission in values]


def check_required_permission(
    raw_permissions,
    required_permission: Optional[str],
    mcp_permission_checker: Optional[Callable] = None,
) -> tuple[list[str], bool]:
    """Return normalized permissions and whether they satisfy a requested scope."""
    permissions = parse_permissions(raw_permissions)
    if not required_permission:
        return permissions, True

    allowed = required_permission in permissions
    if not allowed and required_permission.startswith("mcp:"):
        if mcp_permission_checker is None:
            from uc_api_keys import key_has_mcp_permission

            mcp_permission_checker = key_has_mcp_permission
        app_slug = None if required_permission == "mcp:*" else required_permission[4:]
        allowed = mcp_permission_checker(permissions, app=app_slug or None)
    return permissions, allowed
