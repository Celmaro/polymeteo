"""Tests for emergency shutdown honesty and resilience."""

import logging

import pytest

from weather_copy_bot.live.emergency_shutdown import (
    EmergencyShutdown,
    ShutdownReason,
)


class FlakyExecutor:
    """Executor stub whose close_position can fail per position."""

    def __init__(self, fail_ids: set[str]):
        self.fail_ids = fail_ids
        self.closed: list[str] = []

    async def close_position(self, position_id: str):
        if position_id in self.fail_ids:
            raise RuntimeError(f"CLOB unreachable for {position_id}")
        self.closed.append(position_id)


def _positions_fn(positions):
    async def fn():
        return positions

    return fn


@pytest.mark.asyncio
async def test_close_failure_does_not_abort_remaining_positions():
    shutdown = EmergencyShutdown()
    executor = FlakyExecutor(fail_ids={"p1"})
    positions = [{"position_id": "p1"}, {"position_id": "p2"}, {"position_id": "p3"}]
    shutdown.set_dependencies(
        order_queue=None,
        executor=executor,
        notifier=None,
        get_balance_fn=None,
        get_positions_fn=_positions_fn(positions),
    )

    event = await shutdown.emergency_stop(reason=ShutdownReason.MANUAL, details="test")

    assert event.positions_closed == 2
    assert sorted(executor.closed) == ["p2", "p3"]
    assert "p1" in event.details


@pytest.mark.asyncio
async def test_balance_fetch_failure_is_reported(caplog):
    shutdown = EmergencyShutdown()

    async def broken_balance():
        raise RuntimeError("rpc down")

    shutdown.set_dependencies(
        order_queue=None,
        executor=None,
        notifier=None,
        get_balance_fn=broken_balance,
        get_positions_fn=None,
    )

    with caplog.at_level(logging.WARNING):
        event = await shutdown.emergency_stop(reason=ShutdownReason.MANUAL, details="x")

    assert event.balance_at_shutdown == 0.0
    assert any("balance" in rec.message.lower() for rec in caplog.records)
