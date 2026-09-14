"""包级 CLI 入口：`python -m scheduling_showcase demo`。"""

import sys
from typing import List, Optional

from scheduling_showcase.schedset import run_demo


def main(argv: Optional[List[str]] = None) -> int:
    """包 CLI 入口，仅支持 `demo` 子命令，无参数时打印用法并返回 2。"""
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["demo"]:
        return run_demo()
    print("用法: python -m scheduling_showcase demo", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
