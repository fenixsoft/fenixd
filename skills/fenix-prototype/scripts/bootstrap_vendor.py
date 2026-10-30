#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""vendor 预打包与三级降级判定（fenix-prototype · 任务 1.2）。

先做环境自检（node / npm / 代理 / 既有缓存），再按栈画像侦察到的版本把
react + antd 预打包进 **skill 自维护、与工程无关** 的 vendor 缓存；输出三级
降级判定，每一级在输出 JSON 中显式可见：

    1. ``vendor``  预打包缓存（本次命中或新打包写入）
    2. ``cdn``     CDN ESM 兜底（缓存不可用、网络可达时）
    3. ``plain``   纯 HTML/CSS 仿样（显式标注「视觉参照、无约束力」）

缓存落盘于 gitignore 覆盖的运行时目录 ``.fenix/prototype-vendor/``（依赖
仓根既有的 ``.fenix/*`` 整体忽略规则），MUST NOT 落仓内 ``skills/`` 入库；
输出中附 ``cache.git_ignored`` 自查结果兜底校验。

node 是优先条件而非硬假设：node/npm 缺失或打包失败时逐级降级，不硬崩。
零第三方依赖；本脚本对目标工程零写入（除缓存目录，及本地 node_modules
打包路径在工程 ``node_modules/.cache/`` 下的临时工作目录外——该目录随
node_modules 通行被 gitignore，打包后即清理）。

用法::

    python3 bootstrap_vendor.py --project <工程目录> [--cache-dir <dir>]
                                [--offline] [--install-timeout <sec>] [--pretty]

退出码：0 = 判定完成（含 plain 降级，属正常产物）；2 = 用法/目录错误。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from stack_profile import build_profile  # noqa: E402
else:  # pragma: no cover - 测试经 sys.path 直插导入
    from stack_profile import build_profile

SCHEMA_VERSION = "fenix-prototype/vendor-bootstrap@1"

#: 三级降级的用户可见标签（生成时必须向用户说明所用层级）
LEVEL_LABELS = {
    "vendor": "预打包 vendor 缓存（真实组件，具约束力）",
    "cdn": "CDN ESM 兜底（真实组件，具约束力；依赖外网可达）",
    "plain": "纯 HTML/CSS 仿样（视觉参照、无约束力）",
}

CDN_BASE = "https://esm.sh"
CDN_TIMEOUT_SEC = 8

#: npmjs 直连超时/失败时的镜像重试（国内网络环境下 npmjs 元数据解析常超时）
MIRROR_REGISTRY = "https://registry.npmmirror.com"

_ESBUILD_RE = re.compile(r"esbuild v(\d+\.\d+\.\d+)")


# ---------------------------------------------------------------------------
# 环境自检
# ---------------------------------------------------------------------------

def self_check() -> dict:
    """环境自检：node / npm 可用性与版本、代理环境变量。缺失不报错，只如实上报。"""
    node_path = shutil.which("node")
    npm_path = shutil.which("npm")
    node_version = npm_version = None
    if node_path:
        try:
            node_version = subprocess.run([node_path, "--version"], capture_output=True,
                                          text=True, timeout=15).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            node_version = None
    if npm_path:
        try:
            npm_version = subprocess.run([npm_path, "--version"], capture_output=True,
                                         text=True, timeout=15).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            npm_version = None
    proxy = {k: os.environ[k] for k in
             ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY")
             if os.environ.get(k)}
    return {
        "node": {"available": node_path is not None and bool(node_version),
                 "path": node_path, "version": node_version},
        "npm": {"available": npm_path is not None and bool(npm_version),
                "path": npm_path, "version": npm_version},
        "proxy_env": proxy,
    }


# ---------------------------------------------------------------------------
# 版本与缓存
# ---------------------------------------------------------------------------

def pinned(version_range: str) -> str | None:
    """``^6.6.0`` / ``~19.2.7`` / ``19.2.7`` → ``6.6.0``（按画像版本精确缓存）。

    无法从中提取精确版本的 range（如 ``>=18 <20``）返回 None：原样拼进
    ``react@<range>`` 会产出错误的安装参数，调用方须显式跳过 npm 精确
    安装路径再降级。
    """
    match = re.search(r"\d+\.\d+(\.\d+)?", version_range or "")
    return match.group(0) if match else None


def cache_key(react_version: str, antd_version: str) -> str:
    # 不可精确化的 range 回退原串作缓存键，避免不同 range 共享同一缓存目录
    return (f"react-{pinned(react_version) or react_version}"
            f"-antd-{pinned(antd_version) or antd_version}")


def cache_manifest_read(cache_dir: Path) -> dict | None:
    manifest = cache_dir / "manifest.json"
    if not manifest.is_file():
        return None
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def cache_lookup(cache_root: Path, react_version: str, antd_version: str) -> dict | None:
    """按精确版本查缓存；manifest 版本不匹配或产物完整性复核失败视为未命中。"""
    entry = cache_root / cache_key(react_version, antd_version)
    manifest = cache_manifest_read(entry)
    if manifest is None or not (entry / "vendor.js").is_file():
        return None
    if pinned(str(manifest.get("react", ""))) != pinned(react_version):
        return None
    if pinned(str(manifest.get("antd", ""))) != pinned(antd_version):
        return None
    # 完整性复核：manifest 与 vendor.js 两步落盘非原子，进程在写入间隙被杀
    # 可能留下「旧 manifest + 截断产物」组合；先比大小再做 sha256，不一致
    # 按未命中处理，避免把损坏产物以 vendor（具约束力）层级下发。
    try:
        data = (entry / "vendor.js").read_bytes()
    except OSError:
        return None
    expected_bytes = manifest.get("bytes")
    if isinstance(expected_bytes, int) and len(data) != expected_bytes:
        return None
    expected_sha = manifest.get("sha256")
    if isinstance(expected_sha, str) and expected_sha and \
            hashlib.sha256(data).hexdigest() != expected_sha:
        return None
    return {"dir": entry, "manifest": manifest}


def write_cache(cache_root: Path, versions: dict, vendor_js: Path,
                node_version: str | None) -> Path:
    """把打包产物写入缓存并生成 manifest（含 sha256 与实际打包版本）。

    产物与 manifest 均先写临时文件再原子 replace：保证「manifest 在即产物
    完整」不变量，进程在写入间隙被杀不会留下截断的 vendor.js 或半截 manifest。
    """
    entry = cache_root / cache_key(versions["react"], versions["antd"])
    entry.mkdir(parents=True, exist_ok=True)
    data = vendor_js.read_bytes()
    vendor_tmp = entry / f"vendor.js.tmp-{os.getpid()}"
    vendor_tmp.write_bytes(data)
    os.replace(vendor_tmp, entry / "vendor.js")
    manifest = {
        "react": versions["react"],
        "react-dom": versions.get("react-dom", versions["react"]),
        "antd": versions["antd"],
        "vendor_js": "vendor.js",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "tool": {"name": "esbuild", "version": versions.get("esbuild", "unknown")},
        "node_version": node_version,
        "created": datetime.now(timezone.utc).isoformat(),
    }
    manifest_tmp = entry / f"manifest.json.tmp-{os.getpid()}"
    manifest_tmp.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(manifest_tmp, entry / "manifest.json")
    return entry


def git_ignored(path: Path) -> bool | None:
    """自查路径是否被 gitignore 覆盖（路径不在任何 git 仓内返回 None）。

    check-ignore 的 ignore 规则按路径所属 git 仓解析：先用最近的现存祖先
    目录定位其仓根，再以该仓根为 cwd 执行。脱离仓语境（脚本进程 cwd 不在
    仓内、或属于另一个仓）执行会使自查结果失真成误报源。
    """
    anchor = path
    while not anchor.is_dir() and anchor.parent != anchor:
        anchor = anchor.parent
    try:
        top = subprocess.run(["git", "-C", str(anchor), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, timeout=10)
        if top.returncode != 0:
            return None
        repo_root = Path(top.stdout.strip() or ".").resolve()
        target = path.resolve()
        try:
            check_path = str(target.relative_to(repo_root))
        except ValueError:
            check_path = str(target)
        proc = subprocess.run(["git", "check-ignore", "-q", "--", check_path],
                              capture_output=True, timeout=10, cwd=str(repo_root))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return proc.returncode == 0


# ---------------------------------------------------------------------------
# 打包（node 路径）与 CDN 探测
# ---------------------------------------------------------------------------

VENDOR_ENTRY_JS = """\
// fenix-prototype vendor 入口：把 react / react-dom / antd 暴露为浏览器全局，
// 供单文件原型 HTML 以真实组件渲染（antd v5+ 无浏览器全局构建，必须打包）。
import * as React from "react";
import { createRoot } from "react-dom/client";
import * as antd from "antd";

window.React = React;
window.ReactDOM = { createRoot };
window.antd = antd;
"""


def _installed_version(node_modules: Path, package: str) -> str | None:
    pkg_json = node_modules / package / "package.json"
    if not pkg_json.is_file():
        return None
    try:
        return str(json.loads(pkg_json.read_text(encoding="utf-8")).get("version") or "")
    except (OSError, ValueError):
        return None


def _esbuild_version(esbuild_bin: Path) -> str:
    try:
        proc = subprocess.run([str(esbuild_bin), "--version"], capture_output=True,
                              text=True, timeout=15)
        match = _ESBUILD_RE.search(proc.stdout or "")
        return match.group(1) if match else (proc.stdout or "").strip() or "unknown"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _run_esbuild(esbuild_bin: Path, entry: Path, outfile: Path,
                 timeout: float, log: list[str]) -> Path | None:
    log.append("esbuild-bundle: iife 打包 react+react-dom+antd → vendor.js")
    try:
        proc = subprocess.run(
            [str(esbuild_bin), str(entry), "--bundle", "--format=iife",
             f"--outfile={outfile}", "--log-level=warning", "--jsx=automatic"],
            capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        log.append("bundle-fail: esbuild 打包超时，本步放弃")
        return None
    if proc.returncode != 0 or not outfile.is_file():
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        log.append("bundle-fail: esbuild 打包失败（rc=%d）：%s"
                   % (proc.returncode, " / ".join(tail) or "无输出"))
        return None
    log.append("bundle-ok: 打包完成")
    return outfile


def find_local_node_modules(project: Path) -> Path | None:
    """从 project 逐级向上找含 react + antd 的既有 node_modules（零网络打包入口）。"""
    cur = project.resolve()
    for _ in range(6):
        candidate = cur / "node_modules"
        if (candidate / "antd" / "package.json").is_file() and \
           (candidate / "react" / "package.json").is_file():
            return candidate
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _persist_bundle(outfile: Path) -> Path:
    """把打包产物挪出 TemporaryDirectory，落系统临时文件（调用方缓存后清理）。"""
    fd, name = tempfile.mkstemp(prefix="fenix-vendor-", suffix=".js")
    os.close(fd)
    dest = Path(name)
    shutil.copyfile(outfile, dest)
    return dest


def bundle_with_node(project: Path, react_version: str, antd_version: str,
                     install_timeout: float,
                     ) -> tuple[Path | None, dict | None, list[str]]:
    """按画像版本预打包 react+antd。成功返回 (vendor_js, 实际打包版本 dict, log)。

    两条路径逐级尝试，每步显式记入 log（降级可见性要求）：

    1. npm 精确安装（默认 registry 超时/失败 → 镜像 registry 重试一次）；
    2. 本地既有 node_modules 直接打包（零网络；实际安装版本可能与画像 range
       不同，以 package.json 实测版本入 manifest 并记录）。

    全部失败返回 (None, None, log)，由调用方继续向 CDN / 仿样降级。
    """
    log: list[str] = []
    npm = shutil.which("npm")
    if not npm:
        log.append("bundle-fail: npm 不可用，跳过 npm 精确安装路径")
    react_pin = pinned(react_version)
    antd_pin = pinned(antd_version)
    if npm and (react_pin is None or antd_pin is None):
        log.append(f"bundle-fail: 版本 range 不可精确化"
                   f"（react@{react_version} antd@{antd_version}），"
                   "跳过 npm 精确安装路径，转本地 node_modules 打包")
        npm = None

    with tempfile.TemporaryDirectory(prefix="fenix-proto-vendor-") as tmp:
        tmp_dir = Path(tmp)
        if npm:
            for registry in (None, MIRROR_REGISTRY):
                label = registry or "默认 registry"
                log.append(f"npm-install[{label}]: react@{react_pin} "
                           f"react-dom@{react_pin} antd@{antd_pin} "
                           f"esbuild（timeout={install_timeout:g}s）")
                cmd = [npm, "install", "--prefix", str(tmp_dir), "--no-save", "--no-audit",
                       "--no-fund", "--loglevel=error",
                       f"react@{react_pin}",
                       f"react-dom@{react_pin}",
                       f"antd@{antd_pin}",
                       "esbuild"]
                if registry:
                    cmd += ["--registry", registry]
                try:
                    proc = subprocess.run(cmd, capture_output=True, text=True,
                                          timeout=install_timeout)
                except subprocess.TimeoutExpired:
                    log.append(f"bundle-fail[{label}]: npm install 超时"
                               f"（>{install_timeout:g}s），换下一路径")
                    continue
                if proc.returncode != 0:
                    tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-2:]
                    log.append(f"bundle-fail[{label}]: npm install 失败（rc=%d）：%s"
                               % (proc.returncode, " / ".join(tail) or "无输出"))
                    continue
                esbuild_bin = tmp_dir / "node_modules" / ".bin" / "esbuild"
                entry = tmp_dir / "vendor-entry.js"
                entry.write_text(VENDOR_ENTRY_JS, encoding="utf-8")
                outfile = _run_esbuild(esbuild_bin, entry, tmp_dir / "vendor.js",
                                       install_timeout, log)
                if outfile is not None:
                    return _persist_bundle(outfile), {
                        "react": react_pin,
                        "react-dom": react_pin,
                        "antd": antd_pin,
                        "esbuild": _esbuild_version(esbuild_bin),
                    }, log
                # 安装成功但打包失败：与 registry 无关（同入口同依赖树，结果
                # 确定），换镜像重装重打只会白耗一轮安装超时，直接转本地路径
                log.append("bundle-fail: esbuild 打包失败与 registry 无关，"
                           "不再重试镜像 registry，转本地 node_modules 路径")
                break

        # npm 精确安装不可用 → 本地既有 node_modules 直接打包（零网络）
        local = find_local_node_modules(project)
        if local is None:
            log.append("local-modules-miss: 工程及上级目录未找到含 react+antd 的 node_modules")
            return None, None, log
        local_antd = _installed_version(local, "antd") or antd_version
        local_react = _installed_version(local, "react") or react_version
        log.append(f"local-modules-hit: 复用本地 {local}（antd@{local_antd} react@{local_react}，"
                   "实际安装版本可能与画像 range 有差异，以实测为准）")
        esbuild_bin = local / ".bin" / "esbuild"
        if not esbuild_bin.is_file():
            log.append("bundle-fail: 本地 node_modules 无 esbuild 可执行文件")
            return None, None, log
        # 本地打包：入口必须落在 node_modules 解析范围内——用其下 .cache 工作目录
        # （node_modules 通行被 gitignore，散件零风险），产物经系统临时文件中转
        work = local / ".cache" / f"fenix-proto-work-{os.getpid()}"
        outfile = None
        try:
            work.mkdir(parents=True, exist_ok=True)
            entry = work / "vendor-entry.js"
            entry.write_text(VENDOR_ENTRY_JS, encoding="utf-8")
            outfile = _run_esbuild(esbuild_bin, entry, tmp_dir / "vendor.js",
                                   install_timeout, log)
        except (OSError, subprocess.SubprocessError) as exc:
            # mkdir / 入口写入 / esbuild 执行的 OSError（权限、只读、跨设备等）
            # 不向上穿透硬崩，记 bundle-fail 后交由调用方继续 CDN / 仿样降级
            log.append(f"bundle-fail: 本地 node_modules 打包异常"
                       f"（{type(exc).__name__}: {exc}），本步放弃")
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if outfile is None:
            return None, None, log
        return _persist_bundle(outfile), {
            "react": pinned(local_react) or local_react,
            "react-dom": pinned(local_react) or local_react,
            "antd": pinned(local_antd) or local_antd,
            "esbuild": _esbuild_version(esbuild_bin),
        }, log


def cdn_urls(react_version: str, antd_version: str) -> dict[str, str]:
    """CDN ESM 兜底资源清单（importmap 用）。"""
    react = pinned(react_version) or react_version
    antd = pinned(antd_version) or antd_version
    return {
        "react": f"{CDN_BASE}/react@{react}",
        "react-dom": f"{CDN_BASE}/react-dom@{react}",
        "antd": f"{CDN_BASE}/antd@{antd}"
                f"?deps=react@{react},react-dom@{react}",
    }


def cdn_probe(react_version: str, antd_version: str, timeout: float = CDN_TIMEOUT_SEC,
              _opener=None) -> tuple[bool, str | None]:
    """探测 CDN ESM 可达性（GET 主资源，读少量字节即断开）。失败返回 (False, 原因)。"""
    url = cdn_urls(react_version, antd_version)["antd"]
    try:
        if _opener is not None:
            with _opener(url, timeout=timeout) as resp:
                ok = 200 <= resp.status < 300
            return (ok, None if ok else f"HTTP 状态非 2xx")
        req = urllib.request.Request(url, headers={"User-Agent": "fenix-prototype-bootstrap"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ok = 200 <= resp.status < 300
        return (ok, None if ok else "HTTP 状态非 2xx")
    except Exception as exc:  # 网络层任何失败都只降级，不硬崩
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# 三级降级判定（纯函数，可确定性测试）
# ---------------------------------------------------------------------------

def decide_level(*, has_supported_stack: bool, cache_hit: bool, node_ok: bool,
                 bundle_succeeded: bool, cdn_ok: bool) -> str:
    """三级降级判定：vendor 缓存 → node 现打包 → CDN ESM → 纯 HTML 仿样。"""
    if not has_supported_stack:
        return "plain"
    if cache_hit:
        return "vendor"
    if node_ok and bundle_succeeded:
        return "vendor"
    if cdn_ok:
        return "cdn"
    return "plain"


def vendor_script_snippet(vendor_js_rel: str) -> str:
    """vendor 层的原型引用片段：vendor.js 与原型 HTML 同目录（生成时复制）。"""
    return f'<script src="{vendor_js_rel}"></script>'


def cdn_importmap_snippet(react_version: str, antd_version: str) -> str:
    """CDN 层的原型引用片段：importmap + 模块脚本（antd 裸名映射到 esm.sh）。"""
    urls = cdn_urls(react_version, antd_version)
    return (
        '<script type="importmap">\n'
        "{\n"
        '  "imports": {\n'
        f'    "react": "{urls["react"]}",\n'
        f'    "react-dom/client": "{urls["react-dom"]}",\n'
        f'    "antd": "{urls["antd"]}"\n'
        "  }\n"
        "}\n"
        "</script>\n"
        '<script type="module">\n'
        '  import * as React from "react";\n'
        '  import { createRoot } from "react-dom/client";\n'
        '  import * as antd from "antd";\n'
        "  window.React = React; window.ReactDOM = { createRoot }; window.antd = antd;\n"
        "</script>"
    )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def run(project: Path, cache_dir: Path, offline: bool = False,
        install_timeout: float = 300.0, cdn_probe_fn=cdn_probe,
        bundle_fn=None) -> dict:
    """执行环境自检 + 缓存/打包/降级判定，返回输出 JSON（dict）。

    ``cdn_probe_fn`` / ``bundle_fn`` 为测试注入点（默认真实探测/真实打包）。
    """
    if bundle_fn is None:
        bundle_fn = bundle_with_node
    selfcheck = self_check()
    profile = build_profile(project)
    has_stack = bool(profile.get("detected"))

    react_version = antd_version = None
    if has_stack:
        react_version = profile["framework"].get("version", "")
        antd_version = profile["component_library"].get("version", "")

    degradation_path: list[str] = []
    cache_entry = None
    cache_hit = False
    if has_stack:
        hit = cache_lookup(cache_dir, react_version, antd_version)
        if hit is not None:
            cache_hit = True
            cache_entry = hit
            degradation_path.append(
                f"vendor-cache-hit: {cache_key(react_version, antd_version)} 命中，直接复用")
        else:
            degradation_path.append(
                f"vendor-cache-miss: {cache_key(react_version, antd_version)} 未命中，尝试现打包")
    else:
        degradation_path.append("stack-unknown: 画像识别失败，跳过缓存与打包，直落仿样")

    vendor_js = None
    bundled_versions = None
    if has_stack and not cache_hit:
        node_ok = selfcheck["node"]["available"] and selfcheck["npm"]["available"]
        if not node_ok:
            degradation_path.append("node-missing: node/npm 不可用（node 是优先条件非硬假设），"
                                    "跳过 npm 精确安装路径，尝试本地 node_modules 打包")
        vendor_js, bundled_versions, bundle_log = bundle_fn(
            project, react_version, antd_version, install_timeout)
        degradation_path.extend(bundle_log)
        if vendor_js is not None and bundled_versions is not None:
            try:
                entry = write_cache(cache_dir, bundled_versions, vendor_js,
                                    selfcheck["node"]["version"])
            except (OSError, ValueError) as exc:
                # 缓存目录不可写（权限/只读/.fenix 被普通文件占据等）不硬崩，
                # 与「node/npm 缺失或打包失败时逐级降级」同一契约：记原因后
                # 作废本次产物，继续 CDN / 仿样降级
                degradation_path.append(
                    f"vendor-cache-write-fail: 缓存写入失败"
                    f"（{type(exc).__name__}: {exc}），本次打包产物作废，"
                    "继续 CDN / 仿样降级")
                try:
                    Path(str(vendor_js)).unlink(missing_ok=True)
                except OSError:
                    pass
                vendor_js = None
            else:
                cache_entry = {"dir": entry, "manifest": cache_manifest_read(entry)}
                degradation_path.append(f"vendor-cache-write: 已写入缓存 {entry.name}")
                # 打包产物已复制入缓存，清理系统临时落点（只清系统临时目录内的）
                try:
                    vj = Path(str(vendor_js))
                    if tempfile.gettempdir() in vj.resolve().parents:
                        vj.unlink(missing_ok=True)
                except OSError:
                    pass

    cdn_ok = False
    cdn_reason = None
    # 探测仅在「缓存未命中且打包失败」时才有意义：cdn_ok 只在这种分支参与
    # 判定；缓存命中已定 vendor 层，探测白付网络等待且结果不会被消费
    if has_stack and not cache_hit and vendor_js is None and not offline:
        cdn_ok, cdn_reason = cdn_probe_fn(react_version, antd_version)
        degradation_path.append(
            f"cdn-probe: {'可达' if cdn_ok else '不可达（' + str(cdn_reason) + '）'}")
    elif has_stack and cache_hit:
        degradation_path.append(
            "cdn-probe: 缓存命中已定 vendor 层，跳过 CDN 探测（结果不参与判定）")
    elif has_stack and offline and not cache_hit and vendor_js is None:
        degradation_path.append("cdn-probe: --offline 跳过 CDN 探测")

    level = decide_level(
        has_supported_stack=has_stack,
        cache_hit=cache_hit,
        node_ok=selfcheck["node"]["available"] and selfcheck["npm"]["available"],
        bundle_succeeded=vendor_js is not None,
        cdn_ok=cdn_ok,
    )
    if level == "plain" and has_stack:
        degradation_path.append("plain-fallback: 三级全落空 → 纯 HTML/CSS 仿样（视觉参照、无约束力）")

    assets: dict = {}
    if level == "vendor" and cache_entry is not None:
        assets = {
            "vendor_js": str((cache_entry["dir"] / "vendor.js").resolve()),
            "manifest": cache_entry["dir"] / "manifest.json",
            "snippet": vendor_script_snippet("vendor.js"),
            "note": "生成原型时把 vendor.js 复制进原型目录与 HTML 同放",
        }
    elif level == "cdn":
        assets = {
            "urls": cdn_urls(react_version, antd_version),
            "snippet": cdn_importmap_snippet(react_version, antd_version),
            # importmap 裸名导入无 integrity 属性可用（SRI 不适用于 ES module
            # 映射），供应链风险只能显式标注供生成侧提示用户
            "note": "CDN 资源无完整性校验（importmap 直接执行 esm.sh 返回内容，"
                    "无 SRI）：CDN 被劫持或返回被篡改 JS 时将在浏览器执行任意代码，"
                    "生成原型时须向用户说明该风险",
        }

    ignored = git_ignored(cache_dir)
    if ignored is False:
        degradation_path.append(
            f"cache-ignore-warning: 缓存目录 {cache_dir} 未被 gitignore 覆盖，"
            "请确认在仓根运行或调整 --cache-dir，MUST NOT 使缓存入库")

    return {
        "schema": SCHEMA_VERSION,
        "ok": True,
        "level": level,
        "level_label": LEVEL_LABELS[level],
        "degradation_path": degradation_path,
        "environment": selfcheck,
        "profile": {
            "detected": profile.get("detected", False),
            "profile": profile.get("profile"),
            "react_version": react_version,
            "antd_version": antd_version,
        },
        "cache": {
            "dir": str(cache_dir),
            "hit": cache_hit,
            "entry": str(cache_entry["dir"].resolve()) if cache_entry else None,
            "manifest": cache_entry["manifest"] if cache_entry else None,
            "git_ignored": ignored,
        },
        "assets": assets,
        "generation": profile.get("generation"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fenix-prototype vendor 预打包与三级降级判定")
    parser.add_argument("--project", default=".", help="目标工程根目录（默认当前目录）")
    parser.add_argument("--cache-dir", default=".fenix/prototype-vendor",
                        help="vendor 缓存目录（默认 .fenix/prototype-vendor，gitignore 覆盖）")
    parser.add_argument("--offline", action="store_true",
                        help="跳过 CDN 探测（离线判定，缓存未命中直接落仿样）")
    parser.add_argument("--install-timeout", type=float, default=300.0,
                        help="npm install / esbuild 单步超时秒数（默认 300）")
    parser.add_argument("--output", default=None, help="判定 JSON 落盘路径（默认打印 stdout）")
    parser.add_argument("--pretty", action="store_true", help="缩进美化输出")
    args = parser.parse_args(argv)

    project = Path(args.project)
    if not project.is_dir():
        print(json.dumps({"ok": False, "error": f"工程目录不存在：{args.project}"},
                         ensure_ascii=False), file=sys.stderr)
        return 2

    result = run(project, Path(args.cache_dir), offline=args.offline,
                 install_timeout=args.install_timeout)
    text = json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None,
                      default=str)
    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
