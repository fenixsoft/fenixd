#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原型伺服地址生成（fenix-prototype · dashboard 承载，add-proto-dashboard-serving）。

不独立启动 HTTP 服务器：原型静态伺服（GET /proto/<project>/<spec>/...）与
批注落盘（POST /api/proto/<project>/<spec>/feedback）由 fenix dashboard
常驻进程承载。本脚本探测存活 dashboard、按项目根路径解析其注册名、验证
原型 URL 可达，输出客户端可直接打开的地址（dashboard 端口为常驻稳定端口，
沿用既有访问通道即可直达，无需为原型临时开洞）。

不自行拉起 dashboard（拉起/巡检职责归 fenix-dashboard skill 与 systemd
unit ``fenix-dashboard.service``）；未存活时输出结构化错误与拉起指引。

用法::

    python3 proto_serve.py --project <项目根目录> --spec <spec 名>
                           [--dashboard-port N] [--round N] [--pretty]

端口候选链（逐个探测，首个存活者生效）：
``--dashboard-port`` > ``~/.config/fenixd/dashboard.yaml`` 顶层 ``port:``
（regex 解析，不引入 YAML 依赖）> 8787 默认。

退出码：0 = ok（``url`` 字段可直接交用户打开）；2 = 输入错误（项目根不
存在 / 原型目录缺失 / 目录内无 html）；3 = dashboard 不存活；4 = 项目未
注册（hint 指引 ``--add-project``）；5 = 原型 URL 验证失败（dashboard
存活但 /proto/ 路由 404——dashboard 版本过旧或 spec 名不符）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

# 框架目录自举：本脚本位于 <仓库根>/skills/fenix-prototype/scripts/ 下，
# 仓库根即框架主树（bin/fenix_dashboard.py 同树；第三方项目经 .fenix 软链
# 自举时仓库根下是 .fenix/bin/fenix_dashboard.py）
REPO_ROOT = Path(__file__).resolve().parents[3]


def _dashboard_py() -> Path | None:
    """框架 dashboard 入口脚本：优先主树 bin/，退回 .fenix/bin 自举软链。"""
    for cand in (REPO_ROOT / "bin" / "fenix_dashboard.py",
                 REPO_ROOT / ".fenix" / "bin" / "fenix_dashboard.py"):
        if cand.is_file():
            return cand
    return None

DEFAULT_PORT = 8787
PROBE_TIMEOUT = 2.0        # /api/projects 探测窗口
VERIFY_TIMEOUT = 5.0       # 原型 URL 可达性验证窗口


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
    except OSError:
        from_yaml = None
    if from_yaml:
        ports.append(from_yaml)
    ports.append(DEFAULT_PORT)
    return list(dict.fromkeys(ports))


def fetch_json(url: str, timeout: float) -> tuple[int | None, object | None]:
    """GET 并解析 JSON；网络/HTTP/解码失败统一返回 (None, None)。"""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read()
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        # HTTPError（4xx/5xx）与 URLError（连不通）都按「不可用」处理
        return None, None
    try:
        return status, json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return status, None


def probe_dashboard(port: int) -> dict | None:
    """探测 <port> 上是否存活 fenix dashboard：/api/projects 返回 200 且
    JSON 含 projects 列表（与 fenix-dashboard skill 的存活判定同口径）。"""
    status, payload = fetch_json(f"http://127.0.0.1:{port}/api/projects",
                                 PROBE_TIMEOUT)
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
        try:
            entry_real = os.path.realpath(
                os.path.expanduser(str(entry.get("path", ""))))
        except (OSError, ValueError):
            continue
        if entry_real == real:
            name = entry.get("name")
            return str(name) if name else None
    return None


def build_url(port: int, project: str, spec: str, page: str, round_: int) -> str:
    """拼客户端可直接打开的原型地址。

    index.html 用目录形态（尾斜杠，页面相对资源以其为基解析）；非 index
    页直指文件。轮次经 ``proto_round`` 查询参数携带（annotator.js 的轮次
    来源链第一优先）。
    """
    if page == "index.html":
        path = f"/proto/{project}/{spec}/"
    else:
        path = f"/proto/{project}/{spec}/{page}"
    return f"http://127.0.0.1:{port}{path}?proto_round={round_}"


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


