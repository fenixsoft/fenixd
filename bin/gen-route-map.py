#!/usr/bin/env python3
"""gen-route-map.py — 路由地图生成器参考实现（fenixd dashboard 项目）。

add-planner-efficiency（planner-route-map）：项目声明生成器协议——
以 worktree 为 cwd、单参（worktree 根）调用，stdout 为人类可读 Markdown
（条目含 `文件:行号` 出处），非零退出/超时=失败 fail-open（planner 回退
逐轮 grep 现状）。

本实现扫描 fenixd dashboard 的三类入口：
  1. 后端 API 路由表（core/dashboard/server.py 的 _handle_api 系列方法，
     `path == "/api/..."` / `path.startswith("/api/...")` 分支）；
  2. SPA 菜单路由（core/dashboard/static/src/app.tsx 的 menuDataRender，
     `path: '/xxx'` 条目）；
  3. 关键 data-testid（static src 下的 data-testid="..." 出现点）。

内置自检（design D1）：用宽 grep 启发式统计路由候选总数，与解析产出条目数
差异 ≥30% 时在输出中追加覆盖差异 warning（防解析模式漏配——地图缺条目时
planner 依赖 prompt 措辞兜底取证）。

用法：
    python3 bin/gen-route-map.py <worktree-root>
"""

import re
import sys
from pathlib import Path


def _rel_line(path: Path, root: Path, lineno: int) -> str:
    """条目出处标注：相对 worktree 根的 `文件:行号`。"""
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    return f"{rel}:{lineno}"


def scan_server_routes(root: Path) -> list:
    """扫描 API 路由，产出 (route, source, method) 条目。

    路由已迁入 `core/dashboard/routes/` 子包（refactor-giant-classes D4），
    分两级扫描（design D4 三条 MUST ① 同文件集合）：

    1. **表驱动路由表**（主源）：`routes/base.py` 的 `_API_GET_ROUTES` /
       `_API_POST_ROUTES` / `_API_DELETE_ROUTES` 三张表驱动路由表——条目
       显式声明 (kind, pattern, handler)。按表归属方法（MUST ②：不再依赖
       回看 60 行的 `_handle_api_post`/`_handle_api_delete` 启发式，方法
       归属由表名显式决定）；pattern 为精确串/regex 原样收录（regex 条目
       以 `^...$` 形态收 '^/api/xxx' 前缀，供 planner 参考）。
    2. **文本扫描**（兼容 fallback）：对 `routes/*.py` 全文件集合与
       `server.py` 扫描 `path == "/api/..."` 字面量（旧生成器伪造测试
       消费 server.py 文本）。此级不再做方法归属启发式——旧测试仅断言
       条目存在性与出处 `文件:行号`，不依赖 POST/DELETE 判定。

    新生成的 map 条目数 ≥ 收敛前 → 本仓覆盖回归断言（task 4.6）校验
    条目数不减少。
    """
    entries: list = []
    # ── 1) 表驱动路由表（主源，方法显式归属） ────────────────────────────
    routes_base = root / "core" / "dashboard" / "routes" / "base.py"
    if routes_base.is_file():
        text = routes_base.read_text(encoding="utf-8")
        table_entries = []
        for table_name, method in (
            ("_API_GET_ROUTES", "GET"),
            ("_API_POST_ROUTES", "POST"),
            ("_API_DELETE_ROUTES", "DELETE"),
        ):
            for line_idx, line in enumerate(
                routes_base.read_text(encoding="utf-8").splitlines(), start=1
            ):
                m = re.search(
                    r'\(\s*"(exact|regex|suffix)",\s*"([^"]+)"', line
                )
                if not m:
                    continue
                # 需要确定该行属于哪张表（以 "_API_GET_ROUTES = [" 等为界）
                pass
        # 简化：按表边界切分文本后逐表匹配
        marker = re.compile(r"_API_(GET|POST|DELETE)_ROUTES = \[")
        current_table = None
        table_start_line = 0
        for line_idx, line in enumerate(
            routes_base.read_text(encoding="utf-8").splitlines(), start=1
        ):
            m = marker.search(line)
            if m:
                current_table = m.group(1)
                table_start_line = line_idx
                continue
            if current_table is None:
                continue
            # 表结束：遇到下一个表或非缩进条目
            if line.startswith("]") and current_table:
                current_table = None
                continue
            if not line.strip().startswith("("):
                continue
            rm = re.search(r'\(\s*"(exact|regex|suffix)",\s*"([^"]+)"', line)
            if not rm:
                continue
            pattern = rm.group(2)
            if pattern.startswith("^/"):
                # regex 条目：展示 pattern 的 /api/... 前缀
                display = pattern[: pattern.find("$")] if "$" in pattern else pattern
                display = display.lstrip("^")
            else:
                display = pattern
            entries.append(
                (display, _rel_line(routes_base, root, line_idx), current_table)
            )
    # ── 2) 文本扫描 fallback（routes/ 子包全文件 + server.py） ──────────
    api_pat = re.compile(r'path\s*(?:==|startswith|endswith)\s*\(?\s*"([^"]+)"\s*\)?')
    scan_files = []
    routes_dir = root / "core" / "dashboard" / "routes"
    if routes_dir.is_dir():
        scan_files.extend(sorted(routes_dir.glob("*.py")))
    server = root / "core" / "dashboard" / "server.py"
    if server.is_file():
        scan_files.append(server)
    for f in scan_files:
        lines = f.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines, start=1):
            stripped = line.strip()
            m = api_pat.search(stripped)
            if not m:
                continue
            route = m.group(1)
            if not route.startswith("/"):
                continue
            entries.append((route, _rel_line(f, root, i), "GET"))
    return entries


