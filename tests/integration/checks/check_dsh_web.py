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
import re
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
        # stderr 在前（错误通常在 stderr），两端拼接保尾部；足够长以含错误头
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-2000:]
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


def boot_profile_until_created(argv: list, log_path: Path, seconds: int) -> None:
    """后台 boot dsh profile，待 profile package.json 落盘后收尾进程。

    `dsh --profile <p> --from-default-profile <t>` 的 CLI 语义是「初始化然后
    boot」（--help 实证），前台调用会一路 boot 成常驻服务永不返回（容器内
    实测 300s 超时）——初始化意图必须用后台 boot + 落盘轮询 + terminate 达成。
    stdin 接 DEVNULL（boot 后若进入交互态不至于吞住管道）。
    """
    log_f = open(log_path, "ab", buffering=0)
    proc = subprocess.Popen(
        argv, cwd=str(FW), env={**os.environ, **dashboard_env()},
        stdout=log_f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
    )
    profile_pkg = DSH_WEB_HOME / "profiles" / PROFILE / "package.json"
    deadline = time.time() + seconds
    while time.time() < deadline:
        if profile_pkg.is_file():
            break
        if proc.poll() is not None:
            fail("profile/挂载", f"profile boot 提前退出 rc={proc.returncode}，"
                 f"日志尾部见 {log_path}")
        time.sleep(1)
    else:
        proc.kill()
        fail("profile/挂载", f"{seconds}s 内 profile package.json 未落盘（{profile_pkg}）")
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=10)


def extract_web_url(log_path: Path) -> str:
    """从 dsh web 启动日志提取带 token 的服务 URL（`dsh web: http://...`）。"""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    hits = re.findall(r"(https?://127\.0\.0\.1:\d+/\?token=\S+)", text)
    return hits[-1].rstrip(".），") if hits else ""


def wait_web_url(log_path: Path, seconds: int = 15) -> str:
    """轮询启动日志直至 token URL 落盘（boot 横幅写盘可能晚于端口 listen）。

    竞态实测：wait_port 探到 :3080 listen 的瞬间读文件，横幅尚未写出 →
    extract 落空 → fallback 裸 URL → 服务 token 鉴权 401 → GUI 断言必然
    超时。此处轮询兜平写盘延迟；超时返回空串（调用方 fallback 裸 URL，
    无鉴权部署仍可用）。"""
    deadline = time.time() + seconds
    while time.time() < deadline:
        url = extract_web_url(log_path)
        if url:
            return url
        time.sleep(1)
    return ""


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

# ── 1.5) 复制进可写工作区再构建：目录形态插件源是只读卷挂载（run.sh 设计，
#         源零污染），而 pnpm install 需在包目录写 node_modules/.bin shims
#         （EROFS 实测）；构建一律在 /work 副本上进行，link: 亦指向副本。
bridge_build_dir = Path("/work/dsh-web-bridge")
shutil.rmtree(bridge_build_dir, ignore_errors=True)
# node_modules 必须排除：宿主目录形态下它是 pnpm symlink 农场（指向宿主
# store 路径，容器内不存在），带入会使 tsdown 配置加载期 import unrun 失败
# （实测）；副本内由 pnpm 依 lockfile 全新安装。
shutil.copytree(
    bridge_dir, bridge_build_dir, symlinks=True,
    ignore=shutil.ignore_patterns("node_modules"),
)
print(f"  · bridge 已复制进可写工作区（排除 node_modules）: {bridge_build_dir}")
bridge_dir = bridge_build_dir

# ── 2) bridge 构建（pnpm build → lib/index.js）────────────────────────────
print("[check_dsh_web] 阶段[构建] pnpm install + pnpm build")
try:
    run(["pnpm", "install", "--no-frozen-lockfile"], cwd=bridge_dir, timeout=900)
    # tsdown 0.23.1 虽声明 unrun 依赖，但其配置加载器从项目上下文 import，
    # pnpm 严格隔离下对项目不可见（容器内实测 ERR_MODULE_NOT_FOUND）——
    # 按 tsdown 声明范围补为直接依赖
    run(["pnpm", "add", "-D", "unrun@^0.3.1"], cwd=bridge_dir, timeout=300)
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
# 初始化以后台 boot 形态完成（见 boot_profile_until_created），插件必须在
# 最终 boot 之前挂入——web 服务的配置在 boot 时组定，运行中挂插件不生效。
print(f"[check_dsh_web] 阶段[profile] 初始化 {PROFILE}（--from-default-profile web，后台 boot）")
shutil.rmtree(DSH_WEB_HOME, ignore_errors=True)
web_log = ART / "dsh-web.log"
try:
    boot_profile_until_created(
        ["dsh", "--profile", PROFILE, "--from-default-profile", "web", "--no-open"],
        web_log, 120,
    )
    run(["dsh", "plugin", "--profile", PROFILE, "add", f"link:{bridge_dir}"],
        env=dashboard_env(), timeout=300)
