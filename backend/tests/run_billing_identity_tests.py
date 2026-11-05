"""Run the service-free billing lane suite, isolating legacy import-time storage.

Usage: .venv311/bin/python backend/tests/run_billing_identity_tests.py [pytest args]
"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch


def main():
    root = Path(__file__).resolve().parents[2]
    os.chdir(root)
    sys.path.insert(0, str(root / "backend"))
    original_new = Path.__new__
    with tempfile.TemporaryDirectory(prefix="ops-center-org-tests-") as directory:
        def isolated_path(cls, *args, **kwargs):
            if args == ("/app/data",):
                args = (directory,)
            return original_new(cls, *args, **kwargs)

        # org_manager creates a global singleton at import. Redirect only its
        # default data path, without modifying production code or /app/data.
        with patch.object(Path, "__new__", isolated_path):
            import org_manager  # noqa: F401

        import pytest
        return pytest.main([
            "-c", "backend/pytest.ini", "-o", "addopts=",
            "backend/tests/unit", "backend/tests/test_org_manager.py",
            *sys.argv[1:],
        ])


if __name__ == "__main__":
    raise SystemExit(main())
