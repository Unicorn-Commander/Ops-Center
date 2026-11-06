"""
Avatar Storage Service

Provides centralized avatar management for UC-Cloud ecosystem:
- Downloads and caches avatars from external providers (Gravatar, Google, GitHub)
- Supports custom avatar uploads
- Solves CORS issues by serving avatars from same origin
- Persistent storage with Docker volume mounting

Usage:
    GET  /api/v1/users/{user_id}/avatar        - Get avatar (cached or fetch)
    POST /api/v1/users/{user_id}/avatar        - Upload custom avatar
    DELETE /api/v1/users/{user_id}/avatar      - Reset to provider avatar
    POST /api/v1/users/{user_id}/avatar/refresh - Force refresh from provider
"""

import os
import httpx
import hashlib
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Response
from fastapi.responses import FileResponse
from PIL import Image
import io
import logging

from kc_picture_sync import (
    LiveKeycloakPictureAdmin,
    avatar_version,
    build_avatar_url,
    build_public_avatar_url,
    console_avatar_filename,
    default_public_avatar_dir,
    forget_owner_id,
    is_keycloak_user_id,
    is_ops_center_avatar_url,
    sync_picture,
    write_owner_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["avatars"])

# Avatar storage configuration
AVATAR_DIR = Path(os.getenv("AVATAR_STORAGE_DIR", "/app/avatars"))
try:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
except OSError as exc:
    # Import must succeed where the volume is not mounted (tests, a mis-set path).
    # Writes call _ensure_avatar_dir() and still fail loudly if they cannot.
    logger.warning("Avatar directory not created at import (%s)", type(exc).__name__)

DEFAULT_AVATAR_PATH = Path(__file__).parent.parent / "static" / "default-avatar.png"
MAX_AVATAR_SIZE = 5 * 1024 * 1024  # 5MB
ALLOWED_FORMATS = {"PNG", "JPEG", "JPG", "WEBP"}
AVATAR_SIZE = (256, 256)  # Standardize all avatars to 256x256


def get_avatar_path(user_id: str, custom: bool = False) -> Path:
    """Get the file path for a user's avatar"""
    suffix = "-custom" if custom else ""
    return AVATAR_DIR / f"{user_id}{suffix}.png"


def _ensure_avatar_dir() -> Path:
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    return AVATAR_DIR


def get_picture_admin():
    """Keycloak admin client. Tests replace this with a fake."""
    return LiveKeycloakPictureAdmin()


async def _stamp_keycloak_picture(user_id: str, picture_url: Optional[str]) -> bool:
    """Set or clear the suite picture claim. A Keycloak miss must not fail the upload."""
    try:
        ok = await sync_picture(get_picture_admin(), user_id, picture_url)
        if not ok:
            logger.warning(
                "Keycloak picture sync failed for user %s; local avatar kept",
                user_id,
            )
        return bool(ok)
    except Exception as exc:
        logger.warning(
            "Keycloak picture sync failed for user %s (%s); local avatar kept",
            user_id,
            type(exc).__name__,
        )
        return False


# Console (profile + admin) writes. Same 2MB cap and extensions the endpoints already enforced.
CONSOLE_MAX_BYTES = 2 * 1024 * 1024


def public_avatar_dir() -> Path:
    """public/avatars, read at call time so tests can point it at a temp directory."""
    return default_public_avatar_dir()


async def _resolve_console_user_id(user_id: str, email: str) -> Optional[str]:
    """Keycloak user id from the caller, or from the email when the session has no subject."""
    if is_keycloak_user_id(user_id or ""):
        return user_id
    admin = get_picture_admin()
    finder = getattr(admin, "get_user_by_email", None)
    if finder is None or not email:
        logger.warning("No Keycloak user id; skipped picture sync")
        return None
    try:
        user = await finder(email)
    except Exception as exc:
        logger.warning(
            "Keycloak picture sync failed for user lookup (%s); local avatar kept",
            type(exc).__name__,
        )
        return None
    found = user.get("id") if isinstance(user, dict) else None
    if is_keycloak_user_id(str(found or "")):
        return str(found)
    logger.warning("No Keycloak user id; skipped picture sync")
    return None


