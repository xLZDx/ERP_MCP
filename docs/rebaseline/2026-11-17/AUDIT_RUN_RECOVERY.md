# Audit run locking and recovery

Both public collector CLIs acquire the same permanent `.inventory.guard` using a nonblocking operating-system lock before touching run manifests or output files. Windows uses a byte-range lock; POSIX uses flock. The lock handle is held for the whole run. The guard file must never be deleted or replaced: concurrent processes must always lock the same file object.

A competing invocation fails without modifying evidence. The `.inventory.lock` file is only an informational run marker, not the exclusion primitive. A successful guard owner may overwrite a marker left by a dead process. Ordinary completion removes the marker while still holding the guard. A hard process termination automatically releases the kernel lock, so rerun the tool normally; do not manually delete stale files and do not ask for a new operator GO.

Manifest status and hashes describe a particular run, not an assertion that no newer run has started. Consumers must use the guarded CLI, or hold the same guard while reading/validating the complete manifest set. Internal collect() helpers assume that their caller already holds the guard; they are not independent consumer entrypoints. Never infer current validity from a raw COMPLETE string while an uncoordinated writer can run.

An accepted evidence set requires a COMPLETE source manifest, matching run ID and baseline, and all named file hashes. The details CLI acquires the same guard before validating the source manifest. PARTIAL exits2, COMPLETE exits0, exceptions publish FAILED and propagate. Earlier complete output can remain after a process dies before invalidation; it remains the prior dated snapshot and is not proof that the interrupted new attempt completed. Rerun under the guard for fresh evidence.

This supersedes the earlier PID/time/identity-check-then-unlink procedure, whose concurrent recovery race was found in final reliability review. No branch, worktree, application data or inventory output is removed by this recovery protocol.
