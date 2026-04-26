"""DEPRECATED — re-exports from ``scripts.retain_memory``.

The script was renamed in v0.3.0 because it handles every ``kind``
(lesson / gotcha / decision / failure / fact), not just lessons. Keeping this
shim so older runbooks, hooks, and SOPS-wrapped invocations continue to work
through the deprecation window. Will be removed in v1.0.0.

Update your invocations:

    OLD: python -m scripts.retain_lesson --bank consumer-d ...
    NEW: python -m scripts.retain_memory  --bank consumer-d ...

The flag set, exit codes, and behaviour are identical — only the module path
changed.
"""
from __future__ import annotations

import sys
import warnings

# Import EVERYTHING used by callers from the new module so any
# `from scripts.retain_lesson import RetainItem` etc continues to resolve.
from scripts.retain_memory import (  # noqa: F401, E402
    ALLOWED_KINDS,
    QUEUE_FILE,
    SCRIPT_BASENAME,
    RetainItem,
    main as _main,
)


def main() -> int:
    warnings.warn(
        "scripts.retain_lesson was renamed to scripts.retain_memory in v0.3.0. "
        "Update your invocations to `python -m scripts.retain_memory ...`. "
        "The shim will be removed in v1.0.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    print(
        "⚠️ scripts.retain_lesson is deprecated; use scripts.retain_memory.",
        file=sys.stderr,
    )
    return _main()


if __name__ == "__main__":
    sys.exit(main())
