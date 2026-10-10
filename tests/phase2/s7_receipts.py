"""Test helper: genuine ``CursorCommitReceipt`` objects from a real fake-backed ``DriveCursorStore`` commit,
and a ``MembershipChecker`` bound to that store."""
from __future__ import annotations

from test_s7_gpt_fix_cursor import IDENT, make_env

from business_ai_gateway.phase2.drive_baseline import page_events
from business_ai_gateway.phase2.drive_cursor import CursorState, DriveCorpus, events_digest
from business_ai_gateway.phase2.drive_membership import Corpus, MembershipChecker

ROOT_CORPUS = DriveCorpus(None, ("R",))
OTHER_CORPUS = DriveCorpus(None, ("ROOT-1",))


class Committer:
    """A fake-backed store plus the corpus its cursor was created for."""

    def __init__(self, env, corpus: DriveCorpus) -> None:
        self.env, self.corpus = env, corpus

    @property
    def store(self):
        return self.env.store


async def committer(corpus: DriveCorpus = ROOT_CORPUS) -> Committer:
    """A fresh env whose store has an initialized (UNINITIALIZED) cursor for IDENT and ``corpus``."""
    env = await make_env()
    load = await env.store.initialize(IDENT, corpus, 0, env.lease)
    assert load.usable, load
    return Committer(env, corpus)


async def _commit(c: Committer, token: str, epoch: int, events):
    load = await c.store.load(IDENT, c.corpus, epoch, c.env.lease)
    assert load.usable, load
    new = load.record.evolve(state=CursorState.BASELINING, token=token, pos=None, seen=())
    done = await c.store.commit(IDENT, c.env.lease, load, new, list(events))
    assert done.ok, done
    return done.receipt


async def receipt(c: Committer, prior: str, token: str, *, events=(), epoch: int = 0):
    """Commit cursor ``prior`` and then ``token`` (carrying ``events``); return the second commit's receipt."""
    await _commit(c, prior, epoch, ())
    return await _commit(c, token, epoch, events)


async def page_receipt(c: Committer, prior: str, preparation, *, epoch: int = 0):
    """The receipt of a genuine commit of exactly ``preparation``'s page (its canonical events)."""
    events = page_events(IDENT, preparation.batch, prior)
    return await receipt(c, prior, preparation.batch.committable_cursor(), events=events, epoch=epoch)


def page_digest(preparation, prior: str) -> str:
    return events_digest(page_events(IDENT, preparation.batch, prior))


def checker(fake, c: Committer, epoch: int = 0, **kw) -> MembershipChecker:
    return MembershipChecker(fake, IDENT, Corpus(IDENT.namespace, ("R",), **kw), epoch, commit_store=c.store)