async def save_console_avatar(*, email: str, user_id: str, content: bytes, ext: str) -> dict:
    """Write one console avatar and stamp Keycloak ``picture`` and ``avatar_url``.

    The profile upload and the admin upload both call this. The file name and
    the relative URL stay ``/avatars/{local-part}_{hash}{ext}``, which is what
    the console already puts in ``<img src>``. The Keycloak attributes get the
    absolute form of that same URL. A Keycloak failure is a warning; the file
    is still saved and this does not raise.
    """
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(content) > CONSOLE_MAX_BYTES:
        raise HTTPException(status_code=400, detail="File size must be less than 2MB")
    filename = console_avatar_filename(email, content, ext)
    if not filename:
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Allowed: .gif, .jpeg, .jpg, .png, .webp",
        )

    dest_dir = public_avatar_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = (dest_dir / filename).resolve()
    if dest_dir.resolve() not in path.parents:
        raise HTTPException(status_code=400, detail="Invalid file type. Allowed: .gif, .jpeg, .jpg, .png, .webp")
    path.write_bytes(content)

    relative_url = f"/avatars/{filename}"
    public_url = build_public_avatar_url(filename)
    resolved = await _resolve_console_user_id(user_id, email)
    kc_ok = False
    if resolved:
        try:
            write_owner_id(Path(AVATAR_DIR), filename, resolved)
        except OSError as exc:
            logger.warning("Avatar owner record not written (%s)", type(exc).__name__)
        if public_url is None:
            logger.warning(
                "No public base URL configured; skipped Keycloak picture sync for %s",
                resolved,
            )
        else:
            kc_ok = await _stamp_keycloak_picture(resolved, public_url)

    logger.info("Saved console avatar %s", filename)
    return {
        "relative_url": relative_url,
        "public_url": public_url,
        "filename": filename,
        "keycloak_updated": kc_ok,
    }


async def clear_console_avatar(*, user_id: str, email: str = "") -> dict:
    """Clear Keycloak ``picture`` and ``avatar_url`` for a console removal.

    The image file stays, matching the admin endpoint: old tokens must not 404
    mid-session. The owner record is dropped so a later backfill does not put
    the attributes back. A Keycloak failure is a warning; this does not raise.
    """
    resolved = await _resolve_console_user_id(user_id, email)
    if not resolved:
        return {"keycloak_updated": False}
    try:
        forget_owner_id(Path(AVATAR_DIR), resolved)
    except OSError as exc:
        logger.warning("Avatar owner record not cleared (%s)", type(exc).__name__)
    kc_ok = await _stamp_keycloak_picture(resolved, None)
    return {"keycloak_updated": kc_ok}


async def _stamp_served_avatar(user_id: str) -> None:
    """Point the claim at the file a normal GET would serve, or clear it."""
    custom_avatar_path = get_avatar_path(user_id, custom=True)
    cached_avatar_path = get_avatar_path(user_id, custom=False)
    if custom_avatar_path.exists():
        path = custom_avatar_path
    elif cached_avatar_path.exists():
        path = cached_avatar_path
    else:
        await _stamp_keycloak_picture(user_id, None)
        return

    picture_url = build_avatar_url(user_id, avatar_version(path.read_bytes()))
    if picture_url is None:
        logger.warning(
            "No public base URL configured; skipped Keycloak picture sync for %s",
            user_id,
        )
        return
    await _stamp_keycloak_picture(user_id, picture_url)


def get_gravatar_url(email: str, size: int = 256) -> str:
    """Generate Gravatar URL from email"""
    email_hash = hashlib.md5(email.lower().encode()).hexdigest()
    return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=mp"


