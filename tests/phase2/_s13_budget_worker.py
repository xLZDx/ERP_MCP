"""Child-process entry point for test_s13_budget_reservation_concurrency.py (multiprocessing spawn).

Kept in its own light module (asyncpg + stdlib only) so a spawned child never imports pytest or the ledger
test fixtures. One child = one OS process = one PostgreSQL backend that calls the real
change_ledger.claim(...) entry point as the requester role inside its own explicit transaction.

Protocol on the shared result queue (all items are plain tuples):
    ("ready", idx)               connected and transaction open; about to block on the gate (if any) and claim
    ("claimed_open", idx, out)   hold mode only: claim succeeded inside a still-open transaction
    ("result", idx, out)         final outcome; out = {"ok": bool, "token_id", "generation", "err"}
Hold mode then waits for "rollback" (explicit ROLLBACK) or is killed by the parent (abrupt death).
"""
import asyncio
import sys

import asyncpg

CLAIM_SQL = "SELECT * FROM change_ledger.claim($1,$2,$3::uuid,$4,$5::uuid,$6::numeric,$7,$8)"


async def _run(spec, q, cmd):
    conn = await asyncpg.connect(spec["dsn"], database=spec["db"], timeout=60)
    out = {"ok": False, "token_id": None, "generation": None, "err": None}
    tr = conn.transaction()
    await tr.start()
    try:
        await conn.execute(f'SET LOCAL ROLE "{spec["role"]}"')
        await conn.fetchval("SELECT change_ledger.set_scope($1,$2)", spec["t"], spec["c"])
        q.put(("ready", spec["idx"]))
        if spec.get("gate") is not None:
            # blocks until the parent releases its exclusive session advisory lock: every racer then starts together
            await conn.fetchval("SELECT pg_advisory_xact_lock_shared($1)", spec["gate"])
        try:
            row = await conn.fetchrow(CLAIM_SQL, spec["t"], spec["c"], spec["change_id"], None, spec["grant_id"],
                                      spec["amount"], spec["counts_cu"], spec["counts_post"])
            out.update(ok=True, token_id=str(row["token_id"]), generation=row["generation"])
        except asyncpg.PostgresError as e:
            out["err"] = str(e).splitlines()[0]
        if spec.get("hold") and out["ok"]:
            q.put(("claimed_open", spec["idx"], dict(out)))
            # keep the transaction (and its grant row lock) open until told to roll back, or until killed
            msg = await asyncio.get_running_loop().run_in_executor(None, cmd.recv)
            if msg == "rollback":
                await tr.rollback()
                out["ok"] = False
                out["err"] = "ROLLED_BACK_BY_TEST"
                q.put(("result", spec["idx"], out))
                return
        if out["ok"]:
            await tr.commit()
        else:
            await tr.rollback()
    except BaseException:
        try:
            await tr.rollback()
        except Exception:  # noqa: BLE001 - connection may already be unusable
            pass
        raise
    finally:
        await conn.close()
    q.put(("result", spec["idx"], out))


def worker(spec, q, cmd):
    try:
        asyncio.run(_run(spec, q, cmd))
    except BaseException as e:  # noqa: BLE001 - surface the crash to the parent instead of a silent hang
        q.put(("result", spec["idx"], {"ok": False, "token_id": None, "generation": None,
                                       "err": "CHILD_CRASH: " + repr(e)}))
        sys.exit(4)
