#!/usr/bin/env python3
"""Backfill Keycloak ``picture`` and ``avatar_url`` from local avatar files.

Dry-run unless ``--apply``. Scans two directories:

- the storage dir (``AVATAR_STORAGE_DIR`` or ``/app/avatars``): ``{id}.png``
  and ``{id}-custom.png``. Custom wins. The new URL is the avatar route.
- ``public/avatars`` (``PUBLIC_AVATAR_DIR`` or ``/app/public/avatars``):
  every image the console wrote. One line per file. When an owner record
  names the Keycloak user, the new URL is ``{origin}/avatars/{filename}``.
  A file with no owner record is listed and not written.

Prints, for each file that maps to a user:

    <user id>, <current picture attribute>, <new URL>

A file in public/avatars with no owner record prints the filename in place
of the user id. A second ``--apply`` does not write when both attributes
already equal the new URL.

Exits 1 on any Keycloak error and 2 when files exist but no public base
URL is configured. Never prints tokens or response bodies.

Dogfood (container workdir is /app; ``./public`` is mounted at ``/app/public``
and ``./avatars`` at ``/app/avatars``):

    python3 scripts/backfill_kc_picture.py
    python3 scripts/backfill_kc_picture.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from kc_picture_sync import (  # noqa: E402
    LiveKeycloakPictureAdmin,
    attributes_match,
    avatar_version,
    build_avatar_url,
    build_public_avatar_url,
    default_avatar_dir,
    default_public_avatar_dir,
    first_attr,
    local_avatar_index,
    public_avatar_index,
    public_base_url,
    read_owner_id,
    sync_picture,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill Keycloak picture from local avatar files. Dry-run unless --apply."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write picture and avatar_url. Omit for a dry-run.",
    )
    parser.add_argument(
        "--avatar-dir",
        default=None,
        help="Avatar directory. Defaults to AVATAR_STORAGE_DIR or /app/avatars.",
    )
    parser.add_argument(
        "--public-dir",
        default=None,
        help="Console avatar directory. Defaults to PUBLIC_AVATAR_DIR or /app/public/avatars.",
    )
    return parser.parse_args(argv)


async def _sync_one(*, apply: bool, admin, user_id: str, new_url: str) -> int:
    """Print one line. Return 1 when a Keycloak read or write failed."""
    try:
        user = await admin.get_user(user_id)
    except Exception:
        print(f"ERROR {user_id}: keycloak read failed", file=sys.stderr)
        return 1
    if not user:
        print(f"ERROR {user_id}: keycloak user not found", file=sys.stderr)
        return 1

    current = first_attr(user, "picture") or ""
    print(f"{user_id}, {current}, {new_url}", flush=True)

    if not apply or attributes_match(user, new_url):
        return 0
    try:
        ok = await sync_picture(admin, user_id, new_url)
    except Exception:
        print(f"ERROR {user_id}: keycloak write failed", file=sys.stderr)
        return 1
    if not ok:
        print(f"ERROR {user_id}: keycloak write failed", file=sys.stderr)
        return 1
    return 0


async def backfill_kc_picture(
    *,
    apply: bool,
    avatar_dir: Path,
    admin,
    base_url: str,
    public_dir: Path | None = None,
) -> int:
    """Print one line per local avatar. Write only when ``apply`` is set.

    ``public_dir`` is the console directory. None skips it (callers that only
    have the storage dir, including older tests). ``main`` always passes it.

    Returns 0, or 1 when any Keycloak read or write failed.
    """
    index = local_avatar_index(avatar_dir)
    errors = 0
    for user_id in sorted(index):
        path = index[user_id]
        new_url = build_avatar_url(user_id, avatar_version(path.read_bytes()), base=base_url)
        if not new_url:
            print(f"ERROR {user_id}: could not build avatar URL", file=sys.stderr)
            errors += 1
            continue
        errors += await _sync_one(apply=apply, admin=admin, user_id=user_id, new_url=new_url)

    if public_dir is not None:
        for path in public_avatar_index(public_dir):
            filename = path.name
            new_url = build_public_avatar_url(filename, base=base_url)
            if not new_url:
                print(f"ERROR {filename}: could not build avatar URL", file=sys.stderr)
                errors += 1
                continue
            user_id = read_owner_id(avatar_dir, filename)
            if not user_id:
                # Still one line per file. Nothing to write without a user id.
                print(f"{filename}, , {new_url}", flush=True)
                continue
            errors += await _sync_one(apply=apply, admin=admin, user_id=user_id, new_url=new_url)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    avatar_dir = Path(args.avatar_dir) if args.avatar_dir else default_avatar_dir()
    public_dir = Path(args.public_dir) if args.public_dir else default_public_avatar_dir()
    index = local_avatar_index(avatar_dir)
    public_files = public_avatar_index(public_dir)
    if not index and not public_files:
        print("no local avatar files", file=sys.stderr)
        return 0

    base_url = public_base_url()
    if not base_url:
        print(
            "ERROR public base URL is not configured "
            "(FEDERATION_ENDPOINT_URL or EXTERNAL_HOST)",
            file=sys.stderr,
        )
        return 2

    admin = LiveKeycloakPictureAdmin()
    return asyncio.run(
        backfill_kc_picture(
            apply=args.apply,
            avatar_dir=avatar_dir,
            admin=admin,
            base_url=base_url,
            public_dir=public_dir,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
