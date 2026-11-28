#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面调试会话地址生成（fenix-ui-debug · dashboard 承载）。

不独立启动 HTTP 服务器：目标页反向代理（GET /uidebug/<project>/<session>/~/<path>）、
批注器资产（GET /uidebug-assets/annotator.js）与批注落盘
（POST /api/uidebug/<project>/<session>/feedback）均由 fenix dashboard
常驻进程承载。本脚本把「任意 http(s) URL」注册为项目下的调试会话
（写 ``<project>/.fenix/ui-debug/<session>/session.json``），探测存活
dashboard、验证 wrapper 与代理入口可达，输出客户端可直接打开的地址。

不自行拉起 dashboard（拉起/巡检职责归 fenix-dashboard skill）；未存活时
输出结构化错误与拉起指引。

用法::

    python3 uidebug_serve.py --project <项目根目录> --url <目标页 URL>
                             [--session 名字] [--dashboard-port N]
                             [--round N] [--pretty]

会话名缺省由 target host:port slug 化（``localhost-3000`` 形态）；同名
会话重跑直接覆盖 session.json（重指 target 是传入新 URL 的正常路径）。

端口候选链（逐个探测，首个存活且已注册目标项目的实例生效；全部存活
实例都未注册目标项目才判未注册）：
``--dashboard-port`` > ``~/.config/fenixd/dashboard.yaml`` 顶层 ``port:``
（regex 解析，不引入 YAML 依赖）> 8787 默认。

退出码：0 = ok（``url`` 字段可直接交用户打开）；2 = 输入错误（项目根不
存在 / URL 非法或非 http(s) / session 名非法）；3 = dashboard 不存活
（含探活通过但验证阶段失联的 ``dashboard-lost-after-probe`` 形态）；
4 = 项目未注册（hint 指引 ``--add-project``；仅当全部存活候选实例都
未注册目标项目才判 4）；5 = uidebug wrapper 验证失败（dashboard 存活
但 /uidebug/ 路由返回 4xx/5xx——dashboard 版本过旧）；6 = 目标页不可达
（代理返回 502 或上游回答非 200——target 地址/端口/路径不对）；1 = 工具
自身未捕获异常（崩溃路径向 stderr 输出 ``ok: false`` JSON，不占用上方
语义）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

# Windows 控制台编码兜底（fenix-init 同款）：SSH 会话/旧式控制台下 stdout
# 默认回落本地 ANSI 代码页（cp1252/cp936），中文报告 print/write 直接
# UnicodeEncodeError 崩溃。保编码不换，仅把不可编码字符替换掉。
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

# 框架目录自举：本脚本位于 <仓库根>/skills/fenix-ui-debug/scripts/ 下，
# 仓库根即框架主树（bin/fenix_dashboard.py 同树；第三方项目经 .fenix 软链
# 自举时仓库根下是 .fenix/bin/fenix_dashboard.py）
REPO_ROOT = Path(__file__).resolve().parents[3]
# 单源复用框架内的会话落盘/校验逻辑（normalize/write/load 全在
# core.dashboard.uidebug_io；skill 脚本不内联复制校验规则）
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_PORT = 8787
PROBE_TIMEOUT = 2.0        # /api/projects 探测窗口
VERIFY_TIMEOUT = 5.0       # wrapper / 代理入口可达性验证窗口


def _dashboard_py() -> Path | None:
    """框架 dashboard 入口脚本：优先主树 bin/，退回 .fenix/bin 自举软链。"""
    for cand in (REPO_ROOT / "bin" / "fenix_dashboard.py",
                 REPO_ROOT / ".fenix" / "bin" / "fenix_dashboard.py"):
        if cand.is_file():
            return cand
    return None


def parse_yaml_port(text: str) -> int | None:
    """从 dashboard.yaml 文本解析顶层 ``port:``（无缩进、跳过注释行）。

    只认顶层键（缩进行是 projects 等子键下的内容，不误吞）；解析失败或
    越界返回 None，调用方落回默认端口。
    """
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace():
            continue  # 缩进行：非顶层键
        m = re.match(r"^port:\s*(\d{1,5})\s*(?:#.*)?$", line.strip())
        if m:
            port = int(m.group(1))
            return port if 1 <= port <= 65535 else None
    return None


