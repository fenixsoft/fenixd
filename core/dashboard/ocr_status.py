"""ocr_status.py — open-code-review（ocr）安装探测与一键安装（质量页签）。

背景：`verify.impl_code_review` 开启后，实现者收尾阶段调用 `bin/ocr_review.py`
包装器调 ocr 审查本 spec 改动。ocr 是外部 npm 包
（@alibaba-group/open-code-review），未安装时实现者按 `status: "unavailable"`
降级跳过。设置页「质量」页签据此提供安装状态提示与一键安装，使「开关可用」
与「环境确能跑 ocr」一致。

探测口径：`shutil.which("ocr")` —— 与包装器 bin/ocr_review.py 的
`FENIX_OCR_BIN` 缺省裸名路径解析同一条 PATH，避免「界面说可用、运行期找不到」
的错配（若改用 `npm ls -g` 探测，会漏掉 PATH 上有 ocr 但不在 npm 全局前缀的
装法，反之亦然）。

安装：`npm install -g @alibaba-group/open-code-review`，固定字面量、无用户
输入拼接（无注入面）。非零退出/超时/异常一律返回可读错误，不做 sudo 提权
（用户决策：权限不足时把 npm 原始报错透出，由用户自行用 sudo 安装）。
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import threading

from core.proc_utils import guard_killpg

# 安装命令的包名（固定字面量，不拼接任何用户输入）
OCR_NPM_PACKAGE = "@alibaba-group/open-code-review"

# `ocr --version` 解析超时（秒）——版本探测失败不影响 installed 判定
_VERSION_TIMEOUT = 5
# `npm install -g` 超时（秒）——全局安装含下载与解包，给足余量
_INSTALL_TIMEOUT = 300
# 全局安装互斥（code-review item ea103a53f670）：dashboard 跑在
# ThreadingHTTPServer 上，双击/两个并发 POST /api/quality/ocr-install 会同时
# 起两个 `npm install -g` 写同一全局前缀，可能损坏 node_modules 并产生难解的
# EEXIST/EBUSY。非阻塞获取，已持锁则返回可读的「安装进行中」错误。
_INSTALL_LOCK = threading.Lock()


def _partial_output(exc) -> str:
    """从 TimeoutExpired 取出子进程已产出的部分 stdout/stderr（尾部 4000 字符）。

    `capture_output+text=True` 时 exc.stdout/stderr 为 str；若 bytes（未设 text）
    则容错解码。任一为空按空串参与拼接。code-review item 95afe353e7d3。
    """
    def _as_text(v) -> str:
        if v is None:
            return ""
        if isinstance(v, bytes):
            return v.decode("utf-8", errors="replace")
        return str(v)

    combined = (_as_text(getattr(exc, "stdout", None)) + "\n"
                + _as_text(getattr(exc, "stderr", None))).strip()
    return combined[-4000:]


def _ocr_version(ocr_bin: str) -> str | None:
    """跑 `ocr --version` 取首行版本描述；失败/超时返回 None。

    首行形如 "open-code-review v1.12.5 (189be5b024) linux/amd64"，原样返回该行
    （UI 直接展示，不再二次解析版本号格式，避免与上游输出格式耦合）。
    """
    try:
        r = subprocess.run(
            [ocr_bin, "--version"],
            capture_output=True,
            # 非交互：不继承 daemon 的 stdin，避免探测进程等待输入
            stdin=subprocess.DEVNULL,
            # 显式 UTF-8：text=True 缺省按 locale 解码，LC_ALL=C 启动的 daemon
            # 遇 UTF-8 输出会抛 UnicodeDecodeError（不被下方 OSError/SubprocessError
            # 捕获）。errors=replace 保证坏字节不再中断探测（code-review item
            # fb2757a60715）。
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_VERSION_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    first = (r.stdout or "").strip().splitlines()
    return first[0].strip() if first else None


def check_ocr_installed() -> dict:
    """探测 ocr 是否安装。

    Returns:
        {"installed": bool, "bin": str|None, "version": str|None}
        - installed=False 时 bin/version 均为 None
        - 已装但 `ocr --version` 失败时 version=None，installed 仍为 True
    """
    ocr_bin = shutil.which("ocr")
    if not ocr_bin:
        return {"installed": False, "bin": None, "version": None}
    return {"installed": True, "bin": ocr_bin, "version": _ocr_version(ocr_bin)}


def install_ocr(timeout: int = _INSTALL_TIMEOUT) -> dict:
    """执行全局 npm 安装。

    Returns:
        {"ok": bool, "error": str|None, "output": str, "version": str|None}
        - ok=True 时附带安装后重新探测的 version（供 UI 立即刷新状态）
        - ok=False 时 error 为可读摘要，output 为 npm stdout/stderr 尾部
          （权限不足等原始报错透出给用户，便于自行 sudo 安装）
        - 并发调用：非阻塞获取全局安装锁，已被占用时返回 error="安装进行中"
          （code-review item ea103a53f670）
    """
    # 下界防御（code-review item fe2c2b2c005e）：timeout<=0 直接透传
    # subprocess.run 行为依赖 CPython 内部实现（0 立即超时、负值可能抛未被
    # 捕获成可读错误 dict 的 ValueError），公开 API 入口钳制回默认值。
    if timeout <= 0:
        timeout = _INSTALL_TIMEOUT
    if not _INSTALL_LOCK.acquire(blocking=False):
        return {
            "ok": False,
            "error": "安装进行中（已有 npm install 正在执行），请稍候重试",
            "output": "",
            "version": None,
        }
    try:
        return _install_ocr_locked(timeout)
    finally:
        _INSTALL_LOCK.release()


def _run_npm_install(argv: list, timeout: int) -> subprocess.CompletedProcess:
    """npm install 执行（start_new_session + 超时进程组清扫）。

    subprocess.run(timeout=...) 超时只终止直接子进程 npm，npm 派生的 node
    孙进程未经收组残留，可继续写全局前缀的 node_modules（半解包/EEXIST，
    与本模块并发安装互斥锁要防的形态同型，code-review item 1984565d20b3）。
    按 core/verify_contract.py ``_run_npm_provision`` 同款组清扫纪律：
    start_new_session 使 leader 即进程组长（pgid == p.pid），提前取定句柄
    防 wait 回收 leader 后 getpgid 失效；超时 SIGTERM 组 → wait(5) →
    SIGKILL 组补刀 → 补 communicate 排空管道收尸，随后按 subprocess.run 同
    约定向调用方抛 TimeoutExpired（既有超时分支的 _partial_output 诊断继续
    生效）。Popen 的 OSError 同样交由调用方捕获。
    """
    p = subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        # 非交互：npm 首次运行可能弹交互确认，读 DEVNULL 使其走非交互
        # 分支/立即失败，不挂起到超时、不消费 daemon 终端输入
        stdin=subprocess.DEVNULL,
        # 同 _ocr_version：显式 UTF-8 + replace，免 locale 依赖解码
        # （code-review item fb2757a60715）。
        text=True,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    )
    try:
        out, err = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            pgid = os.getpgid(p.pid)
        except (ProcessLookupError, PermissionError, OSError):
            pgid = p.pid
        # 击杀最后一跳经自保护守卫（add-killpg-self-guard）：pgid 已提前取定
        # 直传；守卫拒绝（自身组/非正 pgid）与组已不存在同样静默。
        guard_killpg(
            pgid, signal.SIGTERM, caller="ocr_status._run_npm_install", resolve=False
        )
        try:
            p.wait(timeout=5)
        except Exception:
            pass
        # 组清扫补刀：leader 退出不等于组内已清——忽略 SIGTERM 的孙进程
        # （npm 派生的 node）会残留继续写全局前缀，无论 wait 成败都补一次
        # SIGKILL；ProcessLookupError＝组已清空，静默即可。
        guard_killpg(
            pgid, signal.SIGKILL, caller="ocr_status._run_npm_install", resolve=False
        )
        # 收尸：补一次 communicate 排空 stdout/stderr 管道并回收退出状态。
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        raise
    return subprocess.CompletedProcess(argv, p.returncode, out, err)


def _install_ocr_locked(timeout: int) -> dict:
    """`_INSTALL_LOCK` 保护下的实际安装流程（调用方持锁）。"""
    try:
        r = _run_npm_install(["npm", "install", "-g", OCR_NPM_PACKAGE], timeout)
    except subprocess.TimeoutExpired as e:
        # 超时分支保留子进程已写出的部分诊断（code-review item 95afe353e7d3）：
        # 最慢的失败模式（300s 安装）此前只返回空 output，用户看不到任何细节，
        # 而调用方明确依赖 output 透出 npm 报错尾部。TimeoutExpired 携带
        # stdout/stderr 的部分内容，bytes/text 两态都容错解码。
        return {
            "ok": False,
            "error": f"安装超时（>{timeout}s）",
            "output": _partial_output(e),
            "version": None,
        }
    except OSError as e:
        # npm 不在 PATH / 无法执行
        return {
            "ok": False,
            "error": f"无法执行 npm：{e}",
            "output": "",
            "version": None,
        }

    combined = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
    # 尾部截断：npm 报错可能很长，只保留最后 4000 字符（错误通常在末尾）
    output = combined[-4000:]
    if r.returncode != 0:
        return {
            "ok": False,
            "error": f"npm install 返回非零退出码 {r.returncode}",
            "output": output,
            "version": None,
        }
    # 安装成功：重新探测（shutil.which 命中新装的 ocr）
    status = check_ocr_installed()
    if not status["installed"]:
        # 极少见：npm 报告成功但 PATH 上仍找不到（如全局前缀不在 PATH）
        return {
            "ok": False,
            "error": "npm 安装完成但 PATH 上仍找不到 ocr，请检查 npm 全局前缀是否在 PATH 中",
            "output": output,
            "version": None,
        }
    return {"ok": True, "error": None, "output": output, "version": status["version"]}