except RuntimeError as exc:
    fail("profile/挂载", f"dsh profile 初始化或 plugin add 失败: {exc}")
# 挂入口径（容器内三轮探针实证）：`dsh plugin add` 只是 pnpm 装依赖——dsh
# web 的插件加载走 cordis Loader entry 列表（config 组成 = bundles patch 层
# → cordis.patch.yml → overlay）。bridge 是纯 dsh.client 插件（无 dsh.bundle
# manifest，bundle 通道实测报 "declares no dsh.bundle ... skipping"），必须
# 经 cordis.patch.yml 的 insert 条目进顶层 entry 列表：boot 时 host 半注册
# /fenix-dashboard/ 反代路由、client 半进 /plugins/?? 聚合清单（仅 add 不写
# patch 时两者皆缺席：路由 404、页面 HTML 零 fenix 命中；写 patch 后路由
# 在场实测 502——upstream dashboard 未起时的预期故障形态）。
patch_path = DSH_WEB_HOME / "profiles" / PROFILE / "cordis.patch.yml"
try:
    patch_path.write_text(
        "# fenix it: dashboard bridge 插入顶层 entry 列表（dsh plugin add 只装\n"
        "# 依赖，插件加载须经本 patch 层的 insert 条目）\n"
        "- insert:\n"
        f"    - id: {BRIDGE_NAME}\n"
        f"      name: {BRIDGE_NAME}\n",
        encoding="utf-8",
    )
except OSError as exc:
    fail("profile/挂载", f"cordis.patch.yml 写入失败: {exc}")
pkg_path = DSH_WEB_HOME / "profiles" / PROFILE / "package.json"
try:
    deps = json.loads(pkg_path.read_text(encoding="utf-8")).get("dependencies", {})
    if BRIDGE_NAME not in deps:
        fail("profile/挂载", f"plugin add 后 dependencies 缺 {BRIDGE_NAME}: {deps}")
except Exception as exc:  # noqa: BLE001
    fail("profile/挂载", f"plugin 挂入校验失败（{pkg_path}）: {exc}")
print(f"  · bridge 已挂入 profile {PROFILE}（link: 依赖 + patch 层 insert 条目）")

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

# ── 5) 最终 boot：插件已挂入的 profile 起 web 服务（:3080）─────────────────
print("[check_dsh_web] 阶段[dsh web 启动] 目标端口 :%d" % WEB_PORT)
dsh_web_proc = None
# `web` 子命令与 --profile 组合非法（实测 too many arguments）；直接 boot
# 自定义 profile 缺省 app 即 web。--no-open 传给 web app（容器内无浏览器，
# 启动横幅实测提示该开关）；dsh web 缺省端口 3080 与 WEB_PORT 同值。
argv_candidates = [
    ["dsh", "--profile", PROFILE, "--no-open"],
]
for argv in argv_candidates:
    log_f = open(web_log, "ab", buffering=0)
    log_f.write(f"\n=== 尝试 argv: {' '.join(argv)} ===\n".encode())
    proc = subprocess.Popen(
        argv, cwd=str(FW), env={**os.environ, **dashboard_env(), "PORT": str(WEB_PORT)},
        stdout=log_f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
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
        tail = web_log.read_text(encoding="utf-8", errors="replace")[-800:]
    except OSError:
        pass
    fail("dsh web 启动", f"各 argv 形态均未在 45s 内监听 :{WEB_PORT}；日志尾部:\n{tail}")
# 服务带 token 鉴权时页面必须带 token 访问（boot 横幅实测输出
# `dsh web: http://127.0.0.1:3080/?token=...`）——轮询等待落盘后提取供
# GUI 断言深链（wait_port 命中早于横幅写盘的竞态见 wait_web_url 注释）
WEB_URL = wait_web_url(web_log, 15) or f"http://127.0.0.1:{WEB_PORT}"
print(f"  · 服务 URL: {WEB_URL}")

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
        resp = page.goto(
            f"{WEB_URL}#panel=fenix-projects",
            wait_until="domcontentloaded", timeout=30_000,
        )
        # 前置 status 检查：裸 URL 撞 token 鉴权即 401，GUI 断言必空转超时
        # ——失败信息直指 WEB_URL 形态而非 selector 罗生门（实测教训）
        if resp is not None and resp.status >= 400:
            fail("GUI 断言", f"页面 HTTP {resp.status}（token 鉴权未过？WEB_URL={WEB_URL}）")

        # 6a) 面板桥「项目」分区元素存在（testid 均实证于 bridge 源码：
        #     panels.tsx 常规分区 section + 锚点漂移降级形态的 Portal 宿主）
        page.wait_for_selector(
            '[data-testid="fenix-projects-section"], '
            '[data-testid="fenix-projects-portal-host"]',
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
