"""architecture_routes.py — 项目架构图 (add-project-architecture-tab) routes。

承载 3 个端点：
- GET  /api/architecture/status  （query project）→ 生成状态（四态机）
- POST /api/architecture/refresh （query project）→ 受理触发生成（后台线程）
- GET  /api/architecture/diagram （query project）→ 下发 diagram.html（text/html）

端点 handler 走既有 mixin 形态（self._json / self._error），project 均从
query string 解析，不消费请求体（对齐 regression_routes POST 契约；残留
body 字节由派发层 _drain_remaining_request_body 排空）。

生成机制（design D1/D3）：POST 只受理——起 daemon 守护线程跑一次性
headless claude（vendored archify skill 指引原文注入提示词，分析项目代码
→ 自包含交互式 HTML；零联网安装、零用户环境依赖），MUST NOT 在 HTTP
线程内同步等待（全库分析可达 10–30 分钟，同步 HTTP 在浏览器休眠/代理
超时下不可靠）。前端 generating 期间 3s 轮询 status。

产物与状态存储（design D2）：项目根 ``.fenix/architecture/{diagram.html,
status.json}``（gitignored 运行时产物）；status.json 每次状态迁移 tmp+rename
原子写，结构含 ``state/generated_at/started_at/error/duration_ms/
component_count``。dashboard 进程内模块级 ``ArchitectureManager`` 持
per-project 单飞锁与在飞进程句柄，为该目录的唯一写者（单写者原则）。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ── 模块常数（不新增配置项，对齐 autodraft 先例）─────────────────────

# 单次生成的硬超时（秒）。archify 全库分析 10–30 分钟量级，1800s 给足余量；
# 超时以进程组方式击杀（design D3，防孙进程残留）。
GEN_TIMEOUT_SECONDS = 1800

# 生成完成 marker 协议（autodraft marker 范式）：stdout 末行
# ``ARCHIFY_DONE <组件数>``。
ARCHIFY_MARKER_PREFIX = "ARCHIFY_DONE"

# 形态契约：核心组件数允许区间（spec「图形态契约」）。能提取组件数时越界
# 判 failed；无法提取（marker 缺失）记 component_count=null 放行（design D5）。
COMPONENT_COUNT_MIN = 8
COMPONENT_COUNT_MAX = 16

# 产物相对路径（项目根下，gitignored 运行时目录族）。
ARCHITECTURE_DIR = ".fenix/architecture"
STATUS_FILENAME = "status.json"
DIAGRAM_FILENAME = "diagram.html"

# env 剔除口径同 SessionManager._BANNED_ENV_KEYS（D1.11）：一次性架构图
# 生成与 agent-run 无关，MUST NOT 注入 agent-run 专用上下文。
_BANNED_ENV_KEYS = frozenset({
    "FENIX_RUN_PROJECT_ROOT",
    "FENIX_RUN_WORKTREE",
    "CLAUDE_CODE_ENABLE_TODO_TOOLS",
})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _build_spawn_env() -> dict[str, str]:
    """构建 claude 子进程环境：os.environ.copy() 减 agent-run 专用键。"""
    env = os.environ.copy()
    for key in _BANNED_ENV_KEYS:
        env.pop(key, None)
    return env


def _vendored_skill_root() -> Path:
    """archify vendored 包根（design D2）：``<repo>/vendor/archify``。

    以本文件位置锚定仓库根（routes → dashboard → core → 仓库根），脱离
    daemon 进程 cwd 依赖（worktree 内跑单测同样成立）。skill 以 vendored
    形式随库分发（VENDORED.md 溯源），生成链路零联网安装、零用户环境依赖。
    """
    return Path(__file__).resolve().parents[3] / "vendor" / "archify"


def _skill_ready() -> bool:
    """vendored 包完整性检查（design D3）：SKILL.md 存在且非空。

    缺失/为空属部署损坏，由调用方判 failed（不触发任何安装动作）。
    """
    skill_md = _vendored_skill_root() / "SKILL.md"
    try:
        return skill_md.is_file() and skill_md.stat().st_size > 0
    except OSError:
        return False


_SKILL_VENDORED_MISSING_ERROR = (
    "archify skill 包缺件（vendor/archify/SKILL.md 缺失或为空），属部署损坏，"
    "请对照 vendor/archify/VENDORED.md 恢复包后重试"
)


def _build_prompt(proot: Path, project_name: str) -> str:
    """中文生成提示词（design D4/D5）：vendored SKILL.md 指引原文注入 +
    包根绝对路径 + 五项形态约束 + 产物写盘绝对路径 + ARCHIFY_DONE marker
    协议。自包含，不依赖目标项目内有任何 fenixd 文件、不依赖用户环境已装
    skill（指引原文直接注入，claude 读 vendored 伴生文件走绝对路径）。"""
    out = (proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME).resolve()
    skill_root = _vendored_skill_root()
    skill_md = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    return f"""分析当前项目（{project_name}，项目根即当前工作目录）的代码，
