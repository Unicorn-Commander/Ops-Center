"""Credit history must survive jsonb metadata arriving as text (asyncpg without a json codec)."""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import json
import pytest
import credit_system


def test_jsonb_dict_accepts_dict_text_bytes_and_null():
    assert credit_system._jsonb_dict({"service": "tts"}) == {"service": "tts"}
    assert credit_system._jsonb_dict('{"model": "m"}') == {"model": "m"}
    assert credit_system._jsonb_dict(b'{"a": 1}') == {"a": 1}
    assert credit_system._jsonb_dict(None) == {}
    assert credit_system._jsonb_dict("") == {}
    assert credit_system._jsonb_dict("not json") == {}
    assert credit_system._jsonb_dict("[1, 2]") == {}


@pytest.mark.asyncio
async def test_transaction_history_reads_text_metadata():
    row = {"id": "11111111-1111-4111-8111-111111111111", "user_id": "subject-a", "transaction_type": "usage",
           "amount": "-1.25", "provider": "tts", "model": "kokoro", "cost": "1.25",
           "created_at": "2026-11-07T00:00:00Z", "total_count": 1,
           "metadata": json.dumps({"service": "tts", "model": "kokoro", "cost_breakdown": {"chars": 10}})}
    conn = MagicMock(); conn.fetch = AsyncMock(return_value=[row])
    acquire = MagicMock(); acquire.__aenter__ = AsyncMock(return_value=conn); acquire.__aexit__ = AsyncMock(return_value=False)
    manager = credit_system.CreditManager(); manager.db_pool = SimpleNamespace(acquire=lambda: acquire)
    out = await manager.get_transactions("subject-a", limit=10, offset=0)
    assert out[0]["service"] == "tts" and out[0]["model"] == "kokoro" and out[0]["cost_breakdown"] == {"chars": 10}
    assert out[0]["amount"] == Decimal("-1.25") and out[0]["user_id"] == "subject-a"
    assert isinstance(out[0]["metadata"], dict)