def _launch_hint() -> str:
    dashboard_py = _dashboard_py()
    lines = []
    if dashboard_py:
        lines.append(f"python3 {dashboard_py} --serve  # 前台手工实例")
    lines.append("sudo systemctl start fenix-dashboard  # systemd 承载")
    return "；或 ".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="生成经 fenix dashboard 伺服的原型访问地址（不独立起服）")
    parser.add_argument("--project", required=True,
                        help="fenixd 项目根目录（须已在 dashboard 注册）")
    parser.add_argument("--spec", required=True, help="spec 名（原型目录名）")
    parser.add_argument("--dashboard-port", type=int, default=None,
                        help="dashboard 端口（缺省走配置与默认端口探测）")
    parser.add_argument("--round", type=int, default=1,
                        help="迭代轮次（写入 URL proto_round 参数，默认 1）")
    parser.add_argument("--pretty", action="store_true", help="JSON 缩进输出")
    args = parser.parse_args(argv)

    root = Path(args.project).expanduser()
    proto_dir = root / ".fenix" / "prototypes" / args.spec
    if not root.is_dir():
        return _fail(2, "project-root-missing",
                     f"项目根不存在或不是目录：{root}", pretty=args.pretty)
    if not proto_dir.is_dir():
        return _fail(2, "prototype-dir-missing",
                     f"原型目录不存在：{proto_dir}",
                     hint="先按 SKILL.md §3 生成原型到 .fenix/prototypes/<spec>/",
                     pretty=args.pretty)
    pages = sorted(str(p.relative_to(proto_dir))
                   for p in proto_dir.rglob("*.html") if p.is_file())
    if not pages:
        return _fail(2, "no-html",
                     f"原型目录内没有任何 .html 文件：{proto_dir}",
                     pretty=args.pretty)
    page = "index.html" if (proto_dir / "index.html").is_file() else pages[0]

    config_path = Path.home() / ".config" / "fenixd" / "dashboard.yaml"
    tried: list[int] = []
    for port in config_port_candidates(args.dashboard_port, config_path):
        tried.append(port)
        payload = probe_dashboard(port)
        if payload is None:
            continue
        name = match_registered_project(payload["projects"], root)
        if name is None:
            return _fail(4, "project-not-registered",
                         f"dashboard 存活（端口 {port}）但项目未注册：{root}",
                         hint=f"python3 {REPO_ROOT / 'bin' / 'fenix_dashboard.py'}"
                              " --add-project " + str(root),
                         pretty=args.pretty)
        url = build_url(port, name, args.spec, page, args.round)
        # 端到端验证：不带 query 直取页面 URL，须 200 才交付（否则用户拿到
        # 的是打不开的地址；404 通常意味着 dashboard 版本过旧或 spec 名不符）
        status, _ = fetch_json(url.split("?", 1)[0], VERIFY_TIMEOUT)
        if status != 200:
            return _fail(5, "proto-url-unreachable",
                         f"dashboard 存活但原型 URL 验证失败（HTTP {status}）：{url}",
                         hint="确认 dashboard 已升级到含 /proto/ 伺服的版本，"
                              "或核对 spec 名",
                         pretty=args.pretty)
        _emit({"ok": True, "url": url,
               "dashboard": f"http://127.0.0.1:{port}", "port": port,
               "project": name, "spec": args.spec, "page": page,
               "proto_dir": str(proto_dir), "files": pages,
               "round": args.round}, args.pretty)
        return 0
    return _fail(3, "dashboard-not-alive",
                 f"dashboard 不存活（探测端口：{tried}）",
                 hint=_launch_hint(),
                 pretty=args.pretty)


if __name__ == "__main__":
    sys.exit(main())