async def fetch_external_avatar(url: str) -> Optional[bytes]:
    """Fetch avatar from external URL (Gravatar, Google, GitHub, etc.)"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, follow_redirects=True)
            if response.status_code == 200:
                return response.content
            logger.warning(f"Failed to fetch avatar from {url}: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Error fetching avatar from {url}: {e}")
        return None


def process_avatar_image(image_bytes: bytes) -> bytes:
    """
    Process and standardize avatar image:
    - Resize to 256x256
    - Convert to PNG
    - Optimize file size
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))

        # Convert to RGB if necessary (handles RGBA, P, etc.)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if img.mode == "P" else "RGB")

        # Resize to standard size
        img.thumbnail(AVATAR_SIZE, Image.Resampling.LANCZOS)

        # Create square canvas
        canvas = Image.new("RGBA" if img.mode == "RGBA" else "RGB", AVATAR_SIZE, (255, 255, 255, 0))
        offset = ((AVATAR_SIZE[0] - img.width) // 2, (AVATAR_SIZE[1] - img.height) // 2)
        canvas.paste(img, offset)

        # Save to bytes
        output = io.BytesIO()
        canvas.save(output, format="PNG", optimize=True)
        return output.getvalue()
    except Exception as e:
        logger.error(f"Error processing avatar image: {e}")
        raise HTTPException(status_code=400, detail="Invalid image format")


async def get_keycloak_avatar_url(user_id: str) -> Optional[str]:
    """Get avatar URL from Keycloak user attributes"""
    try:
        from keycloak_integration import get_user_by_id

        user = await get_user_by_id(user_id)
        if not user:
            return None
        attributes = user.get("attributes", {})

        # Check for avatar_url attribute. Skip our own avatar URL: once the
        # claim points here, fetching it would call this route again.
        avatar_urls = attributes.get("avatar_url", [])
        if avatar_urls and avatar_urls[0] and not is_ops_center_avatar_url(avatar_urls[0], user_id):
            return avatar_urls[0]

        # Fallback to picture attribute (Google/Microsoft, or our own claim)
        picture_urls = attributes.get("picture", [])
        if picture_urls and picture_urls[0] and not is_ops_center_avatar_url(picture_urls[0], user_id):
            return picture_urls[0]

        # Fallback to Gravatar using email
        email = user.get("email")
        if email:
            return get_gravatar_url(email)

        return None
    except Exception as e:
        logger.error(f"Error fetching Keycloak avatar URL for {user_id}: {e}")
        return None


@router.get("/{user_id}/avatar")
async def get_user_avatar(user_id: str, refresh: bool = False):
    """
    Get user avatar (cached or fetch from provider)

    Args:
        user_id: Keycloak user ID
        refresh: Force refresh from external provider

    Returns:
        PNG image (256x256)
    """
    # Check for custom uploaded avatar first
    custom_avatar_path = get_avatar_path(user_id, custom=True)
    if custom_avatar_path.exists() and not refresh:
        logger.info(f"Serving custom avatar for user {user_id}")
        return FileResponse(
            custom_avatar_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Avatar-Source": "custom",
                "Cross-Origin-Resource-Policy": "cross-origin"
            }
        )

    # Check for cached provider avatar
    cached_avatar_path = get_avatar_path(user_id, custom=False)
    if cached_avatar_path.exists() and not refresh:
        logger.info(f"Serving cached avatar for user {user_id}")
        return FileResponse(
            cached_avatar_path,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Avatar-Source": "cached",
                "Cross-Origin-Resource-Policy": "cross-origin"
            }
        )

    # Fetch from Keycloak/external provider
    avatar_url = await get_keycloak_avatar_url(user_id)
    if avatar_url:
        logger.info(f"Fetching avatar for user {user_id} from {avatar_url}")
        avatar_bytes = await fetch_external_avatar(avatar_url)

        if avatar_bytes:
            # Process and save
            try:
                processed_avatar = process_avatar_image(avatar_bytes)
                cached_avatar_path.write_bytes(processed_avatar)
                logger.info(f"Cached avatar for user {user_id}")

                return Response(
                    content=processed_avatar,
                    media_type="image/png",
                    headers={
                        "Cache-Control": "public, max-age=3600",
                        "X-Avatar-Source": "provider",
                        "Cross-Origin-Resource-Policy": "cross-origin"
                    }
                )
            except Exception as e:
                logger.error(f"Error processing avatar for user {user_id}: {e}")

    # Return default avatar
    logger.info(f"Serving default avatar for user {user_id}")
    if DEFAULT_AVATAR_PATH.exists():
        return FileResponse(
            DEFAULT_AVATAR_PATH,
            media_type="image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Avatar-Source": "default",
                "Cross-Origin-Resource-Policy": "cross-origin"
            }
        )

    # Fallback: Return 1x1 transparent PNG
    transparent_png = (
        b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
        b'\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01'
        b'\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
    )
    return Response(
        content=transparent_png,
        media_type="image/png",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Avatar-Source": "fallback",
            "Cross-Origin-Resource-Policy": "cross-origin"
        }
    )


