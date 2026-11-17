"""Validate the disposable E2E credential document without displaying its values."""
from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_CREDENTIAL_FILE_BYTES = 1_048_576


def validate(path: Path) -> tuple[bool, str]:
    try:
        # Bound the actual read, not only a prior stat() that can race with replacement/growth.
        with path.open("rb") as stream:
            raw = stream.read(MAX_CREDENTIAL_FILE_BYTES + 1)
        if len(raw) > MAX_CREDENTIAL_FILE_BYTES:
            return False, "file exceeds 1 MiB"

        def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
            result: dict[str, object] = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate JSON key")
                result[key] = value
            return result

        document = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique_object,
                              parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid constant")))
    except json.JSONDecodeError as exc:
        return False, f"invalid JSON at character {exc.pos}"
    except RecursionError:
        return False, "JSON nesting is too deep"
    except ValueError:
        return False, "invalid JSON structure"
    except (OSError, UnicodeError):
        return False, "file cannot be read as UTF-8"

    if type(document) is not dict or type(document.get("users")) is not dict:
        return False, "top-level object must contain a users object"
    users = document["users"]
    if not users:
        return False, "users object must not be empty"
    for user in users.values():
        if (type(user) is not dict
                or any(type(user.get(field)) is not str or not user[field]
                       for field in ("sub", "username", "password"))):
            return False, "each user record must contain non-empty string fields"
    return True, f"valid users object ({len(users)} records)"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: validate_e2e_credentials.py <credential-file>")
        return 2
    valid, message = validate(Path(sys.argv[1]))
    print(("OK: " if valid else "INVALID: ") + message)
    return 0 if valid else 2


if __name__ == "__main__":
    raise SystemExit(main())
