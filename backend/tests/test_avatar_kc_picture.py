"""Keycloak picture claim follows the local avatar file.

The admin client is a fake. Nothing here talks to a live Keycloak.
People and hosts are fictional.
"""

import copy
import io
import logging
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
SCRIPTS = BACKEND / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# avatar_storage creates its directory at import. Keep that off /app, and
# restore the process environment so collecting this module does not leak.
_PREVIOUS_AVATAR_DIR = os.environ.get("AVATAR_STORAGE_DIR")
os.environ["AVATAR_STORAGE_DIR"] = tempfile.mkdtemp(prefix="oc-avatar-kc-import-")

import avatar_storage  # noqa: E402
import backfill_kc_picture as backfill_script  # noqa: E402

if _PREVIOUS_AVATAR_DIR is None:
    os.environ.pop("AVATAR_STORAGE_DIR", None)
else:
    os.environ["AVATAR_STORAGE_DIR"] = _PREVIOUS_AVATAR_DIR
from kc_picture_sync import (  # noqa: E402
    avatar_version,
    build_avatar_url,
    build_public_avatar_url,
    local_avatar_index,
    public_base_url,
    read_owner_id,
    write_owner_id,
)
from PIL import Image  # noqa: E402
from starlette.datastructures import UploadFile  # noqa: E402

import pytest  # noqa: E402

USER_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
PUBLIC_BASE = "https://avatars.example.com"
PLANTED_SECRET = "super-secret-token-value"


def _png_bytes(color=(20, 40, 60)) -> bytes:
    image = Image.new("RGB", (32, 32), color)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _user(picture=None, avatar_url=None):
    attributes = {
        "subscription_tier": ["member"],
        "access_token": [PLANTED_SECRET],
    }
    if picture is not None:
        attributes["picture"] = [picture]
    if avatar_url is not None:
        attributes["avatar_url"] = [avatar_url]
    return {
        "id": USER_ID,
        "username": "fictional.user",
        "email": "fictional.user@example.com",
        "attributes": attributes,
    }


class FakePictureAdmin:
    """In-memory stand-in for the Keycloak admin client."""

    def __init__(self):
        self.users = {USER_ID: _user()}
        self.puts = []
        self.gets = []
        self.fail = None

    async def get_user(self, user_id):
        self.gets.append(user_id)
        if self.fail == "get":
            raise RuntimeError(f"token={PLANTED_SECRET}")
        user = self.users.get(user_id)
        if user is None:
            return None
        return copy.deepcopy(user)

    async def put_user(self, user_id, representation):
        if self.fail == "put":
            raise RuntimeError(f"token={PLANTED_SECRET}")
        stored = copy.deepcopy(representation)
        stored["id"] = user_id
        if self.fail == "status":
            self.puts.append((user_id, stored))
            return False
        self.users[user_id] = stored
        self.puts.append((user_id, stored))
        return True


@pytest.fixture
def avatar_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(avatar_storage, "AVATAR_DIR", tmp_path)
    monkeypatch.setenv("FEDERATION_ENDPOINT_URL", PUBLIC_BASE)
    return tmp_path


@pytest.fixture
def fake_admin(monkeypatch):
    fake = FakePictureAdmin()
    monkeypatch.setattr(avatar_storage, "get_picture_admin", lambda: fake)
    return fake


def _upload_file(color=(20, 40, 60)):
    return UploadFile(filename="face.png", file=io.BytesIO(_png_bytes(color)))


def _expected_url(user_id, image_bytes):
    return build_avatar_url(user_id, avatar_version(image_bytes), base=PUBLIC_BASE)


@pytest.mark.asyncio
async def test_upload_sets_picture_and_avatar_url(avatar_dir, fake_admin):
    original = fake_admin.users[USER_ID]
    result = await avatar_storage.upload_user_avatar(USER_ID, _upload_file())

    assert result["success"] is True
    assert result["avatar_url"] == f"/api/v1/users/{USER_ID}/avatar"
    written = (avatar_dir / f"{USER_ID}-custom.png").read_bytes()
    expected = _expected_url(USER_ID, written)

    assert len(fake_admin.puts) == 1
    user_id, rep = fake_admin.puts[0]
    assert user_id == USER_ID
    assert rep["username"] == "fictional.user"
    assert rep["attributes"]["subscription_tier"] == ["member"]
    assert rep["attributes"]["picture"] == [expected]
    assert rep["attributes"]["avatar_url"] == [expected]
    assert "?v=" in expected
    assert len(expected.split("?v=", 1)[1]) == 12
    # The source user dict the fake held is not mutated in place.
    assert "picture" not in original["attributes"]

    await avatar_storage.upload_user_avatar(USER_ID, _upload_file())
    assert len(fake_admin.puts) == 1


