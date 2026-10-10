"""Test helper: genuine ``CursorCommitReceipt`` objects from a real fake-backed ``DriveCursorStore`` commit,
and a ``MembershipChecker`` bound to that store."""
from __future__ import annotations

from test_s7_gpt_fix_cursor import CORPUS, IDENT, make_env

from business_ai_gateway.phase2.drive_cursor import CursorState
from business_ai_gateway.phase2.drive_membership import Corpus, MembershipChecker


async def committer():
    """A fresh env whose store has an initialized (UNINITIALIZED) cursor for IDENT."""
    env = await make_env()
    load = await env.store.initialize(IDENT, CORPUS, 0, env.lease)
    assert load.usable, load
    return env


async def _commit(env, token: str, epoch: int):
    load = await env.store.load(IDENT, CORPUS, epoch, env.lease)
    assert load.usable, load
    state = CursorState.BASELINING
    new = load.record.evolve(state=state, token=token, pos=None, seen=())
    done = await env.store.commit(IDENT, env.lease, load, new, [])
    assert done.ok, done
    return done.receipt


async def receipt(env, prior: str, token: str, *, epoch: int = 0):
    """Commit cursor ``prior`` and then ``token`` through the store; return the receipt of the second commit."""
    await _commit(env, prior, epoch)
    return await _commit(env, token, epoch)


def checker(fake, env, epoch: int = 0, **kw) -> MembershipChecker:
    return MembershipChecker(fake, IDENT, Corpus(IDENT.namespace, ("R",), **kw), epoch, commit_store=env.store)
