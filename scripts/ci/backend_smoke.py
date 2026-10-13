#!/usr/bin/env python3
"""CI gate: static backend sanity checks — parses, never executes, the server.

What it asserts (all via `ast`, so no backend deps/DB/Redis are needed):

  1. backend/server.py parses, creates a FastAPI app, and wires the
     default-deny auth middleware (create_auth_middleware via add_middleware).
  2. Import-sanity for the most critical routers: server.py imports them,
     app.include_router()s them, the module file exists, parses, and actually
     defines the imported router symbol at module scope.
  3. backend/auth_middleware.py's PUBLIC_EXACT / PUBLIC_PREFIXES allowlists
     don't accidentally open admin/mutation surfaces: every literal or pure
     computed entry is checked against a denylist of admin-ish / destructive /
     credential-ish patterns, and over-broad prefixes (e.g. "/api/v1/") are
     rejected outright.
  4. Every /admin route in the model-catalog routers (model_access_api, model_admin_api) takes
     Depends(require_admin_user) as its first dependency.

Run from anywhere:  python3 scripts/ci/backend_smoke.py
Exits non-zero with a list of failures.
"""

import ast
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BACKEND = REPO / "backend"

# Critical routers: security / money / user-management surfaces. Keys are the
# module names exactly as server.py imports them; values are the router
# symbols server.py pulls out of each module.
CRITICAL_ROUTERS = {
    "user_management_api": ["router"],
    "account_management_api": ["router"],
    "billing_api": ["router"],
    "stripe_api": ["router"],
    "credit_api": ["router"],
    "org_api": ["router"],
    "subscription_api": ["router"],
    "admin_subscriptions_api": ["router"],
    "litellm_api": ["router"],
    "system_settings_api": ["router"],
    "local_user_api": ["router"],
    "invite_codes_api": ["admin_router", "user_router"],
    "webhooks": ["router"],  # Stripe webhooks
    "routers.audit_api": ["admin_router", "internal_router"],
    "routers.website_monitor": ["router"],
    "routers.federation": ["router"],
}

# Patterns that must NEVER appear in the auth middleware's public allowlists.
# These are admin/mutation surfaces; allowlisting one to "fix" a 401 would
# silently reopen the 2026-06-08 unauthenticated-endpoint hole.
DENY_PATTERNS = [
    (r"/admin\b", "admin-scoped path"),
    (r"/users?\b", "user-management surface"),
    (r"/organizations?\b", "organization-management surface"),
    # `revoke-self` is a deliberately self-authenticating uc_-key endpoint;
    # other revoke paths remain covered by this destructive-path rule.
    (r"/delete\b|/remove\b|/purge\b|/terminate\b|/revoke(?!-self\b)\b|/wipe\b", "destructive verb in path"),
    (r"/credentials?\b|/secrets?\b|/api-keys?\b|/service-keys?\b", "credential surface"),
    (r"/impersonat", "impersonation surface"),
    (r"/permissions?\b|/roles?\b", "authorization surface"),
    (r"/settings\b", "settings mutation surface"),
    (r"/sessions\b", "session administration surface"),
    (r"/keycloak\b", "identity-provider administration"),
    (r"/backups?\b|/restore\b", "backup/restore surface"),
]

# Prefixes this broad would disable the default-deny middleware wholesale.
OVERBROAD = {"/", "/api", "/api/", "/api/v1", "/api/v1/"}

# The resolver below is deliberately an AST interpreter rather than an import
# or exec of application code.  Keep this environment deterministic: the CI
# audit must not inherit a runner's secrets or deployment-specific settings.
STATIC_ENV_DEFAULTS = {
    "LEGACY_LOCAL_AUTH_ENABLED": "false",
}


class StaticResolutionError(Exception):
    """The static allowlist resolver cannot prove a value safely."""


class _StaticEnvironment:
    def __init__(self, values):
        self._values = dict(values)

    def get(self, key, default=None):
        if not isinstance(key, str):
            raise StaticResolutionError("os.environ keys must be string literals")
        return self._values.get(key, default)

    def __getitem__(self, key):
        value = self.get(key, None)
        if value is None and key not in self._values:
            raise StaticResolutionError(f"os.environ has no documented value for {key!r}")
        return value


