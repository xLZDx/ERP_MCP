"""Test helper: a genuine ``CursorCommitReceipt`` from a real fake-backed ``DriveCursorStore`` commit."""
from __future__ import annotations

from test_s7_gpt_fix_cursor import CORPUS, IDENT, make_env

from business_ai_gateway.phase2.drive_cursor import CursorReason, CursorState


async def receipt_for_token(token: str, *, epoch: int = 0):
    """Commit ``token`` as the cursor through the store and return the receipt it issued."""
    env = await make_env()
    load = await env.store.initialize(IDENT, CORPUS, epoch, env.lease)
    assert load.usable, load
    new = load.record.evolve(state=CursorState.BASELINING, token=token, pos=None, seen=())
    done = await env.store.commit(IDENT, env.lease, load, new, [])
    assert done.ok and done.reason is not CursorReason.INVALID_REQUEST, done
    return done.receipt


async def receipt_for(preparation, *, epoch: int = 0):
    return await receipt_for_token(preparation.batch.committable_cursor(), epoch=epoch)
