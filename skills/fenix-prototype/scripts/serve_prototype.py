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
import contextlib
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

try:
    import fcntl  # 跨进程文件锁（Linux/macOS 可用）；Windows 无此模块走降级
except ImportError:  # 平台兜底：无 fcntl 时保持仅进程内互斥的历史行为
    fcntl = None  # type: ignore[assignment]

PID_FILE_NAME = ".proto-server.json"
FEEDBACK_FILE_NAME = "feedback.json"
PORT_RETRY_ATTEMPTS = 5
RANDOM_PORT_RANGE = (49200, 65499)
MAX_FEEDBACK_BODY_BYTES = 1 << 20  # 1MB
MAX_FEEDBACK_FILE_BYTES = 8 << 20  # 8MB：feedback.json 总量上限，超限拒绝写入
STOP_WAIT_SEC = 5
# 跨请求共享的批注写入锁：ThreadingHTTPServer 每个连接新建 handler 实例，
# 实例级锁没有跨连接互斥，并发 POST /feedback 会互相覆盖丢批注。
# 但线程锁只在单进程内互斥：同目录可能出现多个存活实例共写同一 feedback.json
# （无 /proc 平台命令行核实不可用时保守判残留接管、旧实例未被停止；以及
# probe→写 PID 文件之间无仲裁的并发启动），读-改-写仍会互相覆盖丢批注——
# 批注是本 skill 回流给 agent 的核心产物，写入须另加跨进程文件锁串行化。
_FEEDBACK_LOCK = threading.Lock()


@contextlib.contextmanager
def _feedback_file_lock(target: Path):
    """feedback.json 读改写的跨进程互斥：独占 flock 伴生锁文件 ``<名>.lock``。

    锁落在伴生文件而非 feedback.json 本身：目标文件经 tmp 原子 replace 换名，
    inode 随每次写入变化，锁旧 inode 保护不了新文件。无 fcntl 平台（Windows）
    或锁文件创建/加锁失败时降级为仅进程内互斥（历史行为），不让伺服崩溃。
    """
    if fcntl is None:
        yield
        return
    lock_path = target.with_name(target.name + ".lock")
    fd: int | None = None
    try:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(fd, fcntl.LOCK_EX)
        except OSError as exc:
            print(f"feedback-lock-unavailable: 跨进程锁不可用（{exc}），"
                  "降级为仅进程内互斥", file=sys.stderr)
            yield
            return
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        if fd is not None:
            os.close(fd)


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

