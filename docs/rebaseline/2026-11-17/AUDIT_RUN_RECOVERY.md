# Audit run recovery

The inventory tools use `.inventory.lock` in this folder to exclude concurrent
writers. Ordinary failures publish FAILED and release the lock. A hard process
termination can leave a stale lock; never remove it merely because it is old.

Recovery is an agent-owned local maintenance action, not a request for new
operator authorization. It never removes an inventory, branch, worktree or data.

1. Read the lock's numeric owner PID, file timestamp, size and file identity.
2. Query the process table for that exact PID and its creation time, using
   Get-Process/Get-CimInstance on Windows or a read-only process API. Do not use
   Windows os.kill(pid, 0) as a liveness probe.
3. If the PID no longer exists, the original owner is dead. If the PID exists
   but its process creation time is later than the lock file, the PID has been
   reused and the original owner is dead. A live owner, inaccessible metadata,
   malformed PID or unknown process state is not proof of staleness: retain it.
4. Before removing a proven stale lock, reread its PID, timestamp, size and file
   identity and require they match the inspected file. If they changed, restart
   inspection rather than remove a new owner's lock.
5. Remove only this proven stale `.inventory.lock` using its exact literal path.
   Leave `.tmp` files and previous evidence intact; the next successful atomic
   publication replaces only its own output filenames. Never recursively clean
   this folder to recover a run.
6. Rerun the inventory tool. Accept the new outputs only when INVENTORY_RUN says
   COMPLETE and its named file hashes match. Then run details collection, which
   verifies that source run and emits its own DETAILS_RUN status and hashes.

An IN_PROGRESS, FAILED or PARTIAL run is not complete evidence even if some old
JSON files remain readable. A hard-kill lock is a recoverable local state; it
does not justify inventing an external provider or an operator-GO blocker.