@pytest.mark.asyncio
async def test_delete_clears_picture_and_avatar_url(avatar_dir, fake_admin):
    await avatar_storage.upload_user_avatar(USER_ID, _upload_file())
    assert fake_admin.puts

    result = await avatar_storage.delete_custom_avatar(USER_ID)

    assert result["success"] is True
    assert not (avatar_dir / f"{USER_ID}-custom.png").exists()
    cleared = fake_admin.puts[-1][1]
    assert "picture" not in cleared["attributes"]
    assert "avatar_url" not in cleared["attributes"]
    assert cleared["attributes"]["subscription_tier"] == ["member"]
    assert cleared["username"] == "fictional.user"


@pytest.mark.asyncio
async def test_delete_without_a_file_does_not_call_keycloak(avatar_dir, fake_admin):
    result = await avatar_storage.delete_custom_avatar(USER_ID)
    assert result["success"] is False
    assert fake_admin.gets == []
    assert fake_admin.puts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["put", "status"])
async def test_keycloak_failure_does_not_break_upload(avatar_dir, fake_admin, failure, caplog):
    fake_admin.fail = failure
    with caplog.at_level(logging.WARNING, logger="avatar_storage"):
        result = await avatar_storage.upload_user_avatar(USER_ID, _upload_file())

    assert result["success"] is True
    assert (avatar_dir / f"{USER_ID}-custom.png").exists()
    assert "Keycloak picture sync failed" in caplog.text
    assert PLANTED_SECRET not in caplog.text


