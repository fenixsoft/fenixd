#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原型伺服与批注落盘（fenix-prototype · 任务 2.2）。

独立进程的 python 标准库简易 HTTP 服务器（零第三方依赖、零 dashboard 依赖、
不改 daemon）：静态伺服原型目录 + ``POST /feedback`` 接收批注落盘
``feedback.json``。

生命周期（PID 文件 = ``<原型目录>/.proto-server.json``）：

- 启动时 PID 文件存在且对应进程存活、且命令行核实为本脚本在伺服同一目录
  → **复用**既有实例与端口（不报端口冲突、不重复启动）；
- PID 文件存在但进程已死，或存活进程经命令行核实**不是**本脚本的实例
  （PID 被无辜进程复用，MUST NOT 误杀）→ 判定残留，清理 PID 文件**接管**；
- 正常退出 / SIGINT / SIGTERM / ``--stop`` 时回收 PID 文件，不留僵尸。

端口：默认 0 = OS 分配随机高端口；显式 ``--port`` 被占用时随机高端口重试。
绑定地址显式可配（``--host``），启动时打印完整访问 URL。

用法::

    python3 serve_prototype.py <原型目录> [--host 127.0.0.1] [--port N]
                               [--stop] [--json]

退出码：0 = started / reused / took-over / stopped；2 = 用法/目录错误。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import signal
import socket
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PID_FILE_NAME = ".proto-server.json"
FEEDBACK_FILE_NAME = "feedback.json"
PORT_RETRY_ATTEMPTS = 5
RANDOM_PORT_RANGE = (49200, 65499)
MAX_FEEDBACK_BODY_BYTES = 1 << 20  # 1MB
STOP_WAIT_SEC = 5
# 跨请求共享的批注写入锁：ThreadingHTTPServer 每个连接新建 handler 实例，
# 实例级锁没有跨连接互斥，并发 POST /feedback 会互相覆盖丢批注。
_FEEDBACK_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# PID 文件与进程核实
# ---------------------------------------------------------------------------

def pid_file_path(proto_dir: Path) -> Path:
    return proto_dir / PID_FILE_NAME


