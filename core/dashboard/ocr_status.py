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

import shutil
import subprocess

# 安装命令的包名（固定字面量，不拼接任何用户输入）
OCR_NPM_PACKAGE = "@alibaba-group/open-code-review"

# `ocr --version` 解析超时（秒）——版本探测失败不影响 installed 判定
_VERSION_TIMEOUT = 5
# `npm install -g` 超时（秒）——全局安装含下载与解包，给足余量
_INSTALL_TIMEOUT = 300


def _ocr_version(ocr_bin: str) -> str | None:
    """跑 `ocr --version` 取首行版本描述；失败/超时返回 None。

    首行形如 "open-code-review v1.12.5 (189be5b024) linux/amd64"，原样返回该行
    （UI 直接展示，不再二次解析版本号格式，避免与上游输出格式耦合）。
    """
    try:
        r = subprocess.run(
            [ocr_bin, "--version"],
            capture_output=True,
            text=True,
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
    """
    try:
        r = subprocess.run(
            ["npm", "install", "-g", OCR_NPM_PACKAGE],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "error": f"安装超时（>{timeout}s）",
            "output": "",
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