def scan_spa_routes(root: Path) -> list:
    """扫描 SPA 菜单路由（app.tsx menuDataRender 的 `path: '/xxx'` 条目）。

    静态前端页面入口：/overview、/projects、/settings、/activities、/help
    及动态项目详情 `/projects/<name>`。
    """
    app = root / "core" / "dashboard" / "static" / "src" / "app.tsx"
    entries: list = []
    if not app.is_file():
        return entries
    lines = app.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines, start=1):
        m = re.search(r"path:\s*['\"]([^'\"]+)['\"]", line)
        if not m:
            continue
        route = m.group(1)
        if route.startswith("/") and "/" not in route[1:]:
            # 一级菜单路由（/overview /projects /settings /activities /help）
            entries.append((route, _rel_line(app, root, i), "SPA"))
        elif route.startswith("/") and len(route) > 1:
            # 动态/嵌套菜单路由（/projects/<name>）
            entries.append((route, _rel_line(app, root, i), "SPA"))
    return entries


def scan_testids(root: Path) -> list:
    """扫描关键 data-testid（static src 下出现点，取首个出现位置）。

    这是页面可交互锚点索引（planner 断言定位常用），覆盖新增页面/组件时
    未进菜单路由的深层交互入口。
    """
    static_root = root / "core" / "dashboard" / "static" / "src"
    entries: list = []
    if not static_root.is_dir():
        return entries
    seen: set = set()
    for path in sorted(static_root.rglob("*.tsx")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for i, line in enumerate(lines, start=1):
            for tid in re.findall(r'data-testid=["\']([^"\']+)["\']', line):
                if tid in seen:
                    continue
                seen.add(tid)
                entries.append((f"data-testid={tid}", _rel_line(path, root, i), "testid"))
    return entries


def self_check(root: Path, parsed_count: int, warning_buf: list) -> None:
    """宽 grep 启发式自检：候选总数 vs 解析条目数，差 ≥30% 输出 warning。

    启发式口径（宽松上界）：
      - server.py 中唯一 `/api/...` 字符串字面量数（`"/api/xxx"`，去重）；
      - static src 下唯一 `data-testid="..."` 数；
      - app.tsx 中唯一 `path: '/xxx'` 菜单路由数。
    解析条目数远低于启发式说明解析模式漏配——地图缺条目时 planner 依赖
    措辞兜底，但框架应有感知。
    """
    heuristic = 0
    subprocess_mod = __import__("subprocess")
    # MUST ③：自检 grep 源与扫描源同文件集合（routes/ 子包 + server.py）。
    grep_targets = [str(root / "core" / "dashboard" / "routes")]
    server_py = root / "core" / "dashboard" / "server.py"
    if server_py.is_file():
        grep_targets.append(str(server_py))
    try:
        res = subprocess_mod.run(
            ["grep", "-oEh", r'"/api/[^"]+"'] + grep_targets,
            capture_output=True,
            text=True,
            timeout=30,
        )
        heuristic += len({ln.strip() for ln in res.stdout.splitlines() if ln.strip()})
    except Exception:
        pass
    try:
        res = subprocess_mod.run(
            [
                "grep",
                "-roEh",
                r'data-testid="[^"]+"',
                str(root / "core" / "dashboard" / "static" / "src"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        heuristic += len({ln.strip() for ln in res.stdout.splitlines() if ln.strip()})
    except Exception:
        pass
    try:
        res = subprocess_mod.run(
            [
                "grep",
                "-oEh",
                r"path: *'/[^']*'",
                str(root / "core" / "dashboard" / "static" / "src" / "app.tsx"),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        heuristic += len({ln.strip() for ln in res.stdout.splitlines() if ln.strip()})
    except Exception:
        pass
    if parsed_count == 0:
        if heuristic > 0:
            warning_buf.append(
                f"> ⚠️ 覆盖自检：启发式候选 {heuristic} 条而解析产出 0 条"
                f"（差异 ≥30%）——解析模式疑似漏配，地图可能缺条目\n"
            )
        return
    diff_ratio = (heuristic - parsed_count) / parsed_count
    if diff_ratio >= 0.30:
        warning_buf.append(
            f"> ⚠️ 覆盖自检：启发式候选 {heuristic} 条 vs 解析产出 {parsed_count} 条"
            f"（差异 {diff_ratio * 100:.0f}% ≥30%）——解析模式可能漏配，"
            f"spec 涉及但地图未覆盖的入口 planner 仍须自行取证\n"
        )


def main() -> int:
    if len(sys.argv) < 2:
        print("用法: gen-route-map.py <worktree-root>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        print(f"worktree 根不存在: {root}", file=sys.stderr)
        return 1

    entries: list = []
    entries.extend(scan_server_routes(root))
    entries.extend(scan_spa_routes(root))
    entries.extend(scan_testids(root))
    # 去重（同 route 多出处取首个），保持 server → SPA → testid 顺序
    seen: set = set()
    deduped: list = []
    for route, src, method in entries:
        if route in seen:
            continue
        seen.add(route)
        deduped.append((route, src, method))

    warning_buf: list = []
    self_check(root, len(deduped), warning_buf)

    out = [
        "# 路由地图（dashboard 项目已知入口索引）\n",
        f"生成：{Path(__file__).name}；条目数 {len(deduped)}。\n",
    ]
    if warning_buf:
        out.append("\n" + "".join(warning_buf))
    out.append("\n## API 路由\n")
    api_entries = [e for e in deduped if e[2] in ("GET", "POST", "DELETE")]
    for route, src, method in api_entries:
        out.append(f"- `{route}` [{method}] ({src})\n")
    out.append("\n## SPA 页面\n")
    for route, src, _ in [e for e in deduped if e[2] == "SPA"]:
        out.append(f"- `{route}` ({src})\n")
    out.append("\n## 关键 data-testid\n")
    for route, src, _ in [e for e in deduped if e[2] == "testid"]:
        out.append(f"- `{route}` ({src})\n")
    out.append("\n> 已知入口索引、非穷尽清单；spec 涉及但地图未覆盖的入口仍须自行源码取证。\n")
    sys.stdout.write("".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