def config_port_candidates(explicit: int | None, config_path: Path) -> list[int]:
    """端口候选链：显式 > 用户配置 > 默认；去重保序。"""
    ports: list[int] = []
    if explicit:
        ports.append(explicit)
    try:
        from_yaml = parse_yaml_port(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError：坏编码（GBK 等）触发 UnicodeDecodeError，按解析失败
        # 同口径静默落回默认端口，不升级为工具崩溃
        from_yaml = None
    if from_yaml:
        ports.append(from_yaml)
    ports.append(DEFAULT_PORT)
    return list(dict.fromkeys(ports))


def fetch_status(url: str, timeout: float) -> int | None:
    """GET 取最终状态码（urllib 自动跟随重定向；代理侧 30x 的 Location
    已被 rebase 回 dashboard 同源，因此跟随仍落在代理通道内）。传输层
    失败（DNS/拒绝/超时）返回 None。"""
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
            return resp.status
    except urllib.error.HTTPError as exc:
        # HTTPError（4xx/5xx）：状态码可知（HTTPError 是 URLError 子类，
        # 须先于 URLError 捕获）
        return exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None


def probe_dashboard(port: int) -> dict | None:
    """探测 <port> 上是否存活 fenix dashboard：/api/projects 返回 200 且
    JSON 含 projects 列表（与 fenix-dashboard skill 的存活判定同口径）。"""
    req = urllib.request.Request(f"http://127.0.0.1:{port}/api/projects",
                                 headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=PROBE_TIMEOUT) as resp:
            status = resp.status
            body = resp.read()
    except (urllib.error.URLError, OSError):
        return None
    try:
        payload = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if status == 200 and isinstance(payload, dict) \
            and isinstance(payload.get("projects"), list):
        return payload
    return None


def match_registered_project(projects: list, root: Path) -> str | None:
    """在 /api/projects 结果里按项目根路径（realpath 口径）匹配注册名。"""
    real = os.path.realpath(str(root))
    for entry in projects:
        if not isinstance(entry, dict):
            continue
        path = entry.get("path")
        # path 缺失/为空/非字符串时直接跳过：realpath("") 会退化为当前
        # 工作目录且不抛异常，调用方以 ``--project .`` 出题时该条目会被
        # 误判命中并生成指向错误注册名的会话 URL
        if not isinstance(path, str) or not path.strip():
            continue
        try:
            entry_real = os.path.realpath(os.path.expanduser(path))
        except (OSError, ValueError):
            continue
        if entry_real == real:
            name = entry.get("name")
            return str(name) if name else None
    return None


def slug_session(netloc: str) -> str:
    """由 target host:port slug 化缺省会话名：非 [A-Za-z0-9._-] 一律折叠
    为「-」（host 里不会出现「..」，产物恒过 session 段校验）。"""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", netloc.strip().lower())
    return slug.strip("-") or "debug"


def build_urls(port: int, project: str, session: str, entry: str,
               round_: int, entry_query: str = "") -> tuple[str, str]:
    """拼 wrapper 与代理入口地址（段逐个 percent 编码，query 串不动；
    中文注册名原样内插会让 http.client 编码请求行时抛 UnicodeEncodeError，
    与 proto_serve.build_url 同款纪律）。入口 query（token URL 等鉴权
    参数）随 wrapper 的 proto_round 一并挂上。"""
    project_seg = urllib.parse.quote(project, safe="")
    session_seg = urllib.parse.quote(session, safe="")
    entry_seg = urllib.parse.quote(entry, safe="/") if entry else ""
    wrapper = f"http://127.0.0.1:{port}/uidebug/{project_seg}/{session_seg}"
    if entry_query:
        wrapper += "?" + entry_query + f"&proto_round={round_}"
    else:
        wrapper += f"?proto_round={round_}"
    proxy = f"http://127.0.0.1:{port}/uidebug/{project_seg}/{session_seg}/~/"
    if entry_seg:
        proxy += entry_seg
    if entry_query:
        proxy += "?" + entry_query
    return wrapper, proxy


def _emit(payload: dict, pretty: bool) -> None:
    print(json.dumps(payload, ensure_ascii=False,
                     indent=2 if pretty else None))


def _fail(code: int, error: str, message: str, hint: str | None = None,
         pretty: bool = False, extra: dict | None = None) -> int:
    payload: dict = {"ok": False, "error": error, "message": message}
    if hint:
        payload["hint"] = hint
    if extra:
        payload.update(extra)
    _emit(payload, pretty)
    return code


def _quote_cmd_path(p) -> str:
    """hint 命令行路径引用：POSIX 用 shlex.quote，Windows cmd.exe 不认单
    引号退回双引号（Windows 路径不含双引号字符）。"""
    import shlex
    return '"%s"' % p if sys.platform == "win32" else shlex.quote(str(p))


def _launch_hint() -> str:
    dashboard_py = _dashboard_py()
    lines = []
    if dashboard_py:
        lines.append(
            f"python3 {_quote_cmd_path(dashboard_py)} --serve  # 前台手工实例")
    lines.append("sudo systemctl start fenix-dashboard  # systemd 承载")
    return "；或 ".join(lines)


def main(argv: list[str] | None = None) -> int:
    # 框架包导入放 main 内：任何导入失败落 __main__ 崩溃兜底（退出码 1），
    # 不产生 traceback
    from core.dashboard import uidebug_io

    parser = argparse.ArgumentParser(
        description="把任意 http(s) URL 注册为 fenix dashboard 批注框架的"
                    "界面调试会话（不独立起服）")
    parser.add_argument("--project", required=True,
                        help="fenixd 项目根目录（须已在 dashboard 注册）")
    parser.add_argument("--url", required=True,
                        help="要接入批注框架的目标页 URL（末段视为入口文档）")
    parser.add_argument("--session", default=None,
                        help="会话名（缺省由 target host:port slug 化）")
    parser.add_argument("--dashboard-port", type=int, default=None,
                        help="dashboard 端口（缺省走配置与默认端口探测）")
    parser.add_argument("--round", type=int, default=1,
                        help="迭代轮次（写入 URL proto_round 参数，默认 1）")
    parser.add_argument("--pretty", action="store_true", help="JSON 缩进输出")
    parser.add_argument("--json", action="store_true",
                        help="本脚本输出恒为 JSON，此开关无副作用")
    args = parser.parse_args(argv)

    root = Path(args.project).expanduser()
    if not root.is_dir():
        return _fail(2, "project-root-missing",
                     f"项目根不存在或不是目录：{root}", pretty=args.pretty)

    split = uidebug_io.split_target_url(args.url)
    if split is None:
        return _fail(2, "invalid-url",
                     f"目标 URL 非法或非 http(s)：{args.url!r}",
                     hint="须为 http:// 或 https:// 且含 host；末段按入口"
                          "文档拆分（例：http://127.0.0.1:3000/app/page2 → "
                          "target http://127.0.0.1:3000/app + 入口 page2）",
                     pretty=args.pretty)
    target, entry, entry_query = split

    session = args.session or slug_session(
        urllib.parse.urlsplit(target).netloc)
    if not uidebug_io.session_segment_safe(session):
        return _fail(2, "invalid-session",
                     f"会话名非法（须为单段路径、无「.」「..」组件）："
                     f"{session!r}", pretty=args.pretty)

    # 先落盘再验证：路由与验证都依赖 session.json 已存在；同名会话重跑
    # 直接覆盖（重指 target 是传入新 URL 的正常路径）
    session_file = uidebug_io.write_session(root, session, target, entry,
                                            entry_query)

    config_path = Path.home() / ".config" / "fenixd" / "dashboard.yaml"
    tried: list[int] = []
    alive_ports: list[int] = []
    wrapper_failures: list[tuple[int, int, str]] = []
    for port in config_port_candidates(args.dashboard_port, config_path):
        tried.append(port)
        payload = probe_dashboard(port)
        if payload is None:
            continue
        alive_ports.append(port)
        name = match_registered_project(payload["projects"], root)
        if name is None:
            # 存活但未注册目标项目：不立即判 4，继续探后续候选端口——
            # 多实例环境下目标项目可能注册在靠后的实例上
            continue
        wrapper_url, proxy_url = build_urls(port, name, session, entry,
                                            args.round, entry_query)
        # 端到端验证 ① wrapper 页 200（dashboard 侧路由健康）；② 代理入口
        # 200（会话解析 + 上游 target 全链路可达）。传输层失联重试一次再
        # 定性，避免瞬时抖动误报。
        wrapper_page = wrapper_url.split("?", 1)[0]
        status = fetch_status(wrapper_page, VERIFY_TIMEOUT)
        if status is None:
            status = fetch_status(wrapper_page, VERIFY_TIMEOUT)
        if status is None:
            return _fail(3, "dashboard-lost-after-probe",
                         f"dashboard 探活通过但验证阶段失联（端口 {port}）："
                         f"{wrapper_url}",
                         hint="dashboard 可能在探活与验证间隙退出或连接瞬时"
                              "失败，请重试或检查 dashboard 进程状态",
                         pretty=args.pretty)
        if status != 200:
            # wrapper 非 200（dashboard 版本过旧无 /uidebug/ 路由等）：
            # 与未注册分支同型继续探后续候选端口，全部候选失败后按首个
            # 失败原因落退出码 5
            wrapper_failures.append((port, status, wrapper_url))
            continue
        # 代理入口：502=代理明确报告上游不可达；其余非 200=上游回答异常
        # （target base 路径不对等）
        up_status = fetch_status(proxy_url, VERIFY_TIMEOUT)
        if up_status is None:
            up_status = fetch_status(proxy_url, VERIFY_TIMEOUT)
        if up_status == 502:
            return _fail(6, "target-unreachable",
                         f"目标页不可达（代理返回 502）：{target}",
                         hint="确认 target 地址/端口可从本机访问（curl "
                              f"{target} 自检）；会话文件已写入 "
                              f"{session_file}，target 恢复后重跑本脚本即可",
                         pretty=args.pretty)
        if up_status is None:
            return _fail(6, "target-unreachable",
                         f"目标页验证传输层失联：{target}",
                         hint=f"curl {target} 自检网络连通性；会话文件已"
                              f"写入 {session_file}",
                         pretty=args.pretty)
        if up_status != 200:
            return _fail(6, "target-unhealthy",
                         f"目标页回答 HTTP {up_status}（预期 200）：{proxy_url}"
                         f" → {target}",
                         hint="核对 target base 路径与入口文档是否存在；会"
                              f"话文件已写入 {session_file}",
                         pretty=args.pretty)
        _emit({"ok": True, "url": wrapper_url, "proxy_url": proxy_url,
               "dashboard": f"http://127.0.0.1:{port}", "port": port,
               "project": name, "session": session, "target": target,
               "entry": entry, "entry_query": entry_query,
               "session_file": str(session_file),
               "round": args.round}, args.pretty)
        return 0
    if wrapper_failures:
        port, status, url = wrapper_failures[0]
        return _fail(5, "uidebug-url-unreachable",
                     f"dashboard 存活但 uidebug wrapper 验证失败（HTTP "
                     f"{status}）：{url}",
                     hint="确认 dashboard 已升级到含 /uidebug/ 路由的版本；"
                          "多实例环境下可核对各存活实例的 dashboard 版本",
                     pretty=args.pretty)
    if alive_ports:
        add_py = _dashboard_py()
        quoted_root = _quote_cmd_path(root)
        add_hint = (f"python3 {_quote_cmd_path(add_py)} "
                    f"--add-project {quoted_root}"
                    if add_py else
                    f"用框架 bin/fenix_dashboard.py --add-project {quoted_root} 注册")
        return _fail(4, "project-not-registered",
                     f"dashboard 存活（端口：{alive_ports}）但项目未注册："
                     f"{root}",
                     hint=add_hint,
                     pretty=args.pretty)
    return _fail(3, "dashboard-not-alive",
                 f"dashboard 不存活（探测端口：{tried}）",
                 hint=_launch_hint(),
                 pretty=args.pretty)


if __name__ == "__main__":
    # 崩溃兜底：输出 JSON 由生成管线消费，未预期异常不得退化为 traceback +
    # 未文档化退出码。退出码 1 未被上方 0/2/3/4/5/6 占用，专留工具自身
    # 异常（向 stderr 输出 ok:false JSON）；argparse 的用法错误走
    # SystemExit(2)，不落入本兜底。
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False,
                          "error": f"工具自身异常：{type(exc).__name__}: {exc}"},
                         ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