class _StaticOS:
    def __init__(self):
        self.environ = _StaticEnvironment(STATIC_ENV_DEFAULTS)

    def getenv(self, key, default=None):
        return self.environ.get(key, default)


class _StaticSettings:
    """Small settings stub for pure allowlist builders.

    These values mirror the documented disabled-local-auth CI default.  An
    unknown setting remains an error instead of being guessed.
    """

    VALUES = {
        "LEGACY_LOCAL_AUTH_ENABLED": "false",
        "legacy_local_auth_enabled": False,
        "local_auth_enabled": False,
    }

    def get(self, key, default=None):
        return self.VALUES.get(key, default)

    def __getattr__(self, name):
        if name in self.VALUES:
            return self.VALUES[name]
        raise StaticResolutionError(f"settings.{name} has no documented static value")


class _StaticModule:
    def __init__(self, path, tree):
        self.path = path
        self.tree = tree
        self.functions = {}
        self.assignments = {}
        self.imports = {}

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.functions[node.name] = node
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        self.assignments[target.id] = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
                self.assignments[node.target.id] = node.value
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.split(".")[0]
                    self.imports[local] = ("module", alias.name, None, 0)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    local = alias.asname or alias.name
                    self.imports[local] = ("symbol", node.module, alias.name, node.level)


class _StaticModuleRef:
    def __init__(self, module):
        self.module = module


class _StaticFunction:
    def __init__(self, resolver, module, node):
        self.resolver = resolver
        self.module = module
        self.node = node


class _StaticCallable:
    def __init__(self, function, description):
        self.function = function
        self.description = description


