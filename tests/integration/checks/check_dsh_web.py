#!/usr/bin/env python3
"""dsh web 插件面完整 GUI 验证（容器内执行；spec: add-integration-test-env）。

流程（设计 D7）：
  1. 插件供源解析：宿主目录挂载形态直接用；git URL 形态容器内克隆；
     两者皆无 → fail-loud exit 1（不静默降级）。
  2. bridge 插件（fenix-dsh-dashboard-bridge）pnpm build 后以软链形态挂入
     自定义 profile（对齐 dsh-bundle README 的 link: 安装口径）。
  3. DSH_HOME 隔离目录 + ``dsh --profile <自定义名> --from-default-profile web``
     初始化 profile（shipped 模板名被 CLI 禁止作为自定义 profile 目标，
     必须携带 --profile）。
  4. dashboard 服务先行就绪（:8787，由 check_dashboard.sh 幂等启动）。
  5. 启动 ``dsh web``（容器内固定 :3080，多 argv 形态探测）。
  6. Playwright（headless chromium）打开页面 → 断言面板桥「项目」菜单行
     元素存在 → 断言其 iframe src 含 ``embed=1`` → frame_locator 进入 iframe
     断言 dashboard 前端根节点渲染 → 截图落产物目录。

任一阶段失败输出失败阶段与原始错误并 exit 1。

依赖环境变量（e2e.sh 注入）：
  FENIX_IT_PLUGINS_REPO   插件源（容器内目录 或 git URL）
  FENIX_IT_FRAMEWORK_DIR  容器内框架克隆目录
  FENIX_IT_ARTIFACTS_DIR  产物目录（截图、dsh web 日志）
  FENIX_IT_DASH_PORT      dashboard 端口（默认 8787）
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PLUGINS = os.environ.get("FENIX_IT_PLUGINS_REPO", "").strip()
FW = Path(os.environ.get("FENIX_IT_FRAMEWORK_DIR", "/work/framework"))
ART = Path(os.environ.get("FENIX_IT_ARTIFACTS_DIR", "/artifacts"))
DASH_PORT = int(os.environ.get("FENIX_IT_DASH_PORT", "8787"))
WEB_PORT = 3080
DSH_WEB_HOME = Path("/work/dsh-web-home")
PROFILE = "fenix-web"
BRIDGE_NAME = "fenix-dsh-dashboard-bridge"

FAIL_STAGE = ""


def fail(stage: str, err: str) -> "None":
    global FAIL_STAGE
    FAIL_STAGE = stage
    print(f"[check_dsh_web] ❌ 阶段[{stage}] {err}", file=sys.stderr)
    sys.exit(1)


def run(cmd, cwd=None, timeout=600, env=None):
    """subprocess.run 薄封装：非零抛 RuntimeError 带原始 stderr/stdout 尾部。"""
    e = dict(os.environ)
    if env:
        e.update(env)
    proc = subprocess.run(
        cmd, cwd=cwd, env=e, capture_output=True, text=True, timeout=timeout,
    )
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-500:]
        raise RuntimeError(f"cmd={' '.join(map(str, cmd))} rc={proc.returncode}\n{tail}")
    return proc


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_port(port: int, seconds: int) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        if port_open(port):
            return True
        time.sleep(1)
    return False


def dashboard_env() -> dict:
    return {"DSH_HOME": str(DSH_WEB_HOME)}


# ── 1) 插件供源解析 ────────────────────────────────────────────────────────
print("[check_dsh_web] 阶段[供源] 解析 bridge 插件源")
if PLUGINS and Path(PLUGINS).is_dir():
    plugins_dir = Path(PLUGINS)
    print(f"  · 使用目录形态插件源: {plugins_dir}")
elif PLUGINS:
    plugins_dir = Path("/work/plugins-clone")
    print(f"  · git URL 形态插件源，容器内克隆: {PLUGINS}")
    shutil.rmtree(plugins_dir, ignore_errors=True)
    try:
        run(["git", "clone", "--depth", "1", PLUGINS, str(plugins_dir)], timeout=300)
    except Exception as exc:  # noqa: BLE001 — fail-loud 带原始错误
        fail("插件仓克隆", f"克隆失败: {exc}")
else:
    fail("插件供源", "FENIX_IT_PLUGINS_REPO 未提供（宿主目录或 git URL 皆无）")

bridge_dir = plugins_dir / BRIDGE_NAME
if not bridge_dir.is_dir():
    fail("插件供源", f"插件源内无 {BRIDGE_NAME} 目录: {plugins_dir}")

# ── 2) bridge 构建（pnpm build → lib/index.js）────────────────────────────
print("[check_dsh_web] 阶段[构建] pnpm install + pnpm build")
try:
    run(["pnpm", "install", "--no-frozen-lockfile"], cwd=bridge_dir, timeout=900)
    run(["pnpm", "build"], cwd=bridge_dir, timeout=600)
except FileNotFoundError:
    fail("插件构建", "pnpm 不可用（镜像未装 pnpm?）")
except subprocess.TimeoutExpired as exc:
    fail("插件构建", f"pnpm 构建/安装超时: {exc}")
except RuntimeError as exc:
    fail("插件构建", f"pnpm 失败: {exc}")
if not (bridge_dir / "lib" / "index.js").is_file():
    fail("插件构建", f"构建产物缺失: {bridge_dir}/lib/index.js")

# ── 3) 自定义 web profile 初始化 + link: 软链挂入 ──────────────────────────
print(f"[check_dsh_web] 阶段[profile] 初始化 {PROFILE}（--from-default-profile web）")
shutil.rmtree(DSH_WEB_HOME, ignore_errors=True)
try:
    run(["dsh", "--profile", PROFILE, "--from-default-profile", "web"],
        env=dashboard_env(), timeout=300)
    run(["dsh", "plugin", "--profile", PROFILE, "add", f"link:{bridge_dir}"],
        env=dashboard_env(), timeout=300)
except RuntimeError as exc:
    fail("profile/挂载", f"dsh profile 初始化或 plugin add 失败: {exc}")

pkg_path = DSH_WEB_HOME / "profiles" / PROFILE / "package.json"
try:
    pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
    bundles = pkg.setdefault("dsh", {}).setdefault("profile", {}).setdefault("bundles", [])
    if BRIDGE_NAME not in bundles:
        bundles.append(BRIDGE_NAME)
    pkg_path.write_text(json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8")
except Exception as exc:  # noqa: BLE001
    fail("profile/挂载", f"bundles 追加失败（{pkg_path}）: {exc}")
print(f"  · bridge 已以 link: 挂入 profile {PROFILE} 并追加 bundles")

# ── 4) dashboard 服务先行就绪 ──────────────────────────────────────────────
print("[check_dsh_web] 阶段[dashboard 就绪] 轮询 :%d" % DASH_PORT)
dash_ok = False
for _ in range(10):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{DASH_PORT}/api/projects", timeout=3
        ) as resp:
            if resp.status == 200:
                dash_ok = True
                break
    except Exception:  # noqa: BLE001 — 轮询期任意异常都视为未就绪
        time.sleep(2)
if not dash_ok:
    fail("dashboard 就绪", f":{DASH_PORT} 未就绪（check_dashboard.sh 应先行启动）")

# ── 5) 启动 dsh web（:3080；多 argv 形态探测）─────────────────────────────
print("[check_dsh_web] 阶段[dsh web 启动] 目标端口 :%d" % WEB_PORT)
web_log = open(ART / "dsh-web.log", "ab", buffering=0)
dsh_web_proc = None
argv_candidates = [
    ["dsh", "--profile", PROFILE, "web", "--port", str(WEB_PORT)],
    ["dsh", "--profile", PROFILE, "web", "-p", str(WEB_PORT)],
    ["dsh", "--profile", PROFILE, "web", "--port", str(WEB_PORT), "--host", "127.0.0.1"],
    ["dsh", "--profile", PROFILE, "web"],
]
for argv in argv_candidates:
    web_log.write(f"\n=== 尝试 argv: {' '.join(argv)} ===\n".encode())
    proc = subprocess.Popen(
        argv, cwd=str(FW), env={**os.environ, **dashboard_env(), "PORT": str(WEB_PORT)},
        stdout=web_log, stderr=subprocess.STDOUT,
    )
    if wait_port(WEB_PORT, 45):
        dsh_web_proc = proc
        print(f"  · dsh web 已监听 :{WEB_PORT}（argv={' '.join(argv)}）")
        break
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
if dsh_web_proc is None:
    tail = ""
    try:
        tail = (ART / "dsh-web.log").read_text(encoding="utf-8", errors="replace")[-800:]
    except OSError:
        pass
    fail("dsh web 启动", f"四种 argv 形态均未在 45s 内监听 :{WEB_PORT}；日志尾部:\n{tail}")

# ── 6) Playwright GUI 断言 ─────────────────────────────────────────────────
print("[check_dsh_web] 阶段[GUI 断言] Playwright headless chromium")
try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:
    fail("GUI 断言", f"playwright 未安装: {exc}")

try:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        # 深链直达「项目」面板（面板 id 与侧栏条目 id 同为 fenix-projects）
        page.goto(
            f"http://127.0.0.1:{WEB_PORT}/#panel=fenix-projects",
            wait_until="domcontentloaded", timeout=30_000,
        )

        # 6a) 面板桥「项目」菜单行/分区元素存在（Portal 分区 testid 或锚点）
        page.wait_for_selector(
            '[data-testid="fenix-projects-section"], [data-testid="fenix-projects-anchor"]',
            timeout=30_000,
        )
        print("  ✅ 面板桥「项目」菜单行元素在场")

        # 6b) 面板桥 iframe 挂载且 src 含 embed=1（iframe src 契约单源）
        iframe_sel = 'iframe[src*="embed=1"]'
        page.wait_for_selector(iframe_sel, timeout=30_000)
        src = page.get_attribute(iframe_sel, "src")
        if "embed=1" not in (src or ""):
            fail("GUI 断言", f"iframe src 缺 embed=1: {src}")
        print(f"  ✅ 面板桥 iframe src 含 embed=1: {src}")

        # 6c) frame_locator 进入 iframe，断言 dashboard 前端根节点渲染
        #    （Playwright 经 CDP 驱动，跨 origin iframe 可进入；umi 挂载根为 #root）
        frame = page.frame_locator(iframe_sel)
        frame.locator("#root").wait_for(timeout=30_000)
        if frame.locator("#root > *").count() == 0:
            fail("GUI 断言", "iframe 内 dashboard #root 无子节点（前端未渲染）")
        print("  ✅ iframe 内 dashboard 前端根节点已渲染")

        # 6d) 截图落产物目录
        shot = ART / "dsh-web-embed.png"
        page.screenshot(path=str(shot), full_page=False)
        print(f"  ✅ 截图落盘: {shot}")

        browser.close()
except Exception as exc:  # noqa: BLE001 — fail-loud 带原始异常
    fail("GUI 断言", f"{type(exc).__name__}: {exc}")

print("[check_dsh_web] 全部通过")
sys.exit(0)
