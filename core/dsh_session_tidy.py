"""dsh_session_tidy.py — dsh web 会话归档投递器（add-dsh-session-title-archive 3.1）。

dsh harness run 终态后，其 dsh 会话仍留在 web 默认视图堆积。本模块把
``archiveSession`` 投递收敛为单一通道：同步子进程调用 dsh-bundle 的
session-tidy-helper（design D2：协议面在 helper 侧，daemon 零帧编解码），
失败转入**持久化重试队列**（JSONL，``<project_root>/.fenix/dsh_session_tidy/
pending.jsonl``——与 ``.fenix/runs``、``.fenix/maintenance_log.jsonl`` 同目录
惯例），daemon 重启后队列仍在，由后续投递事件驱动恢复消费。

退出码三分类（helper 契约，见 dsh-bundle/src/session-tidy-helper.ts 头注）：
  0 = 成功（含已归档幂等 no-op）——按成功，队列若有同 id 条目则移除；
  2 = 可重试（连接失败/超时/session-active/5xx）——入队/累加尝试计数，
      backoff 到期后由后续投递事件重试；放弃阈值（缺省 200 次尝试或
      30 天队龄，先到为准）触顶即移除并 WARN；
  1 = 致命（凭据缺失或形态不符/鉴权被拒/协议错/session-not-found）——
      重试永不成功，移除队列条目（若有）并 WARN 即止，不入队。
子进程自身异常（node 缺失、subprocess 超时、OSError）按可重试同面处置
（环境瞬态，入队兜底；受同一放弃阈值约束，不会无限堆积）。

并发 1：``submit`` 全程持锁串行（含 helper 子进程等待与队列读写）——
submitter 由 run 终态挂接按次新建（threading.Lock 随实例走，仅约束同
实例），队列读改写的跨实例互斥由队列路径 flock 承担
（``core.fs_utils.with_file_lock``，跨进程/跨线程）：队列文件读改写与
helper 调用在并行 run 终态下都不并发交错、依次排队；单次投递同步等待
受 helper ``--timeout``（缺省 10s）+ 子进程宽限约束。

重试消费策略（事件驱动，无后台线程）：每次 ``submit`` 先抽干最多
``drain_limit`` 条到期条目再投递新会话——daemon 重启后第一次新 run 终态
即恢复消费（spec「daemon 重启不丢」）；无新 run 时队列静置，符合「web
恢复后队列清空」的兜底定位而非时效承诺。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from core.fs_utils import atomic_write_text, with_file_lock

#: 队列目录与文件（相对 <project_root>/.fenix/，对齐 runs/maintenance_log 惯例）。
QUEUE_DIRNAME = "dsh_session_tidy"
QUEUE_FILENAME = "pending.jsonl"

#: helper 产物入口（仓库布局 dsh-bundle/dist/session-tidy-helper.mjs；
#: .mts 直跑不可用故由 build copyFileSync 产出 .mjs 双产物之一）。
HELPER_RELATIVE_PATH = Path("dsh-bundle") / "dist" / "session-tidy-helper.mjs"

#: 单次投递缺省超时（秒；helper 侧同值——子进程宽限另加）。
DEFAULT_TIMEOUT_SECONDS = 10.0

#: 放弃阈值缺省：200 次尝试或 30 天队龄，先到为准。
DEFAULT_MAX_ATTEMPTS = 200
DEFAULT_MAX_AGE_DAYS = 30.0

#: 单次 submit 抽干的到期条目上限（终态车道同步等待的上界约束）。
DEFAULT_DRAIN_LIMIT = 1

#: backoff 序列基数与上限（秒）：30s 起指数退避，封顶 1h。
BACKOFF_BASE_SECONDS = 30.0
BACKOFF_MAX_SECONDS = 3600.0

#: helper 子进程宽限（秒）：helper 内部已有 --timeout 自截断，进程级宽限
#: 只防 node 卡死不退出（如加载期 hang）——超时即按可重试处置。
SUBPROCESS_GRACE_SECONDS = 5.0

#: 退出码（与 helper EXIT_OK/EXIT_FATAL/EXIT_RETRYABLE 逐字对齐）。
EXIT_OK = 0
EXIT_FATAL = 1
EXIT_RETRYABLE = 2

_logger = logging.getLogger("fenixd.dsh_session_tidy")


def _default_logger() -> Any:
    """runner 未注入 logger 时的独立落盘面（standalone/测试形态）。"""

    class _StdLogger:
        def warning(self, component: str, message: str, context: dict | None = None) -> None:
            _logger.warning("[%s] %s", component, message)

        def info(self, component: str, message: str, context: dict | None = None) -> None:
            _logger.info("[%s] %s", component, message)

    return _StdLogger()


def resolve_dsh_home(dsh_home: str = "") -> Path:
    """dsh home 解析（agent.dsh_home 缺省面复用）：显式配置 > ``$DSH_HOME``
    环境变量 > ``~/.dsh``（dsh 官方缺省）。helper 的 ``--secret-file`` 取
    此处结果拼 ``.credentials.yaml``。"""
    if dsh_home and str(dsh_home).strip():
        return Path(str(dsh_home).strip())
    env_home = os.environ.get("DSH_HOME", "").strip()
    if env_home:
        return Path(env_home)
    return Path.home() / ".dsh"


def default_helper_path() -> Path:
    """helper 产物绝对路径（仓库布局推演：core/ 的上级 + dsh-bundle/dist）。"""
    return Path(__file__).resolve().parent.parent / HELPER_RELATIVE_PATH


class DshSessionTidySubmitter:
    """终态会话归档投递器：helper 同步调用 + 持久化重试队列（并发 1）。"""

    def __init__(
        self,
        project_root: str | Path,
        web_url: str,
        dsh_home: str = "",
        logger: Any = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_age_days: float = DEFAULT_MAX_AGE_DAYS,
        drain_limit: int = DEFAULT_DRAIN_LIMIT,
        helper_path: str | Path | None = None,
        node_executable: str = "node",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._project_root = Path(project_root)
        self._web_url = str(web_url)
        self._credentials_file = resolve_dsh_home(dsh_home) / ".credentials.yaml"
        self._logger = logger if logger is not None else _default_logger()
        self._timeout_seconds = float(timeout_seconds)
        self._max_attempts = int(max_attempts)
        self._max_age_seconds = float(max_age_days) * 86400.0
        self._drain_limit = max(1, int(drain_limit))
        self._helper_path = Path(helper_path) if helper_path else default_helper_path()
        self._node = node_executable
        self._clock = clock
        self._lock = threading.Lock()

    # ── 队列文件（JSONL round-trip）─────────────────────────────────────

    @property
    def queue_path(self) -> Path:
        return self._project_root / ".fenix" / QUEUE_DIRNAME / QUEUE_FILENAME

    def _load_entries(self) -> list[dict]:
        """读全部待重试条目（损坏行跳过不抛——半行 JSON 来自崩溃残留，读侧
        跳过即可；数值字段非法的条目同样逐条跳过并 WARN 留痕——单条损坏
        不得在 due 过滤/放弃判定处抛错扩散到整条投递通道）。"""
        path = self.queue_path
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except UnicodeDecodeError as e:
            self._logger.warning(
                "dsh_session_tidy",
                f"重试队列文件编码损坏（非合法 UTF-8，按空队列降级）: {e}")
            return []
        except OSError as e:
            self._logger.warning(
                "dsh_session_tidy", f"重试队列读取失败（按空队列降级）: {e}")
            return []
        entries: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not (isinstance(entry, dict) and entry.get("session_id")):
                continue
            normalized = self._normalize_entry(entry)
            if normalized is None:
                self._logger.warning(
                    "dsh_session_tidy",
                    f"重试队列损坏条目跳过（数值字段非法，防单条毒化整通道）: "
                    f"session_id={entry.get('session_id')}",
                )
                continue
            entries.append(normalized)
        return entries

    @staticmethod
    def _normalize_entry(entry: dict) -> dict | None:
        """数值字段逐条装载守卫（attempts/enqueued_at/next_attempt_at）：
        存在但不可数值化（外部编辑/写残变体）→ 返回 None（调用方跳过该
        条）；数值字符串容错归一为数值；缺省字段不动（下游 ``.get`` 缺省
        面接管）。"""
        for key, cast in (("attempts", int), ("enqueued_at", float),
                          ("next_attempt_at", float)):
            if key not in entry:
                continue
            try:
                entry[key] = cast(entry[key])
            except (TypeError, ValueError):
                return None
        return entry

    def _save_entries(self, entries: list[dict]) -> None:
        """全量原子重写（fs_utils.atomic_write_text：mkstemp 唯一临时名 +
        os.replace；空队列时落空文件等价清空）。固定 ``.tmp`` 临时名在并发
        写者下会互相截断（该原语注释点名要消灭的形态），不复用。"""
        payload = "".join(
            json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries
        )
        atomic_write_text(self.queue_path, payload)

    # ── helper 调用 ─────────────────────────────────────────────────────

    def _invoke_helper(self, session_id: str) -> tuple[int, str]:
        """子进程调用 helper，返回 ``(exit_code, detail)``。子进程级异常
        （node 缺失/超时/OSError）折叠为 ``(EXIT_RETRYABLE, 原因)``——环境
        瞬态入队兜底，受放弃阈值约束。"""
        argv = [
            self._node,
            str(self._helper_path),
            "--url", self._web_url,
            "--secret-file", str(self._credentials_file),
            "--session-id", str(session_id),
            "--timeout", str(max(1, round(self._timeout_seconds))),
        ]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds + SUBPROCESS_GRACE_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return EXIT_RETRYABLE, f"helper 子进程超时（>{self._timeout_seconds + SUBPROCESS_GRACE_SECONDS:.0f}s）"
        except OSError as e:
            return EXIT_RETRYABLE, f"helper 子进程启动失败: {e}"
        detail = (proc.stdout or "").strip()
        if detail:
            try:
                detail = json.loads(detail.splitlines()[-1]).get("detail", detail)
            except (ValueError, AttributeError, IndexError):
                pass
        if not detail:
            detail = (proc.stderr or "").strip()[:300] or f"helper 退出码 {proc.returncode}（无输出）"
        return proc.returncode, detail

    # ── 投递与重试 ──────────────────────────────────────────────────────

    @staticmethod
    def _backoff_seconds(attempts: int) -> float:
        """第 attempts 次失败后的退避秒数：30s·2^(n-1) 封顶 1h。"""
        return min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts - 1)), BACKOFF_MAX_SECONDS)

    def _should_abandon(self, entry: dict, now: float) -> bool:
        """放弃判据（先到为准）：尝试次数触顶或队龄超限。"""
        attempts = int(entry.get("attempts", 0))
        enqueued_at = float(entry.get("enqueued_at", now))
        return attempts >= self._max_attempts or (now - enqueued_at) >= self._max_age_seconds

    def _abandon(self, entry: dict, now: float) -> None:
        self._logger.warning(
            "dsh_session_tidy",
            f"会话 {entry.get('session_id')} 重试放弃：attempts="
            f"{entry.get('attempts', 0)} 队龄={((now - float(entry.get('enqueued_at', now))) / 86400.0):.1f}天 "
            f"末次 detail={str(entry.get('last_detail', ''))[:200]}",
        )

    def _process_retryable(self, session_id: str, detail: str, now: float) -> str:
        """可重试结果处置：入队或累加计数；放弃阈值触顶即移除 + WARN。
        返回处置结果（"queued" | "abandoned"）。"""
        entries = self._load_entries()
        existing = next((e for e in entries if e.get("session_id") == session_id), None)
        if existing is None:
            entry = {
                "session_id": session_id,
                "enqueued_at": now,
                "attempts": 1,
                "next_attempt_at": now + self._backoff_seconds(1),
                "last_exit": EXIT_RETRYABLE,
                "last_detail": detail,
            }
            # 非缺省阈值（如 max_attempts=1 / max_age_days=0）下首败即触顶：
            # 与 existing 分支对称，不入队直接放弃。
            if self._should_abandon(entry, now):
                self._abandon(entry, now)
                return "abandoned"
            entries.append(entry)
        else:
            existing["attempts"] = int(existing.get("attempts", 0)) + 1
            existing["last_exit"] = EXIT_RETRYABLE
            existing["last_detail"] = detail
            existing["next_attempt_at"] = now + self._backoff_seconds(existing["attempts"])
            if self._should_abandon(existing, now):
                entries.remove(existing)
                self._save_entries(entries)
                self._abandon(existing, now)
                return "abandoned"
        self._save_entries(entries)
        return "queued"

    def _drain_due_entries(self, now: float) -> None:
        """抽干到期条目（至多 drain_limit 条）：helper 重调 + 按退出码处置。"""
        entries = self._load_entries()
        if not entries:
            return
        due = [e for e in entries if float(e.get("next_attempt_at", 0)) <= now]
        for entry in due[: self._drain_limit]:
            session_id = str(entry.get("session_id"))
            exit_code, detail = self._invoke_helper(session_id)
            fresh = self._load_entries()
            current = next((e for e in fresh if e.get("session_id") == session_id), None)
            if current is None:
                continue  # 并发窗口内已被他处处置（并发 1 下理论不可达，防御）
            if exit_code == EXIT_OK:
                # 「已归档」按成功：队列条目移除（spec：web 恢复后队列清空）。
                fresh.remove(current)
                self._save_entries(fresh)
                self._logger.info(
                    "dsh_session_tidy",
                    f"重试成功：会话 {session_id} 已归档（attempts={current.get('attempts', 0)}）",
                )
            elif exit_code == EXIT_FATAL:
                fresh.remove(current)
                self._save_entries(fresh)
                self._logger.warning(
                    "dsh_session_tidy",
                    f"重试致命放弃：会话 {session_id} detail={detail[:200]}（重试永不成功，不入队）",
                )
            else:
                current["attempts"] = int(current.get("attempts", 0)) + 1
                current["last_exit"] = EXIT_RETRYABLE
                current["last_detail"] = detail
                current["next_attempt_at"] = now + self._backoff_seconds(current["attempts"])
                if self._should_abandon(current, now):
                    fresh.remove(current)
                    self._save_entries(fresh)
                    self._abandon(current, now)
                else:
                    self._save_entries(fresh)

    def submit(self, session_id: str) -> str:
        """投递单会话归档。全程持锁（实例 threading.Lock + 队列路径 flock
        双层，跨实例互斥——submitter 按 run 终态逐次新建，单靠实例锁挡不住
        并行终态的另一实例）；永不抛异常——意外异常把该会话以可重试条目
        落盘重试队列（入队兜底）后返回 "queued"；入队自身失败才降级为仅
        WARN 并返回 "error"（未入队），run 主链路不感知。

        返回处置结果字符串："archived"（成功/幂等）|"queued"（入队重试）
        |"abandoned"（放弃阈值触顶）|"fatal"（致命失败不入队）
        |"error"（意外异常且兜底入队自身失败，未入队）。"""
        try:
            with self._lock:
                # flock 以队列路径加锁（.<name>.lock，跨进程/跨线程），补齐
                # 「锁随实例走」留下的跨实例队列读改写交错窗口。
                return with_file_lock(
                    self.queue_path, lambda: self._submit_locked(session_id))
        except Exception as e:  # noqa: BLE001 — 投递绝不影响 run 主链路
            try:
                self._logger.warning(
                    "dsh_session_tidy",
                    f"会话 {session_id} 投递意外异常（入队兜底，不影响 run 主链路）: {e}",
                )
            except Exception:  # noqa: BLE001 — logger 二次异常静默
                pass
            # 入队兜底落到实处：意外异常下该会话仍按 _process_retryable 的
            # 条目形态落盘重试队列（否则持久化队列「daemon 重启不丢、事件
            # 驱动恢复消费」的兜底对本会话失效）；入队自身失败（如
            # _save_entries 盘满 OSError）才降级为仅 WARN，返回 "error"
            # 如实表示未入队，不以 queued 谎报兜底已生效。
            try:
                with self._lock:
                    return with_file_lock(
                        self.queue_path,
                        lambda: self._process_retryable(
                            session_id, f"submit 意外异常兜底: {str(e)[:300]}",
                            self._clock()),
                    )
            except Exception:  # noqa: BLE001 — 入队自身失败：仅 WARN 即止
                return "error"

    def _submit_locked(self, session_id: str) -> str:
        """flock 持有下的投递主链路：先抽干到期重试（事件驱动消费；含
        daemon 重启恢复消费），再投递新会话——旧账不挤占新投递的同步等待
        预算（抽干有 drain_limit 上界）。"""
        now = self._clock()
        self._drain_due_entries(now)
        exit_code, detail = self._invoke_helper(session_id)
        if exit_code == EXIT_OK:
            # 成功（含已归档幂等）：清队列同 id 残留条目（若有）。
            self._drop_entry(session_id)
            return "archived"
        if exit_code == EXIT_FATAL:
            self._drop_entry(session_id)
            self._logger.warning(
                "dsh_session_tidy",
                f"会话 {session_id} 归档致命失败（不入队）：{detail[:200]}",
            )
            return "fatal"
        return self._process_retryable(session_id, detail, now)

    def _drop_entry(self, session_id: str) -> None:
        """移除同 id 队列条目（成功/致命后的队列卫生；文件缺失视为无队列）。"""
        entries = self._load_entries()
        remaining = [e for e in entries if e.get("session_id") != session_id]
        if len(remaining) != len(entries):
            self._save_entries(remaining)

    def pending_count(self) -> int:
        """队列现存条目数（观测面；读失败按 0 降级）。"""
        try:
            with self._lock:
                return len(self._load_entries())
        except Exception:  # noqa: BLE001
            return 0
