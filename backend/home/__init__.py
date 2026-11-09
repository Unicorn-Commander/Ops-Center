"""Signed-in home state for Unicorn Commander (Ops-Center).

This package builds the read-only home-state document described in the User
Home design (section g): one call per person and organization that gathers live
counts from the suite apps server side, with the person's own access token, and
says plainly when a source is empty, not set up, not entitled or unavailable.

Nothing here imports ``server.py``. The router is ``backend/home_api.py``; the
package itself is plain functions and dataclasses, so the tests drive it with
recorded upstream payloads that use fictional people and hosts.
"""

SCHEMA = "uc.home.state/1"

__all__ = ["SCHEMA"]
