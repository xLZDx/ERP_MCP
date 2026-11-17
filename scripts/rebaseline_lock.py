"""Cross-process lock shared by the rebaseline evidence collectors.

The guard file is permanent. The operating system releases its lock when a
process exits, including after termination, so recovery never unlinks a live
owner's replacement lock file.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path


@contextmanager
def exclusive_guard(directory: Path):
    guard_path = directory / ".inventory.guard"
    stream = guard_path.open("a+b")
    acquired = False
    try:
        stream.seek(0)
        try:
            if __import__("os").name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            raise RuntimeError("Another rebaseline collector holds the audit guard") from exc
        acquired = True
        yield
    finally:
        if acquired:
            try:
                if __import__("os").name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            finally:
                stream.close()
        else:
            stream.close()
