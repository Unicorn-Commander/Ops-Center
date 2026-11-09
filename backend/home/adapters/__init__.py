"""One adapter per suite app. Each exposes ``async fetch(env) -> AppSnapshot``."""

from . import accounting_ops, center_deep, customer_ops, email_ops, meeting_ops, project_ops

ADAPTERS = {
    "project-ops": project_ops.fetch,
    "meeting-ops": meeting_ops.fetch,
    "email-ops": email_ops.fetch,
    "accounting-ops": accounting_ops.fetch,
    "customer-ops": customer_ops.fetch,
    "center-deep": center_deep.fetch,
}

__all__ = ["ADAPTERS"]
