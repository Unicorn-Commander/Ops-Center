"""
Regression guards for the 2026-07-31 billing incident.

THE INCIDENT: `deduct_org_credits()` bound a Python dict to a jsonb query
parameter. asyncpg raises DataError *before* sending the query, so nothing was
ever written -- no allocation update, no pool update, no attribution row. The
LLM route turned that into a 500; the TTS route swallowed it and served real
(paid) ElevenLabs audio for free. An AST sweep then found ten more instances of
the same shape across the backend, including the Stripe credit-purchase path,
which charged the customer and then failed to record the purchase.

WHY IT SURVIVED ~8 MONTHS: the default model `uc/chat-default` is priced 0/0.
Its settle path computes zero cost and therefore never reaches the deduction at
all. Every smoke test against the default model passed while every *billable*
model was broken. Asserting a 200 proves nothing here.

So these tests assert the LEDGER MOVED, and statically forbid the bug shape.
"""

import ast
import os
import pathlib
import re

import pytest

try:  # pytest-asyncio runs in strict mode here: async fixtures need its decorator
    import pytest_asyncio
    async_fixture = pytest_asyncio.fixture
except ImportError:  # pragma: no cover - static gate still runs without it
    async_fixture = pytest.fixture

BACKEND = pathlib.Path(os.environ.get("OPS_CENTER_BACKEND", "/app"))

# executemany is deliberately excluded: its second argument is a *sequence of
# parameter tuples*, not a single bound parameter, so a list there is correct.
ASYNCPG_METHODS = {"execute", "fetch", "fetchval", "fetchrow"}

# asyncpg uses POSITIONAL placeholders ($1, $2). Kuzu and other drivers use
# NAMED ones ($name) with a dict of parameters, which is legitimate. Requiring a
# digit after the $ separates them without guessing at imports -- note that 3 of
# the 7 real defects did NOT import asyncpg directly, so an import-based filter
# would have produced false negatives, which are far worse than false positives.
POSITIONAL_PLACEHOLDER = re.compile(r"\$\d")

SKIP_DIRS = {"__pycache__", "archive", "dist", "node_modules", ".git", "tests"}

# Sites intentionally exempt. Keep this EMPTY unless there is a real reason, and
# always say why -- an entry here is a standing promise that the value is
# already a JSON string or the destination is not json/jsonb.
ALLOWLIST: set[tuple[str, int]] = set()


@async_fixture
async def org_credit_env():
    """A disposable org + funded pool + user allocation.

    Creates its own org and tears it down, so it never touches real billing
    data even when pointed at a live database. Skips (does not fail) when no
    database is reachable, so the static gate above still runs anywhere.
    """
    import uuid

    import asyncpg

    dsn = os.environ.get("DATABASE_URL") or (
        "postgresql://{u}:{p}@{h}:{port}/{db}".format(
            u=os.environ.get("POSTGRES_USER", "unicorn"),
            p=os.environ.get("POSTGRES_PASSWORD", ""),
            h=os.environ.get("POSTGRES_HOST", "unicorn-postgresql"),
            port=os.environ.get("POSTGRES_PORT", "5432"),
            db=os.environ.get("POSTGRES_DB", "unicorn_db"),
        )
    )
    try:
        conn = await asyncpg.connect(dsn, timeout=5)
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"no database available for ledger regression tests: {exc}")

    org_id = uuid.uuid4()
    user_id = f"ledger-regression-{uuid.uuid4()}"
    try:
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3)",
            org_id, f"ledger-regression-{org_id}", f"ledger-regression-{org_id}",
        )
        await conn.execute(
            "INSERT INTO organization_members (org_id, user_id, role) "
            "VALUES ($1, $2, 'owner')",
            org_id, user_id,
        )
        # available_credits is a GENERATED column (total - allocated); inserting
        # it explicitly raises GeneratedAlwaysError.
        await conn.execute(
            "INSERT INTO organization_credit_pools (org_id, total_credits) "
            "VALUES ($1, 100000)",
            org_id,
        )
        await conn.fetchval(
            "SELECT allocate_credits_to_user($1, $2, $3, $4)",
            org_id, user_id, 50000, user_id,
        )
        yield conn, org_id, user_id
    finally:
        for table in (
            "credit_usage_attribution",
            "user_credit_allocations",
            "organization_credit_pools",
            "organization_members",
        ):
            await conn.execute(f"DELETE FROM {table} WHERE org_id = $1", org_id)
        await conn.execute("DELETE FROM organizations WHERE id = $1", org_id)
        await conn.close()