class _StaticResolver:
    """Evaluate the small pure subset used by allowlist builder functions."""

    SAFE_BUILTINS = {
        "bool": bool,
        "len": len,
        "list": list,
        "str": str,
        "tuple": tuple,
    }
    SAFE_STRING_METHODS = {
        "casefold",
        "endswith",
        "lower",
        "replace",
        "startswith",
        "strip",
        "upper",
    }

    def __init__(self, entry_path):
        self.entry_path = entry_path.resolve()
        self.modules = {}
        self.assignment_cache = {}
        self.call_stack = []
        self.static_os = _StaticOS()
        self.static_settings = _StaticSettings()

    def resolve(self, expression):
        module = self._load_module(self.entry_path)
        return self._eval(expression, module, {})

    def _load_module(self, path):
        path = path.resolve()
        if path in self.modules:
            return self.modules[path]
        if not path.exists():
            raise StaticResolutionError(f"imported module {path} does not exist")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            raise StaticResolutionError(f"cannot parse {path}: {exc}") from exc
        module = _StaticModule(path, tree)
        self.modules[path] = module
        return module

    def _find_imported_module(self, module_name, importing_module, level):
        if level:
            directory = importing_module.path.parent
            for _ in range(level - 1):
                directory = directory.parent
            relative = (module_name or "").replace(".", "/")
            roots = [directory]
        else:
            relative = (module_name or "").replace(".", "/")
            roots = [importing_module.path.parent, BACKEND, REPO]

        for root in roots:
            candidate = root / f"{relative}.py"
            if candidate.exists():
                return self._load_module(candidate)
            package = root / relative / "__init__.py"
            if package.exists():
                return self._load_module(package)
        raise StaticResolutionError(
            f"cannot locate imported module {(module_name or '<package>')!r} "
            f"from {importing_module.path}"
        )

    def _resolve_import(self, module, name):
        kind, module_name, imported_name, level = module.imports[name]
        if module_name == "os" and not level:
            if kind == "module":
                return self.static_os
            if imported_name == "environ":
                return self.static_os.environ
            if imported_name == "getenv":
                return _StaticCallable(self.static_os.getenv, "os.getenv")
            raise StaticResolutionError(f"os.{imported_name} is not supported by the static environment")

        imported = self._find_imported_module(module_name, module, level)
        if kind == "module":
            return _StaticModuleRef(imported)
        return self._resolve_name(imported, imported_name, {})

    def _resolve_name(self, module, name, local_values):
        if name in local_values:
            return local_values[name]
        if name in module.functions:
            return _StaticFunction(self, module, module.functions[name])
        if name in module.assignments:
            key = (module.path, name)
            if key not in self.assignment_cache:
                self.assignment_cache[key] = self._eval(module.assignments[name], module, {})
            return self.assignment_cache[key]
        if name in module.imports:
            return self._resolve_import(module, name)
        if name in self.SAFE_BUILTINS:
            return self.SAFE_BUILTINS[name]
        if name == "os":
            return self.static_os
        if name == "settings":
            return self.static_settings
        raise StaticResolutionError(f"name {name!r} is not available in the static environment")

    def _resolve_attribute(self, value, name):
        if isinstance(value, _StaticModuleRef):
            return self._resolve_name(value.module, name, {})
        if value is self.static_os:
            if name == "environ":
                return value.environ
            if name == "getenv":
                return _StaticCallable(value.getenv, "os.getenv")
            raise StaticResolutionError(f"os.{name} is not supported by the static environment")
        if isinstance(value, _StaticEnvironment):
            if name == "get":
                return _StaticCallable(value.get, "os.environ.get")
            raise StaticResolutionError(f"os.environ.{name} is not supported by the static environment")
        if isinstance(value, _StaticSettings):
            if name == "get":
                return _StaticCallable(value.get, "settings.get")
            return getattr(value, name)
        if isinstance(value, str) and name in self.SAFE_STRING_METHODS:
            return _StaticCallable(getattr(value, name), f"str.{name}")
        raise StaticResolutionError(f"attribute {name!r} is not supported in the static environment")

    def _eval(self, node, module, local_values):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return self._resolve_name(module, node.id, local_values)
        if isinstance(node, ast.Tuple):
            return tuple(self._eval(item, module, local_values) for item in node.elts)
        if isinstance(node, ast.List):
            return [self._eval(item, module, local_values) for item in node.elts]
        if isinstance(node, ast.Set):
            return {self._eval(item, module, local_values) for item in node.elts}
        if isinstance(node, ast.Dict):
            if any(key is None for key in node.keys):
                raise StaticResolutionError("dictionary unpacking is not supported")
            return {
                self._eval(key, module, local_values): self._eval(value, module, local_values)
                for key, value in zip(node.keys, node.values)
            }
        if isinstance(node, ast.Attribute):
            return self._resolve_attribute(self._eval(node.value, module, local_values), node.attr)
        if isinstance(node, ast.Subscript):
            value = self._eval(node.value, module, local_values)
            key = self._eval(node.slice, module, local_values)
            try:
                return value[key]
            except (KeyError, IndexError, TypeError) as exc:
                raise StaticResolutionError(f"cannot resolve subscript {key!r}: {exc}") from exc
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            return self._eval(node.left, module, local_values) + self._eval(node.right, module, local_values)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.UAdd, ast.USub)):
            value = self._eval(node.operand, module, local_values)
            if isinstance(node.op, ast.Not):
                return not value
            return +value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                result = None
                for value_node in node.values:
                    result = self._eval(value_node, module, local_values)
                    if not result:
                        return result
                return result
            if isinstance(node.op, ast.Or):
                result = None
                for value_node in node.values:
                    result = self._eval(value_node, module, local_values)
                    if result:
                        return result
                return result
        if isinstance(node, ast.IfExp):
            branch = node.body if self._eval(node.test, module, local_values) else node.orelse
            return self._eval(branch, module, local_values)
        if isinstance(node, ast.Compare):
            left = self._eval(node.left, module, local_values)
            comparisons = []
            for operator, comparator in zip(node.ops, node.comparators):
                right = self._eval(comparator, module, local_values)
                if isinstance(operator, ast.Eq):
                    result = left == right
                elif isinstance(operator, ast.NotEq):
                    result = left != right
                elif isinstance(operator, ast.In):
                    result = left in right
                elif isinstance(operator, ast.NotIn):
                    result = left not in right
                else:
                    raise StaticResolutionError(f"comparison {type(operator).__name__} is not supported")
                comparisons.append(result)
                left = right
            return all(comparisons)
        if isinstance(node, ast.Call):
            function = self._eval(node.func, module, local_values)
            args = [self._eval(arg, module, local_values) for arg in node.args]
            keywords = {}
            for keyword in node.keywords:
                if keyword.arg is None:
                    raise StaticResolutionError("call argument unpacking is not supported")
                keywords[keyword.arg] = self._eval(keyword.value, module, local_values)
            return self._call(function, args, keywords)
        raise StaticResolutionError(f"expression {type(node).__name__} is not supported")

    def _call(self, function, args, keywords):
        if isinstance(function, _StaticFunction):
            return self._call_function(function, args, keywords)
        if isinstance(function, _StaticCallable):
            try:
                return function.function(*args, **keywords)
            except Exception as exc:
                raise StaticResolutionError(f"{function.description} failed: {exc}") from exc
        if function in self.SAFE_BUILTINS.values():
            try:
                return function(*args, **keywords)
            except Exception as exc:
                raise StaticResolutionError(f"safe builtin {function.__name__} failed: {exc}") from exc
        raise StaticResolutionError("call target is not an approved static function")

    def _call_function(self, function, args, keywords):
        if isinstance(function.node, ast.AsyncFunctionDef):
            raise StaticResolutionError(f"async function {function.node.name} cannot be evaluated statically")
        if function.node.name in self.call_stack:
            raise StaticResolutionError(f"recursive function {function.node.name} cannot be evaluated statically")

        positional = list(function.node.args.posonlyargs) + list(function.node.args.args)
        if function.node.args.vararg or function.node.args.kwarg or function.node.args.kwonlyargs:
            raise StaticResolutionError(
                f"function {function.node.name} uses unsupported *args/**kwargs or keyword-only arguments"
            )
        if len(args) > len(positional):
            raise StaticResolutionError(f"too many arguments for {function.node.name}")

        values = {}
        defaults = [_MISSING] * (len(positional) - len(function.node.args.defaults)) + list(function.node.args.defaults)
        for parameter, default in zip(positional, defaults):
            if args:
                values[parameter.arg] = args.pop(0)
            elif parameter.arg in keywords:
                values[parameter.arg] = keywords.pop(parameter.arg)
            elif default is not _MISSING:
                values[parameter.arg] = self._eval(default, function.module, {})
            else:
                raise StaticResolutionError(f"missing argument {parameter.arg!r} for {function.node.name}")
        if args or keywords:
            raise StaticResolutionError(f"unexpected arguments for {function.node.name}")

        self.call_stack.append(function.node.name)
        try:
            returned, value = self._execute_block(function.node.body, function.module, values)
        finally:
            self.call_stack.pop()
        if not returned:
            raise StaticResolutionError(f"function {function.node.name} has no static return value")
        return value

    def _execute_block(self, statements, module, local_values):
        for statement in statements:
            if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
                continue
            if isinstance(statement, ast.Pass):
                continue
            if isinstance(statement, ast.Return):
                value = None if statement.value is None else self._eval(statement.value, module, local_values)
                return True, value
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value_node = statement.value
                if value_node is None:
                    raise StaticResolutionError("annotated assignment has no value")
                targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                if len(targets) != 1 or not isinstance(targets[0], ast.Name):
                    raise StaticResolutionError("only simple local assignments are supported")
                local_values[targets[0].id] = self._eval(value_node, module, local_values)
                continue
            if isinstance(statement, ast.If):
                branch = statement.body if self._eval(statement.test, module, local_values) else statement.orelse
                returned, value = self._execute_block(branch, module, local_values)
                if returned:
                    return True, value
                continue
            raise StaticResolutionError(f"statement {type(statement).__name__} is not supported")
        return False, None


