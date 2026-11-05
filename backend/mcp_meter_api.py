"""
MCP usage metering — debit the shared credit ledger for Ops MCP tool calls
===========================================================================

Customer agents call Accounting-Ops (and later other Ops apps) with a uc_ key.
Those apps resolve identity via POST /api/v1/auth/validate-key, then report
usage here so MCP traffic meters onto the SAME credit unit as LLM inference:

    1 credit = $1.00 of metered provider-equivalent cost (see CREDITS.md / 07)

Default charge is fractional (MCP_TOOL_CREDIT_USD, default $0.001 = 0.001 credits
per tool call). Collect-don't-gate: metering failures never 5xx the agent call
path when apps treat this as best-effort, but this endpoint itself returns
honest status codes so apps can choose gate vs soft-fail.

Auth: the caller's own uc_ key (Authorization: Bearer REMOVED). Requires an MCP
scope on the key (mcp:* or mcp:<app>).
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/mcp", tags=["MCP Metering"])

# Default: one-tenth of a cent per tool call in USD-credit units.
MCP_TOOL_CREDIT_USD = Decimal(os.getenv("MCP_TOOL_CREDIT_USD", "0.001"))


class McpMeterRequest(BaseModel):
    app: str = Field(..., description="Ops app slug, e.g. accounting-ops", min_length=1, max_length=64)
    tool: str = Field(..., description="MCP tool name", min_length=1, max_length=128)
    cost_usd: Optional[float] = Field(
        None,
        description="Override cost in USD (= credits). Defaults to MCP_TOOL_CREDIT_USD.",
        ge=0,
    )
    metadata: Optional[Dict[str, Any]] = None


async def _resolve_uc_key(authorization: Optional[str]) -> Dict[str, Any]:
    """Validate Bearer uc_… and return {user_id, permissions, key_id}."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer REMOVED… required")
    token = authorization[7:].strip()
    if not token.startswith("uc_"):
        raise HTTPException(status_code=401, detail="MCP metering requires a uc_ API key")

    from api_key_manager import get_api_key_manager

    try:
        manager = get_api_key_manager()
        info = await manager.validate_api_key(token)
    except Exception as exc:
        logger.error("mcp meter: validate_api_key failed: %s", exc, exc_info=True)
        raise HTTPException(status_code=401, detail="API key validation failed") from exc

    if not info:
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    perms = info.get("permissions") or []
    if isinstance(perms, str):
        import json
        try:
            perms = json.loads(perms)
        except Exception:
            perms = []
    if not isinstance(perms, list):
        perms = list(perms) if perms else []
    info["permissions"] = [str(p) for p in perms]
    return info


@router.post("/meter")
async def meter_mcp_call(
    body: McpMeterRequest,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    Debit the caller's credit ledger for one MCP tool invocation.

    Requires the presented uc_ key to hold mcp:* or mcp:<app>.
    """
    from uc_api_keys import key_has_mcp_permission

    key_info = await _resolve_uc_key(authorization)
    user_id = key_info["user_id"]
    permissions = key_info["permissions"]
    app_slug = body.app.strip().lower()

    if not key_has_mcp_permission(permissions, app=app_slug):
        raise HTTPException(
            status_code=403,
            detail=f"API key lacks MCP scope for '{app_slug}' (need mcp:* or mcp:{app_slug})",
        )

    amount = Decimal(str(body.cost_usd)) if body.cost_usd is not None else MCP_TOOL_CREDIT_USD
    if amount <= 0:
        return {
            "metered": False,
            "reason": "zero_cost",
            "user_id": user_id,
            "amount": 0.0,
        }

    credit_system = getattr(request.app.state, "credit_system", None)
    if credit_system is None:
        # Fall back to litellm credit system if present
        try:
            from litellm_api import get_credit_system
            # get_credit_system is a Depends helper; pull from app.state directly
            credit_system = getattr(request.app.state, "credit_system", None)
        except Exception:
            credit_system = None

    if credit_system is None:
        logger.warning("mcp meter: no credit_system on app.state — skipping debit")
        return {
            "metered": False,
            "reason": "credit_system_unavailable",
            "user_id": user_id,
            "amount": float(amount),
        }

    meta = {
        "app": app_slug,
        "tool": body.tool,
        "key_id": key_info.get("key_id"),
        **(body.metadata or {}),
    }

    try:
        # Prefer org pool when the integration is available (same path as LLM)
        try:
            from org_credit_integration import get_org_credit_integration
            from litellm_api import is_credit_exempt

            if await is_credit_exempt(user_id):
                return {
                    "metered": False,
                    "reason": "credit_exempt",
                    "user_id": user_id,
                    "amount": 0.0,
                }

            integ = get_org_credit_integration()
            success, used_org_id, remaining = await integ.deduct_org_credits(
                user_id=user_id,
                credits_used=float(amount),
                service=f"mcp:{app_slug}",
                model=body.tool,
                metadata=meta,
            )
            if success:
                return {
                    "metered": True,
                    "user_id": user_id,
                    "org_id": used_org_id,
                    "amount": float(amount),
                    "remaining": remaining,
                    "service": f"mcp:{app_slug}",
                    "tool": body.tool,
                }
        except Exception as org_exc:
            logger.debug("mcp meter: org deduct path unavailable (%s); trying user ledger", org_exc)

        # User-level ledger (CreditSystem.debit_credits — litellm_credit_system)
        if hasattr(credit_system, "debit_credits"):
            new_balance, tx_id = await credit_system.debit_credits(
                user_id=user_id,
                amount=float(amount),
                metadata={
                    "service": f"mcp:{app_slug}",
                    "provider": "mcp",
                    "model": body.tool,
                    **meta,
                },
            )
            return {
                "metered": True,
                "user_id": user_id,
                "amount": float(amount),
                "remaining": float(new_balance) if new_balance is not None else None,
                "transaction_id": tx_id,
                "service": f"mcp:{app_slug}",
                "tool": body.tool,
            }

        # Fallback: older credit_system.deduct_credits API
        balance = await credit_system.deduct_credits(
            user_id=user_id,
            amount=amount,
            service=f"mcp:{app_slug}",
            model=body.tool,
            metadata=meta,
        )
        remaining = balance.get("credits_remaining") or balance.get("balance")
        return {
            "metered": True,
            "user_id": user_id,
            "amount": float(amount),
            "remaining": float(remaining) if remaining is not None else None,
            "service": f"mcp:{app_slug}",
            "tool": body.tool,
        }
    except Exception as exc:
        # Surface insufficient funds; soft-fail other errors as 502 so the app
        # can choose to proceed without blocking the agent.
        name = exc.__class__.__name__
        if "Insufficient" in name or "insufficient" in str(exc).lower():
            raise HTTPException(status_code=402, detail=str(exc)) from exc
        logger.error("mcp meter: debit failed for user %s: %s", user_id, exc, exc_info=True)
        raise HTTPException(status_code=502, detail=f"Credit debit failed: {exc}") from exc