def _python_files():
    for path in BACKEND.rglob("*.py"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name.endswith((".bak", ".orig")) or ".bak-" in path.name:
            continue
        yield path


def _is_json_dumps(node: ast.AST) -> bool:
    """True if the expression is (or resolves through) a json.dumps(...) call."""
    if isinstance(node, ast.IfExp):  # json.dumps(x) if x else None
        return _is_json_dumps(node.body) or _is_json_dumps(node.orelse)
    if isinstance(node, ast.Constant):  # None / "{}" are valid jsonb bindings
        return True
    if not isinstance(node, ast.Call):
        return False
    fn = node.func
    if isinstance(fn, ast.Attribute) and fn.attr == "dumps":
        return True
    return False


def _looks_like_json_payload(node: ast.AST) -> bool:
    """The shapes that bit us: a dict literal, `X or {}`, or `.dict()`.

    LISTS ARE DELIBERATELY NOT FLAGGED. A Python list is the *correct* binding
    for a Postgres text[]/int[] column and for `= ANY($1)`, and treating those
    as defects produced a dozen false positives on the first pass. A dict, by
    contrast, has essentially no legitimate destination other than json/jsonb.
    """
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return True
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        return any(isinstance(v, ast.Dict) for v in node.values)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        # pydantic .dict() / .model_dump() bound straight into a query
        return node.func.attr in {"dict", "model_dump"}
    return False


def _sql_is_positional(node: ast.AST) -> bool:
    """True when the first argument is literal SQL using $1-style placeholders."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return bool(POSITIONAL_PLACEHOLDER.search(node.value))
    if isinstance(node, ast.JoinedStr):  # f-string SQL
        return any(
            isinstance(v, ast.Constant)
            and isinstance(v.value, str)
            and POSITIONAL_PLACEHOLDER.search(v.value)
            for v in node.values
        )
    return False


def _dict_valued_locals(fn_node: ast.AST) -> set[str]:
    """Names assigned a dict literal (or .dict()) inside this function.

    THIS IS THE IMPORTANT PART. The original 2026-07-31 defect was
    `metadata = {...}` followed by binding the bare name `metadata`. Matching
    only literal expressions at the call site missed it entirely -- verified by
    running this gate against the pre-fix sources, where it caught 5 of 11
    defects and let the actual incident through. A gate that would not have
    caught the real bug is worse than no gate, because it manufactures
    confidence.
    """
    names: set[str] = set()
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Assign):
            continue
        if not (isinstance(node.value, (ast.Dict, ast.DictComp))
                or (isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and node.value.func.attr in {"dict", "model_dump"})):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


def test_no_unserialized_dict_bound_to_a_query_parameter():
    """Static gate for the ENTIRE bug class, across every backend module.

    A `::jsonb` cast in the SQL does NOT fix this -- asyncpg still infers the
    parameter as jsonb and still demands a str. Only json.dumps() fixes it.

    KNOWN LIMIT: a dict arriving from a call or a parameter (e.g.
    `alert.get("labels", {})`) cannot be resolved statically without type
    inference, and dynamically-built SQL is invisible here. That gap is why
    test_billable_deduction_actually_moves_the_ledger exists -- the two layers
    cover each other, and neither is sufficient alone.
    """
    offenders = []

    for path in _python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        # Map every call to the set of dict-valued locals of its enclosing
        # function, so bare-name bindings can be resolved.
        scopes: list[tuple[ast.AST, set[str]]] = [
            (fn, _dict_valued_locals(fn))
            for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not (isinstance(fn, ast.Attribute) and fn.attr in ASYNCPG_METHODS):
                continue
            if not node.args or not _sql_is_positional(node.args[0]):
                continue

            dict_locals: set[str] = set()
            for scope_node, names in scopes:
                if (getattr(scope_node, "lineno", 0) <= node.lineno
                        <= getattr(scope_node, "end_lineno", 0)):
                    dict_locals |= names

            # args[0] is the SQL; every arg after it is a bound parameter.
            for arg in node.args[1:]:
                is_bad = _looks_like_json_payload(arg) or (
                    isinstance(arg, ast.Name) and arg.id in dict_locals
                )
                if is_bad and not _is_json_dumps(arg):
                    rel = str(path.relative_to(BACKEND))
                    if (rel, arg.lineno) in ALLOWLIST:
                        continue
                    offenders.append(f"{rel}:{arg.lineno}")

    assert not offenders, (
        "Unserialized dict/list bound to a query parameter. asyncpg needs a JSON "
        "string for json/jsonb params and raises DataError before the query is "
        "sent -- which means the write silently never happens.\n"
        "Wrap it: json.dumps(value), or json.dumps(value) if value is not None "
        "else None for nullable columns.\n  " + "\n  ".join(sorted(offenders))
    )


@pytest.mark.asyncio
async def test_billable_deduction_actually_moves_the_ledger(org_credit_env):
    """A NON-zero cost must change the ledger. Not return True -- change it.

    Parameterized on a real cost because the zero-cost default model is exactly
    what hid the original bug.
    """
    conn, org_id, user_id = org_credit_env
    from org_credit_integration import OrgCreditIntegration

    async def used() -> int:
        return await conn.fetchval(
            "SELECT used_credits FROM user_credit_allocations "
            "WHERE org_id = $1 AND user_id = $2",
            org_id, user_id,
        )

    before = await used()
    before_rows = await conn.fetchval(
        "SELECT count(*) FROM credit_usage_attribution WHERE org_id = $1", org_id
    )

    ok, _, _ = await OrgCreditIntegration().deduct_org_credits(
        user_id=user_id,
        credits_used=0.25,
        service_name="regression-test",
        provider="regression",
        model="regression-model",
        tokens_used=1000,
        power_level="balanced",
        task_type="test",
        request_id="ledger-regression",
        org_id=org_id,
    )

    assert ok is True, "deduct_org_credits reported failure"
    assert await used() > before, (
        "used_credits did not move. The call may have raised and been swallowed "
        "upstream -- this is the exact 2026-07-31 failure."
    )
    assert await conn.fetchval(
        "SELECT count(*) FROM credit_usage_attribution WHERE org_id = $1", org_id
    ) > before_rows, "no audit row written for a billed request"


@pytest.mark.asyncio
async def test_sub_millicredit_charge_is_not_rounded_away(org_credit_env):
    """Tiny-but-real charges must not bill zero.

    `int(credits_used * 1000)` TRUNCATES: a measured 0.000693-credit call billed
    nothing. Cheap models and short completions are a large share of traffic, so
    truncation is systematic under-billing, not a rounding curiosity.
    """
    conn, org_id, user_id = org_credit_env
    from org_credit_integration import OrgCreditIntegration

    async def used() -> int:
        return await conn.fetchval(
            "SELECT used_credits FROM user_credit_allocations "
            "WHERE org_id = $1 AND user_id = $2",
            org_id, user_id,
        )

    before = await used()
    ok, _, _ = await OrgCreditIntegration().deduct_org_credits(
        user_id=user_id,
        credits_used=0.000271,  # a real observed qwen3-8b completion
        service_name="regression-test-tiny",
        provider="regression",
        model="regression-model",
        tokens_used=5,
        power_level="balanced",
        task_type="test",
        request_id="tiny-charge-regression",
        org_id=org_id,
    )

    assert ok is True
    assert await used() >= before + 1, (
        "a non-zero charge billed zero milicredits -- truncation regression"
    )
