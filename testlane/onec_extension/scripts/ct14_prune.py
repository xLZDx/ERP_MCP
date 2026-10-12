"""Try to remove suspicious rights from the discovered set, one at a time; keep a removal only if the whole
operation chain (new draft with marker -> post -> read movements -> unpost) still passes as CT14_NARROW.

Usage: ct14_prune.py Object:Right [Object:Right ...]     e.g. Catalog.Склады:Insert
Each test creates one new draft receipt (test data; never deleted).
"""
import gc
import json
import sys
import uuid

import ct14_iterate as it
import ct14_narrow_ops as ops

state = it.load_state()
c, pw = ops.prepare_user()
del c
gc.collect()
report = []
for arg in sys.argv[1:]:
    obj, right = arg.rsplit(":", 1)
    if right not in state.get(obj, []):
        report.append({"candidate": arg, "result": "not in state"})
        continue
    trial = {k: [r for r in v if not (k == obj and r == right)] for k, v in state.items()}
    trial = {k: v for k, v in trial.items() if v}
    it.write_rights(trial)
    it.build()
    st = ops.run_ops(None, pw, marker="CT14-PRUNE-" + uuid.uuid4().hex[:12])
    gc.collect()
    ok = bool(st.get("ok"))
    report.append({"candidate": arg, "removable": ok, "step": st.get("step"), "error": (st.get("error") or "")[:300]})
    if ok:
        state = trial
    it.save_state(state)
    print(json.dumps(report[-1], ensure_ascii=False), flush=True)
it.write_rights(state)
it.build()
print("final state written; objects:", len(state))