_MISSING = object()


def _find_allowlist_assignment(tree: ast.Module, name: str):
    """Return the last module-scope assignment value for *name*, if present."""
    value = _MISSING
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        else:
            continue
        if any(isinstance(target, ast.Name) and target.id == name for target in targets):
            value = node.value
    return value


def resolve_allowlist(path: Path, name: str):
    """Resolve an allowlist value without importing or executing app code.

    Literal values retain the original path.  PUBLIC_PREFIXES may additionally
    be a pure call expression whose function is defined in this module or a
    local imported module; unsupported expressions raise instead of passing an
    incomplete audit.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError) as exc:
        raise StaticResolutionError(f"cannot parse {path}: {exc}") from exc

    value = _find_allowlist_assignment(tree, name)
    if value is _MISSING:
        raise StaticResolutionError(f"{name} not found (renamed? middleware gutted?)")

    try:
        return ast.literal_eval(value)
    except (ValueError, TypeError, SyntaxError):
        if name != "PUBLIC_PREFIXES":
            raise StaticResolutionError(f"{name} is no longer a literal — cannot audit it statically")

    try:
        return _StaticResolver(path).resolve(value)
    except StaticResolutionError as exc:
        raise StaticResolutionError(f"{name} could not be resolved statically: {exc}") from exc

failures = []


def fail(msg: str) -> None:
    failures.append(msg)


def parse(path: Path):
    """ast.parse a file; record a failure and return None on error."""
    if not path.exists():
        fail(f"{path.relative_to(REPO)} does not exist")
        return None
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as e:
        fail(f"{path.relative_to(REPO)}:{e.lineno}: SyntaxError: {e.msg}")
        return None


def iter_module_scope(tree: ast.Module):
    """Yield statements at module scope, descending into if/try/with/loop
    blocks but NOT into function/class bodies (a router imported or defined
    only inside a function is not part of the module surface)."""

    def visit(body):
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            yield node
            for field in ("body", "orelse", "finalbody"):
                sub = getattr(node, field, None)
                if isinstance(sub, list):
                    yield from visit(sub)
            for handler in getattr(node, "handlers", []) or []:
                yield from visit(handler.body)

    yield from visit(tree.body)


def module_scope_assignments(tree: ast.Module) -> set:
    """Names assigned at module scope."""
    names = set()
    for node in iter_module_scope(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def check_server() -> ast.Module:
    """Check 1+2: server.py parses, builds a FastAPI app, wires auth
    middleware, and imports + includes every critical router."""
    tree = parse(BACKEND / "server.py")
    if tree is None:
        return None

    # module -> {imported_name: local_alias} — module scope ONLY, so a
    # function-local `from x import router as r` can't mask the real wiring.
    imports = {}
    for node in iter_module_scope(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            bucket = imports.setdefault(node.module, {})
            for alias in node.names:
                bucket[alias.name] = alias.asname or alias.name

    included = set()          # names passed to app.include_router(...)
    fastapi_app = False
    auth_mw_wired = False

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # app = FastAPI(...)
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "FastAPI"
                and any(isinstance(t, ast.Name) and t.id == "app" for t in node.targets)
            ):
                fastapi_app = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr == "include_router":
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        included.add(arg.id)
            elif node.func.attr == "add_middleware":
                # app.add_middleware(create_auth_middleware(enabled=...))
                for arg in node.args:
                    if (
                        isinstance(arg, ast.Call)
                        and isinstance(arg.func, ast.Name)
                        and arg.func.id == "create_auth_middleware"
                    ):
                        auth_mw_wired = True

    if not fastapi_app:
        fail("server.py: no `app = FastAPI(...)` assignment found")
    if "create_auth_middleware" not in imports.get("auth_middleware", {}):
        fail("server.py: no longer imports create_auth_middleware from auth_middleware")
    if not auth_mw_wired:
        fail("server.py: app.add_middleware(create_auth_middleware(...)) not found — default-deny auth gate unwired")

    for module, symbols in CRITICAL_ROUTERS.items():
        mod_path = BACKEND / (module.replace(".", "/") + ".py")
        mod_tree = parse(mod_path)
        defined = module_scope_assignments(mod_tree) if mod_tree else set()
        imported_here = imports.get(module, {})
        for symbol in symbols:
            if mod_tree is not None and symbol not in defined:
                fail(f"{mod_path.relative_to(REPO)}: does not define `{symbol}` at module scope")
            local = imported_here.get(symbol)
            if local is None:
                fail(f"server.py: no longer imports `{symbol}` from `{module}`")
            elif local not in included:
                fail(f"server.py: imports `{module}.{symbol}` as `{local}` but never app.include_router()s it")

    print(
        f"server.py OK: FastAPI app + auth middleware wired, "
        f"{len(CRITICAL_ROUTERS)} critical router modules verified "
        f"({sum(len(s) for s in CRITICAL_ROUTERS.values())} router symbols)."
    )
    return tree


def check_auth_allowlists() -> None:
    """Check 3: the public allowlists in auth_middleware.py stay tight."""
    auth_path = BACKEND / "auth_middleware.py"
    tree = parse(auth_path)
    if tree is None:
        return

    exact = prefixes = _MISSING
    for name in ("PUBLIC_EXACT", "PUBLIC_PREFIXES"):
        try:
            value = resolve_allowlist(auth_path, name)
        except StaticResolutionError as exc:
            fail(f"auth_middleware.py: {exc}")
            continue
        if name == "PUBLIC_EXACT":
            exact = value
        else:
            prefixes = value

    if exact is _MISSING or prefixes is _MISSING:
        return

    if not isinstance(exact, (tuple, list, set, frozenset)):
        fail(f"auth_middleware.py: PUBLIC_EXACT resolved to {type(exact).__name__}, expected a collection")
        return
    if not isinstance(prefixes, (tuple, list, set, frozenset)):
        fail(f"auth_middleware.py: PUBLIC_PREFIXES resolved to {type(prefixes).__name__}, expected a collection")
        return

    entries = [("PUBLIC_EXACT", e) for e in exact] + [("PUBLIC_PREFIXES", p) for p in prefixes]
    if not entries:
        fail("auth_middleware.py: both allowlists are empty — parsing bug or middleware rewrite; audit manually")

    compiled = [(re.compile(pat, re.IGNORECASE), reason) for pat, reason in DENY_PATTERNS]
    for source, entry in entries:
        if not isinstance(entry, str):
            fail(f"auth_middleware.py: non-string entry {entry!r} in {source}")
            continue
        if not entry.startswith("/api"):
            fail(f"auth_middleware.py: {source} entry {entry!r} is outside /api — middleware only gates /api/*")
        if source == "PUBLIC_PREFIXES" and entry.rstrip() in OVERBROAD:
            fail(f"auth_middleware.py: prefix {entry!r} would make the ENTIRE API public")
        for regex, reason in compiled:
            if regex.search(entry):
                fail(
                    f"auth_middleware.py: {source} entry {entry!r} matches denylist "
                    f"pattern `{regex.pattern}` ({reason}) — public allowlist must not expose this"
                )

    if not failures:
        print(f"auth allowlists OK: {len(exact)} exact + {len(prefixes)} prefix entries, none admin/mutation-shaped.")


# Router modules whose /admin routes are operator surfaces (model catalog, tier access, markups,
# platform-wide usage). Every such route must take Depends(require_admin_user) as its FIRST dependency:
# the auth middleware only proves "logged in", and get_user_id accepts any customer (2026-09-28 fix).
ADMIN_GATED_MODULES = {"model_access_api": 10, "model_admin_api": 7}  # module -> minimum /admin routes
ROUTE_METHODS = {"get", "post", "put", "delete", "patch"}


def check_model_admin_gates() -> None:
    """Check 4: every /admin route in ADMIN_GATED_MODULES depends first on require_admin_user."""
    for module, minimum in ADMIN_GATED_MODULES.items():
        path = BACKEND / f"{module}.py"
        tree = parse(path)
        if tree is None:
            continue
        prefix = ""
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "router" for t in node.targets)
                    and isinstance(node.value, ast.Call)):
                for kw in node.value.keywords:
                    if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                        prefix = kw.value.value
        gated = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name) and dec.func.value.id == "router"
                        and dec.func.attr in ROUTE_METHODS and dec.args and isinstance(dec.args[0], ast.Constant)):
                    continue
                full = prefix + dec.args[0].value
                if "/admin" not in full:
                    continue
                defaults = node.args.defaults + [d for d in node.args.kw_defaults if d is not None]
                depends = [d for d in defaults if isinstance(d, ast.Call) and isinstance(d.func, ast.Name)
                           and d.func.id == "Depends"]
                first = depends[0].args[0] if depends and depends[0].args else None
                if isinstance(first, ast.Name) and first.id == "require_admin_user":
                    gated += 1
                else:
                    fail(f"{path.relative_to(REPO)}:{node.lineno}: {dec.func.attr.upper()} {full} ({node.name}) must take "
                         f"Depends(require_admin_user) as its first dependency")
        if gated < minimum:
            fail(f"{path.relative_to(REPO)}: found {gated} admin-gated /admin routes, expected at least {minimum} "
                 f"(routes moved or the check went blind)")
        else:
            print(f"{module}: {gated} /admin routes, all gated by require_admin_user first.")


def main() -> int:
    check_server()
    check_auth_allowlists()
    check_model_admin_gates()

    if failures:
        print("\nBackend smoke FAILED:", file=sys.stderr)
        for f in failures:
            print(f"  FAIL: {f}", file=sys.stderr)
        print(f"\n{len(failures)} failure(s).", file=sys.stderr)
        return 1

    print("\nBackend smoke OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