class FeedbackWriteRejected(Exception):
    """feedback.json 拒绝写入（携带 HTTP 状态码），文案直接回给客户端。"""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class PrototypeHandler(SimpleHTTPRequestHandler):
    """静态伺服原型目录 + POST /feedback 落 feedback.json。"""

    protocol_version = "HTTP/1.1"
    # 慢客户端（声明 Content-Length 却缓慢发送 / 半开连接）会让 rfile.read
    # 无限期阻塞并占住 ThreadingHTTPServer 的 handler 线程；超时由基类断开。
    timeout = 30

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
        try:
            raw = self.rfile.read(length)
        except (TimeoutError, OSError):
            # 慢客户端读体超时（handler timeout=30 到点）/ 连接中断：回 408 并
            # 断开，不让未处理异常沿 socketserver 默认 handle_error 刷整栈
            # stderr（与 log_message 静默化「原型伺服不刷日志」的意图一致）。
            self.close_connection = True
            try:
                self._send_json(408, {"ok": False,
                                      "error": "请求体读取超时或连接中断"})
            except OSError:
                pass  # 响应写入本身也可能失败（对端已断）：尽力而为
            return
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
        try:
            path, note = self._append_feedback(annotation)
        except FeedbackWriteRejected as exc:
            self._send_json(exc.status, {"ok": False, "error": str(exc)})
            return
        payload = {"ok": True, "stored": str(path)}
        if note:
            payload["warning"] = note
        self._send_json(200, payload)

    def _append_feedback(self, annotation: dict) -> tuple[Path, str | None]:
        """追加一条批注进 feedback.json（锁内读改写，保留既有 dict 结构）。

        返回 (落盘路径, 非致命提示)；提示非 None 时随响应告知客户端
        （如原文件损坏已被隔离为 .bak）。
        """
        target = self.proto_dir / FEEDBACK_FILE_NAME
        # 先取跨进程文件锁再取线程锁：同目录多存活实例（无 /proc 平台保守接管
        # 或启动竞态双活）下读-改-写必须在进程间也串行，否则后写覆盖前写丢批注。
        with _feedback_file_lock(target), _FEEDBACK_LOCK:
            entries: list = []
            doc: dict | None = None  # dict 形态（如 annotator.js 本地导出）整体保留
            corrupt = False  # 原文件损坏/不可读：覆盖前先改名隔离，防丢可恢复历史
            if target.is_file():
                try:
                    existing = json.loads(target.read_text(encoding="utf-8"))
                    if isinstance(existing, list):
                        entries = existing
                    elif isinstance(existing, dict) and isinstance(existing.get("feedback"), list):
                        doc = existing
                        entries = existing["feedback"]
                    elif isinstance(existing, dict):
                        # dict 但无 feedback 列表（手工整理等其他合法 JSON object）：
                        # 无法安全并入，拒绝写入而非按空数组起步整体覆盖丢历史。
                        raise FeedbackWriteRejected(
                            409, "feedback.json 是不含 feedback 列表的 JSON object，"
                                 "拒绝追加；请先归档或手工合并该文件后重试")
                except (OSError, ValueError):
                    # 非法 JSON（ValueError）或读取失败（OSError）：文件里可能
                    # 仍有手工可恢复的批注历史，不能当空文件整体覆盖——标记待
                    # 隔离，写入前先改名 .bak（见 _isolate_corrupt_feedback）。
                    entries = []
                    corrupt = True
            entries.append(annotation)
            if doc is not None:
                # dict 形态保留原结构整体回写，round 等同级字段不丢
                doc["feedback"] = entries
                payload: dict | list = doc
            else:
                payload = entries  # 裸 list 形态按现有逻辑回写数组
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            if len(text.encode("utf-8")) > MAX_FEEDBACK_FILE_BYTES:
                # 文件无界增长会占满磁盘：超总量上限拒绝写入，提示归档
                raise FeedbackWriteRejected(
                    507, f"feedback.json 超过 {MAX_FEEDBACK_FILE_BYTES}B 总量上限，"
                         "拒绝写入；请归档历史批注后重试")
            note: str | None = None
            if corrupt:
                # 放在所有拒绝路径之后：仅在实际即将覆盖原文件时才动它
                note = self._isolate_corrupt_feedback(target)
            # tmp 文件名带进程/线程唯一后缀：并发写各用各的 tmp，避免内容交错
            tmp = target.with_name(
                f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            try:
                tmp.write_text(text, encoding="utf-8")
                tmp.replace(target)
            except OSError as exc:
                # 写盘失败（磁盘满/目录只读/目标被占用等）：尽力清理残留 tmp
                # 后转 FeedbackWriteRejected，走既有结构化错误通道回包，而非
                # 沿 do_POST 抛未处理异常栈且客户端收不到任何 JSON 响应。
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                raise FeedbackWriteRejected(
                    500, f"feedback.json 写入失败：{exc}") from exc
        return target, note

    def _isolate_corrupt_feedback(self, target: Path) -> str | None:
        """把损坏/不可读的 feedback.json 改名隔离为 .bak，返回客户端提示。

        隔离动作本身失败不阻塞新批注写入：降级为 stderr 提示并返回 None。
        """
        import time
        stamp = time.strftime("%Y%m%d-%H%M%S")
        # 隔离名带进程/线程唯一标识：时间戳秒级粒度内两次隔离也不重名覆盖
        backup = target.with_name(
            f"{target.name}.corrupt-{stamp}."
            f"{os.getpid()}.{threading.get_ident()}.bak")
        try:
            target.replace(backup)
        except OSError as exc:
            print(f"feedback-corrupt-isolate-failed: 无法隔离损坏的 "
                  f"{target.name}（{exc}），原内容将被新批注数组覆盖",
                  file=sys.stderr)
            return None
        return (f"原 {FEEDBACK_FILE_NAME} 无法解析（疑似损坏），"
                f"已隔离为 {backup.name}；请手工检查恢复其中的历史批注")

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
