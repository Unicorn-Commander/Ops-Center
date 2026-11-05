"""Real PostgreSQL regression for the org switcher (org_access_api) and /org/my-orgs.

Organization memberships are keyed two ways in Ops-Center: current org APIs store the
verified Keycloak subject in organization_members.user_id, older rows store users.id and
map to the subject through users.zitadel_id. The org switcher used to match only the
first form, so a user whose real org was a legacy row saw only orgs created later
(2026-10-24: Aaron's switcher showed only the synthetic Rivergreen demo org).

Runs against a real database inside one transaction with temporary shadow tables, then
rolls back. Run inside the container:  python3 tests/test_org_access_subject_postgres.py
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import org_access_api  # noqa: E402
import org_api  # noqa: E402
from org_api import get_db_connection  # noqa: E402


class _Conn:
    """Pass-through to the test connection; endpoint close() must not end the test tx."""

    def __init__(self, conn):
        self._c = conn

    def __getattr__(self, name):
        return getattr(self._c, name)

    async def close(self):
        return None


class _Req:
    def __init__(self, cookies=None):
        self.cookies = cookies or {}


class _Resp:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, key, value, **_):
        self.cookies[key] = value


async def main():
    c = await get_db_connection()
    tx = c.transaction()
    await tx.start()
    try:
        await c.execute(
            """
            CREATE TEMP TABLE users(id text, zitadel_id text, email text) ON COMMIT DROP;
            CREATE TEMP TABLE organizations(id uuid, name text, slug text, plan_tier text,
                status text) ON COMMIT DROP;
            CREATE TEMP TABLE organization_members(org_id uuid, user_id text, role text,
                is_default boolean DEFAULT false, joined_at timestamptz) ON COMMIT DROP;
            CREATE TEMP TABLE subscription_tiers(id int, tier_code text, tier_name text) ON COMMIT DROP;
            """
        )
        real = "00000000-0000-4000-8000-000000000001"
        demo = "00000000-0000-4000-8000-000000000002"
        foreign = "00000000-0000-4000-8000-000000000003"
        await c.execute(
            f"""
            INSERT INTO users VALUES ('legacy-local', 'kc-sub', 'a@example.test'),
                                     ('other-local', 'other-sub', 'a@example.test');
            INSERT INTO organizations VALUES
                ('{real}', 'Zeta Real Co', NULL, 'vip_founder', 'active'),
                ('{demo}', 'Alpha Demo Co', NULL, 'free', 'active'),
                ('{foreign}', 'Foreign Co', NULL, 'free', 'active');
            INSERT INTO organization_members VALUES
                ('{real}', 'legacy-local', 'owner', true, '2026-01-17'),
                ('{demo}', 'kc-sub', 'owner', false, '2026-09-17'),
                ('{real}', 'kc-sub', 'member', false, '2026-10-01'),
                ('{foreign}', 'other-local', 'owner', true, '2026-01-01');
            """
        )
        checks = {}
        wrapped = _Conn(c)

        async def _db():
            return wrapped

        async def _uid(_request):
            return "kc-sub"

        org_access_api.get_db_connection = _db
        org_access_api.get_user_id_from_session = _uid
        org_api.get_db_connection = _db

        async def _user(_request):
            return {"id": "kc-sub"}

        org_api.get_current_user = _user

        res = await org_access_api.get_user_organizations(_Req())
        ids = [o.id for o in res.organizations]
        assert ids == [demo, real], ids  # both forms, deduped, display order by name
        assert res.default_org_id == real, res.default_org_id  # is_default legacy row wins
        assert res.current_org_id == real, res.current_org_id
        assert {o.id: o.role for o in res.organizations}[real] == "owner"  # default row's role
        checks["list-both-key-forms-default-first"] = "PASS"

        res = await org_access_api.get_user_organizations(_Req({"current_org_id": foreign}))
        assert res.current_org_id == real, res.current_org_id
        checks["foreign-cookie-ignored"] = "PASS"

        resp = _Resp()
        ok = await org_access_api.switch_organization(
            _Req(), resp, org_access_api.SwitchOrgRequest(org_id=real)
        )
        assert ok.org_id == real and resp.cookies.get("current_org_id") == real
        checks["switch-to-legacy-keyed-org"] = "PASS"

        try:
            await org_access_api.switch_organization(
                _Req(), _Resp(), org_access_api.SwitchOrgRequest(org_id=foreign)
            )
        except org_access_api.HTTPException as e:
            assert e.status_code == 403
            checks["switch-foreign-denied"] = "PASS"
        else:
            raise AssertionError("switch to foreign org was allowed")

        cur = await org_access_api.get_current_organization(_Req())
        assert cur.org_id == real, cur.org_id
        checks["current-falls-back-to-default"] = "PASS"

        mine = await org_api.get_my_organizations(_Req())
        assert [o["id"] for o in mine] == [demo, real], mine
        checks["my-orgs-both-key-forms"] = "PASS"

        print(json.dumps({"database": "real PostgreSQL; temp shadow tables; rolled back",
                          "checks": checks}))
    finally:
        await tx.rollback()
        await c.close()


if __name__ == "__main__":
    asyncio.run(main())
