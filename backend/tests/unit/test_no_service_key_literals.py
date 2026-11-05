"""
Repo guard: no service-key or known-leaked credential literals anywhere in backend/.

- Any ``sk-<name>-service-key-...`` literal fails (that guessable format was hardcoded in
  source and published; inbound keys now come from OPS_CENTER_SERVICE_KEY_HASHES).
- Any quoted literal, URL password or NAME=value whose sha256[:8] matches a credential
  known to have been committed fails. Only fingerprints are listed here, never values.

On a failure the message names file:line and the fingerprint, never the value.
"""

import hashlib
import os
import re

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# sha256[:8] of literals that were committed and must never come back.
LEAKED_FINGERPRINTS = {
    "97ebffd0": "dogfood Keycloak DB password (old keycloak_integration.py default)",
    "27b80fa2": "prod uchub DB password (old user_analytics.py default URL)",
    "ce8b97cd": "bolt-diy inbound service key",
    "132ae30c": "presenton inbound service key",
    "3f4c9173": "brigade inbound service key",
    "14d23f33": "centerdeep inbound service key",
    "d47f0f3e": "partnerpulse inbound service key",
    "099cf9d8": "open-webui inbound service key",
    "9606d952": "colonel inbound service key",
    "7bfb442b": "majiks inbound service key",
}

SERVICE_KEY_SHAPE = re.compile(r"sk-[a-z][a-z0-9-]*-service-key-")
QUOTED = re.compile(r"""["'`]([^"'`\s]{6,})["'`]""")
URL_PASSWORD = re.compile(r"[a-z][a-z0-9+.\-]*://[^:/@\s\"']*:([^@\s\"']+)@")
NAME_VALUE = re.compile(r"\b[A-Za-z_]*(?:PASS|SECRET|KEY|TOKEN|PWD)[A-Za-z_]*\b[\"']?\s*[:=]\s*[\"']?([^\"'\s,}#)]{6,})")
SKIP_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", "site-packages", ".pytest_cache",
             "reports", "htmlcov", "data", "uploads", "dist"}
TEXT_EXT = (".py", ".sql", ".sh", ".md", ".txt", ".json", ".yml", ".yaml", ".ini", ".cfg", ".toml",
            ".html", ".js", ".ts", ".conf", ".example", ".env")


def _fp(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:8]


def _files():
    for root, dirs, files in os.walk(BACKEND_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in files:
            if name.endswith(TEXT_EXT) or name.startswith(".env"):
                yield os.path.join(root, name)


def _violations():
    found = []
    for path in _files():
        try:
            with open(path, encoding="utf-8", errors="surrogateescape") as fh:
                lines = fh.read().splitlines()
        except OSError:
            continue
        rel = os.path.relpath(path, BACKEND_DIR)
        for lineno, line in enumerate(lines, 1):
            if SERVICE_KEY_SHAPE.search(line):
                found.append(f"{rel}:{lineno}: sk-<name>-service-key- literal")
                continue
            for rx in (QUOTED, URL_PASSWORD, NAME_VALUE):
                for m in rx.finditer(line):
                    fp = _fp(m.group(1))
                    if fp in LEAKED_FINGERPRINTS:
                        found.append(f"{rel}:{lineno}: literal with fp {fp} ({LEAKED_FINGERPRINTS[fp]})")
    return sorted(set(found))


def test_no_service_key_or_leaked_credential_literals_in_backend():
    violations = _violations()
    assert not violations, "credential literals found (values withheld):\n" + "\n".join(violations)


def test_guard_detects_the_patterns_it_claims_to(tmp_path, monkeypatch):
    """Self-test with synthetic values so the guard cannot silently rot."""
    import secrets

    shaped = "sk-" + "example" + "-service-key-" + secrets.token_hex(4)   # built at runtime, never a literal here
    line = f'KEY = "{shaped}"'
    assert SERVICE_KEY_SHAPE.search(line)
    probe = secrets.token_urlsafe(12)
    fp = _fp(probe)
    monkeypatch.setitem(LEAKED_FINGERPRINTS, fp, "synthetic")
    assert any(_fp(m.group(1)) == fp for m in QUOTED.finditer(f'x = "{probe}"'))
    assert any(_fp(m.group(1)) == fp for m in URL_PASSWORD.finditer(f"postgresql://u:{probe}@db:5432/x"))
    assert any(_fp(m.group(1)) == fp for m in NAME_VALUE.finditer(f"DB_PASSWORD={probe}"))
