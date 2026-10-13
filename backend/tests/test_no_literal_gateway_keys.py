"""Repository guard for hard-coded LiteLLM gateway credentials.

The two listed test modules contain intentionally fake provider-key fixtures and
are excluded from this source scan. Built legacy bundles under ``public_old``
are generated fixtures and are also out of scope for the Python-source guard.
"""

import ast
import hashlib
import re
from pathlib import Path


BACKEND = Path(__file__).resolve().parents[1]
FINGERPRINT = "d50586f2"
KEY_VALUE = re.compile(r"^sk-[A-Za-z0-9_-]{24,}$")
QUOTED_KEY = re.compile(r'''(["'])sk-[A-Za-z0-9_-]{24,}\1''')
EXCLUDED_TEST_FIXTURES = {
    BACKEND / "tests" / "test_byok.py",
    BACKEND / "tests" / "test_service_auth_image_generation.py",
}


def _source_files():
    for path in sorted(BACKEND.rglob("*.py")):
        if "public_old" in path.relative_to(BACKEND).parts:
            continue
        if path in EXCLUDED_TEST_FIXTURES:
            continue
        yield path


def _is_environment_lookup(node):
    function = node.func
    if not isinstance(function, ast.Attribute):
        return False
    if function.attr == "getenv":
        return (
            isinstance(function.value, ast.Name)
            and function.value.id == "os"
        )
    if function.attr != "get":
        return False
    if isinstance(function.value, ast.Name):
        return function.value.id == "environ"
    return (
        isinstance(function.value, ast.Attribute)
        and function.value.attr == "environ"
        and isinstance(function.value.value, ast.Name)
        and function.value.value.id == "os"
    )


def _default_key_hits(path, source):
    tree = ast.parse(source, filename=str(path))
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not _is_environment_lookup(node):
            continue
        defaults = list(node.args[1:2])
        defaults.extend(keyword.value for keyword in node.keywords if keyword.arg == "default")
        for default in defaults:
            if isinstance(default, ast.Constant) and isinstance(default.value, str):
                if KEY_VALUE.fullmatch(default.value):
                    fingerprint = hashlib.sha256(default.value.encode()).hexdigest()[:8]
                    hits.append((path, node.lineno, fingerprint))
    return hits


def _fingerprint_hits(path, source):
    if "tests" in path.relative_to(BACKEND).parts:
        return []
    hits = []
    for match in QUOTED_KEY.finditer(source):
        value = match.group(0)[1:-1]
        fingerprint = hashlib.sha256(value.encode()).hexdigest()[:8]
        if fingerprint == FINGERPRINT:
            line = source.count("\n", 0, match.start()) + 1
            hits.append((path, line, fingerprint))
    return hits


def test_backend_has_no_literal_gateway_key_defaults_or_blocked_fingerprint():
    default_hits = []
    fingerprint_hits = []
    for path in _source_files():
        source = path.read_text(encoding="utf-8")
        default_hits.extend(_default_key_hits(path, source))
        fingerprint_hits.extend(_fingerprint_hits(path, source))

    assert not default_hits, "literal gateway-key defaults found: " + ", ".join(
        f"{path}:{line} (fingerprint {fingerprint})"
        for path, line, fingerprint in default_hits
    )
    assert not fingerprint_hits, "blocked gateway-key fingerprint found: " + ", ".join(
        f"{path}:{line} (fingerprint {fingerprint})"
        for path, line, fingerprint in fingerprint_hits
    )