产出一张高层**运行时架构图**：核心组件有哪些、主链路怎么跑、依赖了哪些外部服务、
信任边界在哪。

【archify skill 指引（vendored 随库分发，无需安装，全程无网络依赖）】
包根目录（绝对路径）：{skill_root}
- 下方指引原文中出现的相对路径均相对该包根目录解析；
- 指引中的校验步骤用 `node bin/archify.mjs validate …` 本地执行（无网络）。

<archify-skill>
{skill_md}
</archify-skill>

【产物要求】
- 输出为单个自包含 HTML 文件（全部 CSS/JS 内联，不引用任何外部资源），写入绝对路径：
  {out}
- 图形形态必须同时满足以下五项约束：
  1. 只保留 8–16 个核心组件（模块/服务/数据层等高层抽象），不要穷举目录与文件；
  2. 突出且仅突出一条主要路径（主链路高亮，其余连线弱化处理）；
  3. 标出外部依赖（第三方服务/外部存储等）与信任边界；
  4. 辅助信息放进说明卡片（note card）承载，不要为承载说明而继续增加连线；
  5. 节点与说明文字全部使用中文标注。

【完成标记】写盘成功后，stdout 的最后一行必须输出且仅输出一个 marker：
ARCHIFY_DONE <组件数>
其中 <组件数> 为图中核心组件的实际数量（整数）。"""


def _status_payload(
    state: str,
    *,
    started_at: str | None = None,
    generated_at: str | None = None,
    error: str | None = None,
    duration_ms: int | None = None,
    component_count: int | None = None,
) -> dict:
    """status.json 全字段形态（task 1.1：六键恒在，未 applicable 为 null）。"""
    return {
        "state": state,
        "started_at": started_at,
        "generated_at": generated_at,
        "error": error,
        "duration_ms": duration_ms,
        "component_count": component_count,
    }


def _write_status(proot: Path, payload: dict) -> None:
    """status.json 原子写（tmp + os.replace，design D2）。"""
    arch = proot / ARCHITECTURE_DIR
    arch.mkdir(parents=True, exist_ok=True)
    tmp = arch / (STATUS_FILENAME + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, arch / STATUS_FILENAME)


def _read_status(proot: Path) -> dict | None:
    """读 status.json；缺失/损坏/非 dict → None（读侧按 none 态兜底）。"""
    path = proot / ARCHITECTURE_DIR / STATUS_FILENAME
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _extract_component_count(stdout: str | None) -> int | None:
    """从 stdout 尾部提取 ``ARCHIFY_DONE <组件数>``（autodraft marker 范式：
    claude 可能用代码块包裹输出，剥反引号后前缀匹配）；协议约定 marker 为
    stdout 最后一行，倒序扫描取最后一条可解析出整数的 marker 行（正文回显
    的协议说明文字不可解析，跳过不干扰判定）；缺失 → None。"""
    tail = (stdout or "")[-2000:]
    for line in reversed(tail.splitlines()):
        s = line.strip().strip("`").strip()
        if s.startswith(ARCHIFY_MARKER_PREFIX):
            try:
                return int(s[len(ARCHIFY_MARKER_PREFIX):].strip())
            except ValueError:
                continue
    return None


def _is_selfcontained_html(path: Path) -> bool:
    """自包含 HTML 特征（task 1.5）：文件起始（允许 BOM/空白）为
    ``<!DOCTYPE html`` 或 ``<html`` 前缀（大小写不敏感）。"""
    try:
        with path.open("rb") as f:
            head = f.read(512)
    except OSError:
        return False
    text = head.decode("utf-8", errors="replace").lstrip("﻿ \t\r\n").lower()
    return text.startswith("<!doctype html") or text.startswith("<html")


def _judge_artifact(
    diagram_path: Path, returncode: int, stdout: str | None, logger=None
) -> tuple[str, str | None, int | None]:
    """产物权威判定链（design D5，不信 claude 自述）。

    退出码 → 产物存在且非空 → 自包含 HTML 特征 → 组件数 ∈ [8,16]。
    返回 (state, error, component_count)；marker 缺失时组件数记 None 放行
    （形态校验尽力而为，产物可用性优先）。
    """
    if returncode != 0:
        return "failed", f"claude 进程非零退出（exit={returncode}），产物不可信", None
    if not diagram_path.is_file() or diagram_path.stat().st_size == 0:
        return (
            "failed",
            f"生成产物缺失或为空（{ARCHITECTURE_DIR}/{DIAGRAM_FILENAME}）",
            None,
        )
    if not _is_selfcontained_html(diagram_path):
        return (
            "failed",
            "生成产物不是自包含 HTML（缺少 <!DOCTYPE html>/<html> 起始特征）",
            None,
        )
    count = _extract_component_count(stdout)
    if count is None:
        # marker 缺失 → 无法机械校验组件数，记 null 放行（design D5）
        return "ready", None, None
    if not (COMPONENT_COUNT_MIN <= count <= COMPONENT_COUNT_MAX):
        if logger is not None:
            logger.warning(
                "architecture_routes",
                f"架构图组件数越界（count={count}，"
                f"allowed=[{COMPONENT_COUNT_MIN}, {COMPONENT_COUNT_MAX}]）",
            )
        return (
            "failed",
            f"架构图组件数为 {count}，超出允许范围 "
            f"[{COMPONENT_COUNT_MIN}, {COMPONENT_COUNT_MAX}]（形态契约）",
            count,
        )
    return "ready", None, count


class ArchitectureManager:
    """架构图生成管理器（dashboard 进程内单例）。

    持 per-project 单飞锁与在飞进程句柄（design D2：唯一写者）；生成状态经
    status.json 原子写持久化，刷新页面/daemon 重启不丢态（重启残留的
    generating 由读侧合成 failed，spec「生成生命周期治理」）。
    """

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}
        self._procs: dict[str, subprocess.Popen] = {}

    def _key(self, proot: Path) -> str:
        return str(proot.resolve())

    def _lock_for(self, proot: Path) -> threading.Lock:
        key = self._key(proot)
        with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._locks[key] = lock
            return lock

    def in_flight(self, proot: Path) -> bool:
        """该项目是否有在飞生成（单飞锁被后台线程持有）。"""
        return self._lock_for(proot).locked()

    def status(self, proot: Path) -> dict:
        """读侧状态（四态机）。

        - status.json 缺失/损坏 → ``none``（全字段 null）；
        - 残留 ``generating`` 且在飞线程/进程不在（daemon 曾重启）→ 合成
          ``failed``（中断），MUST NOT 永久停留在 generating。

        在飞判定 MUST 先于读文件：终态写入严格先于锁释放（_run_generation
        各路径 _finish 后才在 finally 释放锁），故「锁未被持有」即终态必已
        落盘——此时读到 generating 只能是重启残留。反之先读后判存在竞态：
        读到 generating 后生成线程才完成「写终态+释放锁」，会把已完成的
        生成误合成为中断（实测假失败）。
        """
        alive = self._in_flight_alive(proot)
        data = _read_status(proot)
        if data is None:
            return _status_payload("none")
        state = str(data.get("state") or "")
        if state == "generating" and not alive:
            synth = _status_payload(
                "failed",
                started_at=data.get("started_at"),
                error="生成被中断（daemon 重启或后台线程已不存在），请重新点击「刷新架构图」",
            )
            return synth
        # 补齐六键（旧版残留文件可能缺键）
        full = _status_payload(state or "none")
        for key in ("started_at", "generated_at", "error", "duration_ms", "component_count"):
            if key in data:
                full[key] = data.get(key)
        return full

    def _in_flight_alive(self, proot: Path) -> bool:
        """在飞判定：单飞锁被持有，或在飞进程句柄仍存活。"""
        if self.in_flight(proot):
            return True
        with self._guard:
            proc = self._procs.get(self._key(proot))
        return proc is not None and proc.poll() is None

    def refresh(
        self, proot: Path, project_name: str, logger=None
    ) -> tuple[bool, bool, str | None]:
        """受理一次生成（POST refresh，design D1：只受理不同步等待）。

        返回 (accepted, conflict, error)：
        - 受理 → (True, False, None)：写入 generating 态并起 daemon 守护线程；
        - 单飞冲突（在飞时再触发）→ (False, True, msg)→调用方回 409；
        - 状态写盘失败 → (False, False, msg)→调用方回 500；
        - 线程启动失败 → (False, False, msg)→调用方回 500（回写 failed 终态
          并释放单飞锁，不留卡死 generating）。
        """
        lock = self._lock_for(proot)
        if not lock.acquire(blocking=False):
            return False, True, "该项目的架构图生成正在进行中，请稍候"
        started_at = _utcnow_iso()
        try:
            _write_status(proot, _status_payload("generating", started_at=started_at))
        except OSError as exc:
            lock.release()
            return False, False, f"架构图状态写入失败: {exc}"
        thread = threading.Thread(
            target=self._run_generation,
            args=(proot, project_name, started_at, lock, logger),
            daemon=True,
            name=f"archify-gen-{project_name}",
        )
        try:
            thread.start()
        except Exception as exc:  # noqa: BLE001 — 系统线程资源耗尽等 RuntimeError
            # code-review item 1295fb028cb4：start() 抛异常若放任逃逸，单飞锁
            # 不释放、status.json 恒卡 generating——同进程内 in_flight() 恒真，
            # refresh 全 409，仅 daemon 重启才由读侧合成 failed，不可自愈。
            # 终态写入 MUST 严格先于锁释放（status() 读侧契约：「锁未被持有」
            # 即终态必已落盘），故先 _finish 再 release；随后按既有失败形态
            # (False, False, msg) 交调用方回 500。
            if logger is not None:
                logger.warning(
                    "architecture_routes",
                    f"架构图生成线程启动失败（project={project_name}）: "
                    f"{type(exc).__name__}: {exc!r}",
                )
            try:
                self._finish(
                    proot,
                    started_at,
                    time.monotonic(),
                    "failed",
                    error=f"后台生成线程启动失败（{type(exc).__name__}），请重试",
                )
            finally:
                lock.release()
            return False, False, "架构图生成线程启动失败，请重试"
        return True, False, None

    def _run_generation(
        self,
        proot: Path,
        project_name: str,
        started_at: str,
        lock: threading.Lock,
        logger=None,
    ) -> None:
        """生成线程体（design D3/D5）：vendored 包完整性检查 → spawn →
        超时治理 → 权威判定链 → 状态落盘。锁在线程结束时释放（finally）。"""
        key = self._key(proot)
        t0 = time.monotonic()
        diagram_path = proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME
        try:
            # ── 1) vendored archify 包完整性检查（design D3）─────────
            if not _skill_ready():
                self._finish(
                    proot, started_at, t0, "failed",
                    error=_SKILL_VENDORED_MISSING_ERROR,
                )
                return

            # ── 2) spawn headless claude（design D3）─────────────────
            prompt = _build_prompt(proot, project_name)
            try:
                diagram_path.parent.mkdir(parents=True, exist_ok=True)
                proc = subprocess.Popen(
                    ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"],
                    cwd=str(proot),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    env=_build_spawn_env(),
                    # 独立会话组（autodraft 同款）：超时可 killpg 整组清场，
                    # 杜绝只杀直接子进程留下的孤儿孙进程
                    start_new_session=True,
                )
            except Exception as exc:  # noqa: BLE001 — CLI 不存在等 spawn 失败
                if logger is not None:
                    logger.warning(
                        "architecture_routes",
                        f"调用 claude CLI 异常（project={project_name}）: "
                        f"{type(exc).__name__}: {exc!r}",
                    )
                self._finish(
                    proot, started_at, t0, "failed", error="调用 claude CLI 失败"
                )
                return
            with self._guard:
                self._procs[key] = proc
            stdout = None
            try:
                stdout, stderr = proc.communicate(timeout=GEN_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                # 进程组击杀（autodraft 同款）：claude 派生的 bash/写文件孙进程
                # 一并终止，锁释放后无在途写者
                try:
                    pgid = os.getpgid(proc.pid)
                    os.killpg(pgid, signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    try:
                        proc.kill()
                    except Exception:  # noqa: BLE001
                        pass
                try:
                    proc.communicate()  # 回收已杀进程、排干管道
                except Exception:  # noqa: BLE001
                    pass
                if logger is not None:
                    logger.warning(
                        "architecture_routes",
                        f"架构图生成超时（>{GEN_TIMEOUT_SECONDS}s，"
                        f"project={project_name}）；已终止整个进程组",
                    )
                self._finish(
                    proot,
                    started_at,
                    t0,
                    "failed",
                    error=f"生成超时（>{GEN_TIMEOUT_SECONDS}s 未完成），已终止生成进程",
                )
                return
            except Exception as exc:  # noqa: BLE001 — communicate 其它异常
                if logger is not None:
                    logger.warning(
                        "architecture_routes",
                        f"claude 进程通信异常（project={project_name}）: "
                        f"{type(exc).__name__}: {exc!r}",
                    )
                self._finish(
                    proot, started_at, t0, "failed", error="claude 进程通信失败"
                )
                return
            finally:
                with self._guard:
                    self._procs.pop(key, None)

            # ── 3) 权威判定链（design D5，不信 claude 自述）──────────
            state, error, count = _judge_artifact(
                diagram_path, proc.returncode, stdout, logger
            )
            if logger is not None and state == "failed":
                logger.warning(
                    "architecture_routes",
                    f"架构图生成判失败（project={project_name}，"
                    f"returncode={proc.returncode}）：{error}；"
                    f"stderr 尾部: {(stderr or '')[-400:] if isinstance(stderr, str) else ''}",
                )
            self._finish(
                proot, started_at, t0, state, error=error, component_count=count
            )
        finally:
            lock.release()

    def _finish(
        self,
        proot: Path,
        started_at: str,
        t0: float,
        state: str,
        *,
        error: str | None = None,
        component_count: int | None = None,
    ) -> None:
        """终态落盘（ready/failed）：generated_at 仅 ready 填、duration_ms 全程。"""
        duration_ms = int((time.monotonic() - t0) * 1000)
        try:
            _write_status(
                proot,
                _status_payload(
                    state,
                    started_at=started_at,
                    generated_at=_utcnow_iso() if state == "ready" else None,
                    error=error,
                    duration_ms=duration_ms,
                    component_count=component_count,
                ),
            )
        except OSError:
            pass  # 终态写盘失败不逃逸线程；读侧按残留态兜底


# dashboard 进程内单例（design D2 单写者）。测试经独立 tmp 项目隔离，
# 键为 resolve 后的项目根，互不串扰。
_MANAGER = ArchitectureManager()


class H13ArchitectureRoutesMixin:
    """H13 architecture（对齐 H12 Regression 汇聚方式；H12 已被占用）。"""

    def _architecture_manager(self) -> ArchitectureManager:
        return _MANAGER

    def _api_architecture_status(self, query):
        """GET /api/architecture/status?project=<name>

        返回生成状态：``{project, state, started_at, generated_at, error,
        duration_ms, component_count}``，state ∈ none|generating|ready|failed。
        项目不存在 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        data = self._architecture_manager().status(proot)
        self._json({"project": project["name"], **data})

    def _api_architecture_refresh(self, query):
        """POST /api/architecture/refresh?project=<name>

        受理触发生成（design D1：起后台线程，MUST NOT 在 HTTP 线程内同步
        等待）。受理 → 200 {ok, state: "generating"}；单飞冲突 → 409；
        状态写盘失败 → 500。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        accepted, conflict, error = self._architecture_manager().refresh(
            proot, project["name"], logger=getattr(self, "logger", None)
        )
        if accepted:
            self._json({"ok": True, "state": "generating"})
            return
        self._error(409 if conflict else 500, error or "受理失败")

    def _api_architecture_diagram(self, query):
        """GET /api/architecture/diagram?project=<name>

        下发 diagram.html（Content-Type text/html）。未生成/非 ready →
        结构化错误（404 + 稳定 code ``architecture_not_generated``，前端
        控制流按 code 分支，不渲染 iframe）。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        state = self._architecture_manager().status(proot).get("state")
        if state != "ready":
            self._json(
                {"error": "架构图尚未生成", "code": "architecture_not_generated"},
                404,
            )
            return
        self._send_file(
            proot / ARCHITECTURE_DIR / DIAGRAM_FILENAME, "text/html; charset=utf-8"
        )