@pytest.mark.asyncio
async def test_upload_without_public_base_still_saves(avatar_dir, fake_admin, monkeypatch, caplog):
    monkeypatch.delenv("FEDERATION_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("EXTERNAL_HOST", raising=False)
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    with caplog.at_level(logging.WARNING, logger="avatar_storage"):
        result = await avatar_storage.upload_user_avatar(USER_ID, _upload_file())

    assert result["success"] is True
    assert (avatar_dir / f"{USER_ID}-custom.png").exists()
    assert fake_admin.puts == []
    assert "No public base URL configured" in caplog.text


@pytest.mark.asyncio
async def test_cached_file_is_stamped_and_missing_file_clears(avatar_dir, fake_admin):
    cached = avatar_dir / f"{USER_ID}.png"
    cached.write_bytes(b"cached-avatar-bytes")
    await avatar_storage._stamp_served_avatar(USER_ID)
    expected = _expected_url(USER_ID, b"cached-avatar-bytes")
    assert fake_admin.puts[-1][1]["attributes"]["picture"] == [expected]

    cached.unlink()
    await avatar_storage._stamp_served_avatar(USER_ID)
    assert "picture" not in fake_admin.puts[-1][1]["attributes"]
    assert "avatar_url" not in fake_admin.puts[-1][1]["attributes"]


@pytest.mark.asyncio
async def test_reader_skips_our_own_avatar_url(monkeypatch):
    own = f"{PUBLIC_BASE}/api/v1/users/{USER_ID}/avatar?v=abc123abc123"
    external = "https://cdn.example.com/photos/fictional.png"

    async def get_user_by_id(user_id):
        assert user_id == USER_ID
        return {
            "email": "fictional.user@example.com",
            "attributes": {"avatar_url": [own], "picture": [external]},
        }

    import keycloak_integration
    monkeypatch.setattr(keycloak_integration, "get_user_by_id", get_user_by_id)

    assert await avatar_storage.get_keycloak_avatar_url(USER_ID) == external

    async def both_own(user_id):
        return {
            "email": "fictional.user@example.com",
            "attributes": {"avatar_url": [own], "picture": [own]},
        }

    monkeypatch.setattr(keycloak_integration, "get_user_by_id", both_own)
    assert await avatar_storage.get_keycloak_avatar_url(USER_ID) == avatar_storage.get_gravatar_url(
        "fictional.user@example.com"
    )


def test_public_base_url_uses_configured_origin_only(monkeypatch):
    monkeypatch.setenv("FEDERATION_ENDPOINT_URL", "https://dogfood.example.com/")
    monkeypatch.setenv("EXTERNAL_HOST", "other.example.com")
    monkeypatch.setenv("EXTERNAL_PROTOCOL", "http")
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    assert public_base_url() == "https://dogfood.example.com"

    monkeypatch.delenv("FEDERATION_ENDPOINT_URL", raising=False)
    monkeypatch.setenv("EXTERNAL_HOST", "prod.example.com")
    monkeypatch.setenv("EXTERNAL_PROTOCOL", "https")
    assert public_base_url() == "https://prod.example.com"

    monkeypatch.delenv("EXTERNAL_HOST", raising=False)
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    assert public_base_url() is None


def test_local_index_prefers_custom_and_ignores_non_users(tmp_path):
    custom = tmp_path / f"{USER_ID}-custom.png"
    plain = tmp_path / f"{USER_ID}.png"
    custom.write_bytes(b"custom")
    plain.write_bytes(b"plain")
    (tmp_path / "notes.txt").write_bytes(b"nope")
    (tmp_path / "not-a-user.png").write_bytes(b"nope")
    (tmp_path / f"{OTHER_ID}.png").write_bytes(b"other")

    index = local_avatar_index(tmp_path)
    assert index[USER_ID] == custom
    assert index[OTHER_ID].name == f"{OTHER_ID}.png"
    assert set(index) == {USER_ID, OTHER_ID}


@pytest.mark.asyncio
async def test_backfill_dry_run_does_not_write_and_apply_is_idempotent(tmp_path, capsys):
    image = b"local-avatar-bytes"
    (tmp_path / f"{USER_ID}.png").write_bytes(image)
    (tmp_path / "notes.txt").write_bytes(b"ignore")
    fake = FakePictureAdmin()
    fake.users[OTHER_ID] = _user()
    fake.users[OTHER_ID]["id"] = OTHER_ID
    expected = _expected_url(USER_ID, image)

    dry = await backfill_script.backfill_kc_picture(
        apply=False, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    out = capsys.readouterr().out
    assert dry == 0
    assert fake.puts == []
    assert out.strip() == f"{USER_ID}, , {expected}"
    assert OTHER_ID not in fake.gets
    assert PLANTED_SECRET not in out

    # picture already equals the new URL, avatar_url does not: apply still writes both.
    fake.users[USER_ID]["attributes"]["picture"] = [expected]
    applied = await backfill_script.backfill_kc_picture(
        apply=True, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    captured = capsys.readouterr()
    assert applied == 0
    assert len(fake.puts) == 1
    assert fake.puts[0][1]["attributes"]["picture"] == [expected]
    assert fake.puts[0][1]["attributes"]["avatar_url"] == [expected]
    assert PLANTED_SECRET not in captured.out
    assert PLANTED_SECRET not in captured.err

    again = await backfill_script.backfill_kc_picture(
        apply=True, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    assert again == 0
    assert len(fake.puts) == 1


@pytest.mark.asyncio
async def test_backfill_keycloak_errors_exit_nonzero_without_secrets(tmp_path, capsys):
    (tmp_path / f"{USER_ID}.png").write_bytes(b"local-avatar-bytes")
    fake = FakePictureAdmin()
    fake.fail = "get"

    code = await backfill_script.backfill_kc_picture(
        apply=True, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    captured = capsys.readouterr()
    assert code == 1
    assert fake.puts == []
    assert "keycloak read failed" in captured.err
    assert PLANTED_SECRET not in captured.out
    assert PLANTED_SECRET not in captured.err

    fake.fail = "status"
    code = await backfill_script.backfill_kc_picture(
        apply=True, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "keycloak write failed" in captured.err
    assert PLANTED_SECRET not in captured.err

    fake.fail = None
    fake.users.pop(USER_ID)
    puts_before = len(fake.puts)
    code = await backfill_script.backfill_kc_picture(
        apply=False, avatar_dir=tmp_path, admin=fake, base_url=PUBLIC_BASE
    )
    captured = capsys.readouterr()
    assert code == 1
    assert "not found" in captured.err
    assert len(fake.puts) == puts_before


def test_backfill_cli_defaults_to_dry_run_and_skips_keycloak_when_idle(tmp_path, monkeypatch):
    assert backfill_script.parse_args([]).apply is False
    assert backfill_script.parse_args(["--apply"]).apply is True

    def explode():
        raise AssertionError("live keycloak client must not be constructed")

    monkeypatch.setattr(backfill_script, "LiveKeycloakPictureAdmin", explode)
    assert backfill_script.main(["--avatar-dir", str(tmp_path)]) == 0

    (tmp_path / f"{USER_ID}.png").write_bytes(b"local-avatar-bytes")
    monkeypatch.delenv("FEDERATION_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("EXTERNAL_HOST", raising=False)
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    assert backfill_script.main(["--avatar-dir", str(tmp_path)]) == 2


@pytest.mark.asyncio
async def test_live_admin_put_logs_status_only(monkeypatch, caplog):
    import httpx
    import keycloak_integration
    from kc_picture_sync import LiveKeycloakPictureAdmin

    sent = {}

    class FakeResponse:
        status_code = 403
        text = PLANTED_SECRET

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def put(self, url, headers=None, json=None, timeout=None):
            sent["url"] = url
            sent["json"] = json
            sent["authorization"] = headers["Authorization"]
            return FakeResponse()

    async def fake_token():
        return "test-admin-token"

    monkeypatch.setattr(keycloak_integration, "get_admin_token", fake_token)
    monkeypatch.setattr(keycloak_integration, "KEYCLOAK_URL", "https://auth.example.com")
    monkeypatch.setattr(keycloak_integration, "KEYCLOAK_REALM", "uchub")
    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    with caplog.at_level(logging.DEBUG):
        ok = await LiveKeycloakPictureAdmin().put_user(
            USER_ID,
            {"id": USER_ID, "username": "fictional.user", "attributes": {"picture": ["https://avatars.example.com/a"]}},
        )

    assert ok is False
    assert sent["url"] == f"https://auth.example.com/admin/realms/uchub/users/{USER_ID}"
    assert sent["json"]["username"] == "fictional.user"
    assert sent["authorization"] == "Bearer test-admin-token"
    assert PLANTED_SECRET not in caplog.text
    assert "test-admin-token" not in caplog.text
    assert "HTTP 403" in caplog.text


def _console_public(avatar_dir, monkeypatch):
    public = avatar_dir / "public"
    public.mkdir()
    monkeypatch.setenv("PUBLIC_AVATAR_DIR", str(public))
    return public


@pytest.mark.asyncio
async def test_profile_and_admin_save_stamps_picture_and_avatar_url(avatar_dir, fake_admin, monkeypatch):
    """Both console uploads call save_console_avatar. The URL the page reads stays /avatars/."""
    public = _console_public(avatar_dir, monkeypatch)
    content = b"console-avatar-bytes"
    saved = await avatar_storage.save_console_avatar(
        email="fictional.user@example.com",
        user_id=USER_ID,
        content=content,
        ext=".png",
    )

    import hashlib
    digest = hashlib.md5(content).hexdigest()[:12]
    filename = f"fictional.user_{digest}.png"
    assert saved["filename"] == filename
    assert saved["relative_url"] == f"/avatars/{filename}"
    assert saved["public_url"] == f"{PUBLIC_BASE}/avatars/{filename}"
    assert saved["keycloak_updated"] is True
    assert (public / filename).read_bytes() == content
    assert "/api/v1/users/" not in saved["public_url"]

    user_id, rep = fake_admin.puts[0]
    assert user_id == USER_ID
    assert rep["username"] == "fictional.user"
    assert rep["attributes"]["picture"] == [saved["public_url"]]
    assert rep["attributes"]["avatar_url"] == [saved["public_url"]]
    assert rep["attributes"]["subscription_tier"] == ["member"]
    assert read_owner_id(avatar_dir, filename) == USER_ID

    await avatar_storage.save_console_avatar(
        email="fictional.user@example.com",
        user_id=USER_ID,
        content=content,
        ext=".PNG",
    )
    assert len(fake_admin.puts) == 1


@pytest.mark.asyncio
async def test_profile_save_resolves_email_when_session_has_no_subject(avatar_dir, fake_admin, monkeypatch):
    _console_public(avatar_dir, monkeypatch)

    async def get_user_by_email(email):
        assert email == "fictional.user@example.com"
        return {"id": USER_ID, "email": email}

    fake_admin.get_user_by_email = get_user_by_email
    saved = await avatar_storage.save_console_avatar(
        email="fictional.user@example.com",
        user_id="",
        content=b"face-bytes",
        ext=".png",
    )
    assert saved["keycloak_updated"] is True
    assert saved["relative_url"].startswith("/avatars/fictional.user_")
    assert fake_admin.puts[0][0] == USER_ID
    assert fake_admin.puts[0][1]["attributes"]["picture"] == [saved["public_url"]]
    assert fake_admin.puts[0][1]["attributes"]["avatar_url"] == [saved["public_url"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["put", "status"])
async def test_console_keycloak_failure_does_not_break_save(avatar_dir, fake_admin, monkeypatch, failure, caplog):
    public = _console_public(avatar_dir, monkeypatch)
    fake_admin.fail = failure
    with caplog.at_level(logging.WARNING, logger="avatar_storage"):
        saved = await avatar_storage.save_console_avatar(
            email="fictional.user@example.com",
            user_id=USER_ID,
            content=b"console-avatar-bytes",
            ext=".jpeg",
        )
    assert saved["keycloak_updated"] is False
    assert saved["relative_url"].startswith("/avatars/")
    assert any(public.iterdir())
    assert "Keycloak picture sync failed" in caplog.text
    assert PLANTED_SECRET not in caplog.text


@pytest.mark.asyncio
async def test_console_save_without_public_base_still_saves(avatar_dir, fake_admin, monkeypatch, caplog):
    public = _console_public(avatar_dir, monkeypatch)
    monkeypatch.delenv("FEDERATION_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("EXTERNAL_HOST", raising=False)
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    with caplog.at_level(logging.WARNING, logger="avatar_storage"):
        saved = await avatar_storage.save_console_avatar(
            email="fictional.user@example.com",
            user_id=USER_ID,
            content=b"console-avatar-bytes",
            ext=".png",
        )
    assert saved["keycloak_updated"] is False
    assert saved["public_url"] is None
    assert saved["relative_url"].startswith("/avatars/")
    assert any(public.iterdir())
    assert fake_admin.puts == []
    assert "No public base URL configured" in caplog.text


@pytest.mark.asyncio
async def test_admin_remove_clears_picture_and_avatar_url(avatar_dir, fake_admin, monkeypatch):
    public = _console_public(avatar_dir, monkeypatch)
    saved = await avatar_storage.save_console_avatar(
        email="fictional.user@example.com",
        user_id=USER_ID,
        content=b"console-avatar-bytes",
        ext=".png",
    )
    assert (public / saved["filename"]).exists()
    assert read_owner_id(avatar_dir, saved["filename"]) == USER_ID

    cleared = await avatar_storage.clear_console_avatar(
        user_id=USER_ID,
        email="fictional.user@example.com",
    )
    assert cleared["keycloak_updated"] is True
    attrs = fake_admin.puts[-1][1]["attributes"]
    assert "picture" not in attrs
    assert "avatar_url" not in attrs
    assert attrs["subscription_tier"] == ["member"]
    # The file stays so an old token does not 404. The owner record does not,
    # so a later backfill cannot put the attributes back.
    assert (public / saved["filename"]).is_file()
    assert read_owner_id(avatar_dir, saved["filename"]) is None

    await avatar_storage.clear_console_avatar(user_id=USER_ID, email="fictional.user@example.com")
    assert len(fake_admin.puts) == 2


@pytest.mark.asyncio
async def test_backfill_finds_public_avatars_and_apply_is_idempotent(tmp_path, capsys):
    storage = tmp_path / "storage"
    public = tmp_path / "public"
    storage.mkdir()
    public.mkdir()
    image = b"stored-avatar-bytes"
    (storage / f"{OTHER_ID}.png").write_bytes(image)
    owned_name = "fictional.user_abc123def456.png"
    orphan_name = "orphan.user_ffffffffffff.jpg"
    (public / owned_name).write_bytes(b"public-avatar-bytes")
    (public / orphan_name).write_bytes(b"orphan-bytes")
    (public / "notes.txt").write_bytes(b"ignore")
    write_owner_id(storage, owned_name, USER_ID)

    fake = FakePictureAdmin()
    fake.users[OTHER_ID] = _user()
    fake.users[OTHER_ID]["id"] = OTHER_ID
    public_url = build_public_avatar_url(owned_name, base=PUBLIC_BASE)
    stored_url = _expected_url(OTHER_ID, image)
    orphan_url = f"{PUBLIC_BASE}/avatars/{orphan_name}"

    dry = await backfill_script.backfill_kc_picture(
        apply=False,
        avatar_dir=storage,
        admin=fake,
        base_url=PUBLIC_BASE,
        public_dir=public,
    )
    out = capsys.readouterr().out
    assert dry == 0
    assert fake.puts == []
    assert f"{OTHER_ID}, , {stored_url}" in out
    assert f"{USER_ID}, , {public_url}" in out
    assert f"{orphan_name}, , {orphan_url}" in out
    assert "notes.txt" not in out
    assert PLANTED_SECRET not in out

    applied = await backfill_script.backfill_kc_picture(
        apply=True,
        avatar_dir=storage,
        admin=fake,
        base_url=PUBLIC_BASE,
        public_dir=public,
    )
    captured = capsys.readouterr()
    assert applied == 0
    by_user = {user_id: rep for user_id, rep in fake.puts}
    assert set(by_user) == {USER_ID, OTHER_ID}
    assert by_user[USER_ID]["attributes"]["picture"] == [public_url]
    assert by_user[USER_ID]["attributes"]["avatar_url"] == [public_url]
    assert by_user[OTHER_ID]["attributes"]["picture"] == [stored_url]
    assert by_user[OTHER_ID]["attributes"]["avatar_url"] == [stored_url]
    assert PLANTED_SECRET not in captured.out
    assert PLANTED_SECRET not in captured.err

    again = await backfill_script.backfill_kc_picture(
        apply=True,
        avatar_dir=storage,
        admin=fake,
        base_url=PUBLIC_BASE,
        public_dir=public,
    )
    assert again == 0
    assert len(fake.puts) == 2


def test_console_endpoints_call_shared_storage():
    server = (BACKEND / "server.py").read_text(encoding="utf-8")
    admin = (BACKEND / "user_management_api.py").read_text(encoding="utf-8")
    profile = server[server.index("async def update_profile"): server.index("async def validate_key_endpoint")]
    assert "save_console_avatar(" in profile
    assert "set_user_picture" not in profile
    upload = admin[admin.index("async def admin_set_user_avatar"): admin.index("async def admin_remove_user_avatar")]
    assert "save_console_avatar(" in upload
    assert "set_user_picture" not in upload
    removal = admin[admin.index("async def admin_remove_user_avatar"):]
    assert "clear_console_avatar(" in removal
    assert "set_user_picture" not in removal


def test_avatar_router_paths_do_not_match_console_uploads():
    console = {
        "/api/v1/auth/profile",
        "/api/v1/admin/users/{user_id_or_email}/avatar",
    }
    paths = {route.path for route in avatar_storage.router.routes}
    assert paths.isdisjoint(console)
    assert "/api/v1/users/{user_id}/avatar" in paths


def test_backfill_cli_lists_public_dir_without_calling_keycloak(tmp_path, monkeypatch):
    public = tmp_path / "public"
    public.mkdir()
    (public / "fictional.user_abc123def456.png").write_bytes(b"x")

    def explode():
        raise AssertionError("live keycloak client must not be constructed")

    monkeypatch.setattr(backfill_script, "LiveKeycloakPictureAdmin", explode)
    monkeypatch.delenv("FEDERATION_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("EXTERNAL_HOST", raising=False)
    monkeypatch.setenv("OPS_CENTER_URL", "http://ops-center-direct:8084")
    code = backfill_script.main([
        "--avatar-dir", str(tmp_path / "missing-storage"),
        "--public-dir", str(public),
    ])
    assert code == 2
    assert backfill_script.parse_args([]).public_dir is None
