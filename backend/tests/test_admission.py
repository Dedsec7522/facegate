"""The inference pool's admission queue: bounded, back-pressured, nearly-finished sessions first."""
import asyncio

import pytest

from app.vision.pipeline import Admission


@pytest.mark.asyncio
async def test_full_pool_times_out_then_frees():
    adm = Admission(1)
    held = await adm.acquire()
    assert held is not None and adm.full
    assert await adm.acquire(timeout=0.05) is None      # nobody released: the caller is told "busy"
    held.release()
    held.release()                                       # releasing twice must not create a second slot
    assert not adm.full
    a = await adm.acquire(timeout=0.05)
    assert a is not None and await adm.acquire(timeout=0.01) is None


@pytest.mark.asyncio
async def test_waiters_are_served_by_priority_then_arrival():
    adm = Admission(1)
    held = await adm.acquire()
    order: list[str] = []

    async def want(name: str, priority: int) -> None:
        p = await adm.acquire(priority, timeout=2)
        order.append(name)
        await asyncio.sleep(0)
        p.release()

    tasks = [asyncio.create_task(want(n, pr)) for n, pr in (("new-1", 0), ("new-2", 0), ("nearly-done", 3))]
    await asyncio.sleep(0.01)
    held.release()
    await asyncio.gather(*tasks)
    assert order == ["nearly-done", "new-1", "new-2"]
    assert not adm.full


@pytest.mark.asyncio
async def test_cancelled_and_timed_out_waiters_do_not_leak_slots():
    adm = Admission(2)
    a, b = await adm.acquire(), await adm.acquire()
    gone = asyncio.create_task(adm.acquire(timeout=5))
    await asyncio.sleep(0.01)
    gone.cancel()
    with pytest.raises(asyncio.CancelledError):
        await gone
    for _ in range(600):                                 # many given-up waiters: the queue must not grow without bound
        assert await adm.acquire(timeout=0) is None
    assert len(adm._heap) < 600
    a.release()
    b.release()
    assert await adm.acquire(timeout=0.01) is not None and await adm.acquire(timeout=0.01) is not None
    assert adm.full
