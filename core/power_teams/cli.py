from __future__ import annotations

import sys

from power_teams.runtime.opencode_supervisor import main as supervisor_main


def main(argv=None) -> int:
    return supervisor_main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())