def read_pid_file(proto_dir: Path) -> dict | None:
    path = pid_file_path(proto_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or "pid" not in data:
            return None
        pid = data["pid"]
        if not isinstance(pid, int) or isinstance(pid, bool):
            return None  # pid 为 null/非数字字符串等非法类型：视作无 PID 文件
        return data
    except (OSError, ValueError):
        return None


def write_pid_file(proto_dir: Path, pid: int, host: str, port: int) -> Path:
    path = pid_file_path(proto_dir)
    path.write_text(json.dumps({
        "pid": pid,
        "host": host,
        "port": port,
        "proto_dir": str(proto_dir.resolve()),
        "started": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def remove_pid_file(proto_dir: Path) -> None:
    try:
        pid_file_path(proto_dir).unlink(missing_ok=True)
    except OSError:
        pass


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        # Windows 的 os.kill 对任意非 CTRL_* 信号值等价 TerminateProcess，
        # 绝不能拿它做探活（PID 被复用后会误杀无辜进程）；改用 OpenProcess 查询。
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # 存活但不可信号（他人进程）
    return True


def process_cmdline(pid: int) -> str:
    """读进程命令行（仅 Linux /proc；不可用时返回空串）。

    注意：macOS/Windows 等无 /proc 平台上恒返回空串——命令行核实整体失效，
    调用方（probe_existing）须据此显式标注降级，而非静默判 stale。
    """
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def probe_existing(proto_dir: Path, script_path: str) -> dict:
    """探测既有实例：``reuse``（存活且核实为本脚本伺服同目录）/ ``stale``（可接管）。

    存活但命令行核实不是本脚本实例（PID 被无辜进程复用）同样判 ``stale``——
    只清理 PID 文件并另起新实例，MUST NOT 杀掉无辜进程。
    """
    info = read_pid_file(proto_dir)
    if info is None:
        return {"state": "fresh", "info": None}
    try:
        pid = int(info.get("pid", 0))
    except (TypeError, ValueError):
        return {"state": "stale", "info": info, "reason": "PID 文件 pid 字段非法"}
    if not process_alive(pid):
        return {"state": "stale", "info": info, "reason": f"PID {pid} 进程已死"}
    cmdline = process_cmdline(pid)
    # 目录一致性以 PID 文件写入口径（resolve 后的 proto_dir）比对——cmdline 保存
    # 的是启动时原样输入，相对路径启动的旧实例不含 resolve 后的绝对路径；
    # 脚本身份仅作辅助确认（完整路径或脚本名均可，PID 文件已锚定同一目录）。
    recorded_dir = str(info.get("proto_dir", ""))
    script_identified = script_path in cmdline or Path(script_path).name in cmdline
    if script_identified and recorded_dir == str(proto_dir.resolve()):
        return {"state": "reuse", "info": info}
    if cmdline:
        return {"state": "stale", "info": info,
                "reason": f"PID {pid} 存活但非本原型服务器实例（命令行核实不符），不误杀、直接接管"}
    # 无 /proc 平台（macOS/Windows 等）命令行核实不可用：显式标注给调用方，
    # 而非静默判 stale（避免同目录每次重复叠加新实例、覆盖 PID 文件）。
    return {"state": "stale", "info": info,
            "reason": f"PID {pid} 存活但命令行核实不可用（本平台无 /proc，"
                      "无法确认为本脚本实例），保守判残留接管",
            "cmdline_check": "unavailable"}


def stop_server(proto_dir: Path, script_path: str) -> dict:
    """``--stop``：核实身份后 SIGTERM 回收；不留僵尸、不误杀无辜进程。"""
    probe = probe_existing(proto_dir, script_path)
    if probe["state"] == "fresh":
        return {"ok": False, "action": "not-running", "error": "无运行中的原型服务器"}
    if probe["state"] == "stale":
        remove_pid_file(proto_dir)
        return {"ok": True, "action": "cleaned-stale",
                "reason": probe.get("reason", "残留 PID 文件已清理")}
    pid = int(probe["info"]["pid"])
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        remove_pid_file(proto_dir)
        return {"ok": False, "action": "stop-failed", "error": str(exc)}
    import time
    deadline = time.time() + STOP_WAIT_SEC
    while time.time() < deadline:
        if not process_alive(pid):
            break
        time.sleep(0.1)
    if process_alive(pid):
        return {"ok": False, "action": "stop-timeout",
                "error": f"PID {pid} 在 {STOP_WAIT_SEC}s 内未退出"}
    remove_pid_file(proto_dir)
    return {"ok": True, "action": "stopped", "pid": pid}


# ---------------------------------------------------------------------------
# HTTP 服务
# ---------------------------------------------------------------------------

class PrototypeHandler(SimpleHTTPRequestHandler):
    """静态伺服原型目录 + POST /feedback 落 feedback.json。"""

    protocol_version = "HTTP/1.1"

    def __init__(self, *args, proto_dir: Path | None = None, **kwargs):
        self.proto_dir = proto_dir
        super().__init__(*args, directory=str(proto_dir), **kwargs)

    # 静默访问日志（原型伺服不需要每请求刷 stderr）
    def log_message(self, format, *args):  # noqa: A002 - 签名对齐基类
        pass

    # 目录请求一律 403：原型伺服只需 HTML 入口（目录下有 index.html 时根路径
    # 不受影响），关闭 stdlib 默认的目录列举，避免 --host 0.0.0.0 时 LAN 内
    # 可枚举原型目录全部文件（含 feedback.json 与 .proto-server.json）。
    def list_directory(self, path):
        self.send_error(403, "Directory listing is not allowed")
        return None

    # ── POST /feedback ────────────────────────────────────────────────
    def do_POST(self):
        if self.path.split("?")[0].rstrip("/") != "/feedback":
            self._send_json(404, {"ok": False, "error": "仅支持 POST /feedback"})
            return
        raw_length = self.headers.get("Content-Length")
        if not raw_length:
            # chunked 等无 Content-Length 的请求：显式 411，而非误报「请求体为空」
            self._send_json(411, {"ok": False, "error": "缺少 Content-Length 头"})
            return
        try:
            length = int(raw_length)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "Content-Length 非法"})
            return
        if length <= 0 or length > MAX_FEEDBACK_BODY_BYTES:
            self._send_json(413, {"ok": False,
                                  "error": f"请求体为空或超过 {MAX_FEEDBACK_BODY_BYTES}B 上限"})
            return
        raw = self.rfile.read(length)
        try:
            annotation = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._send_json(400, {"ok": False, "error": "批注不是合法 JSON"})
            return
        if not isinstance(annotation, dict) or not annotation.get("anchor") \
                or not annotation.get("text"):
            self._send_json(400, {"ok": False,
                                  "error": "批注必须含非空 anchor 与 text 字段"})
            return
        path = self._append_feedback(annotation)
        self._send_json(200, {"ok": True, "stored": str(path)})

    def _append_feedback(self, annotation: dict) -> Path:
        """追加一条批注进 feedback.json（锁内读改写，保留既有 dict 结构）。"""
        target = self.proto_dir / FEEDBACK_FILE_NAME
        with _FEEDBACK_LOCK:
            entries: list = []
            doc: dict | None = None  # dict 形态（如 annotator.js 本地导出）整体保留
            if target.is_file():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    if isinstance(existing, list):
                        entries = existing
                    elif isinstance(existing, dict) and isinstance(existing.get("feedback"), list):
                        doc = existing
                        entries = existing["feedback"]
                except (OSError, ValueError):
                    entries = []
            entries.append(annotation)
            if doc is not None:
                # dict 形态保留原结构整体回写，round 等同级字段不丢
                doc["feedback"] = entries
                payload: dict | list = doc
            else:
                payload = entries  # 裸 list 形态按现有逻辑回写数组
            # tmp 文件名带进程/线程唯一后缀：并发写各用各的 tmp，避免内容交错
            tmp = target.with_name(
                f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            tmp.replace(target)
        return target

    def _send_json(self, code: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def bind_server(host: str, port: int, proto_dir: Path) -> ThreadingHTTPServer:
    """绑定监听；显式端口被占用时按随机高端口重试（冲突重试要求）。"""
    attempts = [(port, 0)] if port == 0 else \
        [(port, 0)] + [(random.randint(*RANDOM_PORT_RANGE), i + 1)
                       for i in range(PORT_RETRY_ATTEMPTS)]
    last_exc: OSError | None = None
    for try_port, seq in attempts:
        try:
            server = ThreadingHTTPServer(
                (host, try_port), lambda *a, **kw: PrototypeHandler(*a,
                                                                    proto_dir=proto_dir, **kw))
            if seq:
                print(f"port-conflict-retry: 端口 {port} 被占用，改用随机端口 "
                      f"{try_port}（第 {seq} 次重试）", file=sys.stderr)
            return server
        except OSError as exc:
            last_exc = exc
    raise RuntimeError(f"端口绑定失败（含 {PORT_RETRY_ATTEMPTS} 次随机重试）：{last_exc}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def emit(result: dict, as_json: bool) -> None:
    text = json.dumps(result, ensure_ascii=False) if as_json else \
        json.dumps(result, ensure_ascii=False, indent=2)
    print(text, flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="fenix-prototype 原型服务器")
    parser.add_argument("proto_dir", help="原型目录（静态伺服根）")
    parser.add_argument("--host", default="127.0.0.1",
                        help="绑定地址（默认 127.0.0.1；外部访问显式配置，如 0.0.0.0）")
    parser.add_argument("--port", type=int, default=0,
                        help="监听端口（默认 0 = OS 分配随机高端口；被占用时随机重试）")
    parser.add_argument("--stop", action="store_true", help="停止既有实例并回收 PID 文件")
    parser.add_argument("--json", action="store_true", help="以单行 JSON 输出结果")
    args = parser.parse_args(argv)

    proto_dir = Path(args.proto_dir)
    if not proto_dir.is_dir():
        emit({"ok": False, "error": f"原型目录不存在：{args.proto_dir}"}, args.json)
        return 2
    script_path = str(Path(__file__).resolve())

    if args.stop:
        result = stop_server(proto_dir, script_path)
        emit(result, args.json)
        return 0 if result.get("ok") else 1

    # 生命周期：复用 / 接管 / 新起
    probe = probe_existing(proto_dir, script_path)
    if probe["state"] == "reuse":
        info = probe["info"]
        url = f"http://{info.get('host', args.host)}:{info.get('port')}/"
        emit({"ok": True, "action": "reused", "url": url, "pid": info.get("pid"),
              "pid_file": str(pid_file_path(proto_dir)),
              "note": "同目录已有存活实例，复用既有端口"}, args.json)
        return 0
    if probe["state"] == "stale":
        remove_pid_file(proto_dir)
        print(f"stale-takeover: {probe.get('reason', '')}", file=sys.stderr)

    server = bind_server(args.host, args.port, proto_dir)
    host, port = server.server_address[0], server.server_address[1]
    # 0.0.0.0 等通配绑定打印时保持用户输入（URL 用 localhost 提示可达性）
    display_host = args.host if host in ("0.0.0.0", "::") else str(host)
    url = f"http://{display_host}:{port}/"

    pid = os.getpid()
    pid_path = write_pid_file(proto_dir, pid, display_host, port)

    def _cleanup(*_a):
        # 只回收自己写入的 PID 文件：若已被继任者覆盖（pid 非本进程），不误删
        info = read_pid_file(proto_dir)
        if info is not None and info.get("pid") != pid:
            return
        remove_pid_file(proto_dir)

    import atexit
    atexit.register(_cleanup)

    def _on_signal(signum, _frame):
        # SystemExit 在主线程抛出 → serve_forever 退出 → finally 回收 PID 文件
        raise SystemExit(f"received signal {signum}")

    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)

    emit({"ok": True, "action": "started", "url": url, "pid": pid,
          "pid_file": str(pid_path), "proto_dir": str(proto_dir.resolve()),
          "feedback_file": str(proto_dir / FEEDBACK_FILE_NAME),
          "note": "Ctrl+C 或 --stop 回收"}, args.json)
    try:
        server.serve_forever()
    finally:
        _cleanup()
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