@router.post("/{user_id}/avatar")
async def upload_user_avatar(
    user_id: str,
    file: UploadFile = File(...)
):
    """
    Upload custom avatar for user

    Args:
        user_id: Keycloak user ID
        file: Image file (PNG, JPEG, WEBP, max 5MB)

    Returns:
        Success message with avatar URL
    """
    # Validate file size
    content = await file.read()
    if len(content) > MAX_AVATAR_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large. Maximum size is {MAX_AVATAR_SIZE / 1024 / 1024}MB"
        )

    # Validate file format
    try:
        img = Image.open(io.BytesIO(content))
        if img.format not in ALLOWED_FORMATS:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image format. Allowed: {', '.join(ALLOWED_FORMATS)}"
            )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid image file: {str(e)}")

    # Process and save
    try:
        processed_avatar = process_avatar_image(content)
        _ensure_avatar_dir()
        custom_avatar_path = get_avatar_path(user_id, custom=True)
        custom_avatar_path.write_bytes(processed_avatar)

        logger.info(f"Uploaded custom avatar for user {user_id}")

        # Suite-wide claim. The local file is already saved; Keycloak is best-effort.
        picture_url = build_avatar_url(user_id, avatar_version(processed_avatar))
        if picture_url is None:
            logger.warning(
                "No public base URL configured; skipped Keycloak picture sync for %s",
                user_id,
            )
        else:
            await _stamp_keycloak_picture(user_id, picture_url)

        return {
            "success": True,
            "message": "Avatar uploaded successfully",
            "avatar_url": f"/api/v1/users/{user_id}/avatar",
            "size_bytes": len(processed_avatar)
        }
    except Exception as e:
        logger.error(f"Error uploading avatar for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to process avatar")


@router.delete("/{user_id}/avatar")
async def delete_custom_avatar(user_id: str):
    """
    Delete custom avatar and revert to provider avatar

    Args:
        user_id: Keycloak user ID

    Returns:
        Success message
    """
    custom_avatar_path = get_avatar_path(user_id, custom=True)

    if custom_avatar_path.exists():
        custom_avatar_path.unlink()
        logger.info(f"Deleted custom avatar for user {user_id}")
        # The custom photo is gone, so the suite claim is cleared. A cached
        # provider file is not the user's uploaded photo; refresh re-stamps it.
        await _stamp_keycloak_picture(user_id, None)
        return {
            "success": True,
            "message": "Custom avatar deleted. Reverted to provider avatar."
        }

    return {
        "success": False,
        "message": "No custom avatar to delete"
    }


@router.post("/{user_id}/avatar/refresh")
async def refresh_avatar_cache(user_id: str):
    """
    Force refresh avatar from external provider

    Args:
        user_id: Keycloak user ID

    Returns:
        Success message
    """
    # Delete cached avatar
    cached_avatar_path = get_avatar_path(user_id, custom=False)
    if cached_avatar_path.exists():
        cached_avatar_path.unlink()

    # Fetch new avatar
    await get_user_avatar(user_id, refresh=True)
    # Custom file still wins for a normal GET. Otherwise stamp the new cache,
    # or clear the claim when the provider returned nothing.
    await _stamp_served_avatar(user_id)

    logger.info(f"Refreshed avatar cache for user {user_id}")

    return {
        "success": True,
        "message": "Avatar cache refreshed",
        "avatar_url": f"/api/v1/users/{user_id}/avatar"
    }


@router.get("/{user_id}/avatar/info")
async def get_avatar_info(user_id: str):
    """
    Get information about user's avatar

    Args:
        user_id: Keycloak user ID

    Returns:
        Avatar metadata
    """
    custom_avatar_path = get_avatar_path(user_id, custom=True)
    cached_avatar_path = get_avatar_path(user_id, custom=False)

    has_custom = custom_avatar_path.exists()
    has_cached = cached_avatar_path.exists()

    info = {
        "user_id": user_id,
        "avatar_url": f"/api/v1/users/{user_id}/avatar",
        "has_custom_avatar": has_custom,
        "has_cached_avatar": has_cached,
        "source": "custom" if has_custom else ("cached" if has_cached else "default")
    }

    if has_custom:
        stat = custom_avatar_path.stat()
        info["custom_avatar"] = {
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime
        }

    if has_cached:
        stat = cached_avatar_path.stat()
        info["cached_avatar"] = {
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime
        }

    return info
