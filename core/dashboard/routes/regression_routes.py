"""regression_routes.py — 全量回归 (test-regression-tab) routes（add-test-regression-tab）。

承载 4 个端点：
- GET  /api/regression/result    （query project）→ 最近一次回归快照
- GET  /api/regression/config    （query project）→ verify.yaml regression 段配置状态
- POST /api/regression/run       （query project）→ 写手动触发信号
- POST /api/regression/autodraft （query project）→ 同步 AI 生成 regression 段

端点 handler 走既有 mixin 形态（self._json / self._error）。两个 POST 端点的
项目均从 query string 解析，不消费请求体（code-review item 6e9597e51e90：
旧实现读 body 却不用，且 _read_json_body 对空 body 回 400，把遵循契约
不带 body 的客户端拒之门外；残留 body 字节由派发层
_drain_remaining_request_body 排空，keep-alive 不受影响）。
手动触发走 code-review 同款「dashboard 原子写 → daemon 主循环消费」范式：
POST 只写 ``.fenix/regression_request.json`` 文件信号，MUST NOT 在 HTTP
线程内同步跑回归（回归可跑 1800s）。

autodraft 为同步生成（对齐 /api/project/describe 范式）：HTTP 线程内
headless claude 直接探测测试体系 → 起草（整契约或仅 regression 段）→
自证 → 落位 verify.yaml，请求返回即终态。旧实现（写 AdminStore SIGNAL →
admin_monitor 巡检唤起 Administrator，分钟级异步）已废弃——信号通道本身
保留给其它生产者（code_fix 验证撞墙、周期检查点）继续使用。
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from core.dashboard import data as dashboard_data

# 手动触发信号文件（daemon 主循环经 fenixd._check_regression_requests 消费）。
# 与 code_review_request / approve_push_request 同属「dashboard 原子写 →
# daemon 主循环消费」文件信号族。
REGRESSION_REQUEST = ".fenix/regression_request.json"

# 同步生成的服务端预算（秒）。起草含「按 cmd 跑一次全量回归」的自证步
# （fenix_verify_contract.py regression 行），大套件可到十分钟级——给足
# 15 分钟；前端 timeoutMs 另加余量（dashboard.ts REGRESSION_AUTODRAFT_TIMEOUT_MS）。
AUTODRAFT_TIMEOUT_SECONDS = 900

# 同步起草单飞锁（per-project）：ThreadingHTTPServer 并发线程下两个同项目
# 请求会各起一个 claude 起草进程，互相踩 verify.yaml / git index。同项目
# 在途时第二个请求直接 409。
_AUTODRAFT_LOCKS_GUARD = threading.Lock()
_AUTODRAFT_LOCKS: dict[str, threading.Lock] = {}


def _autodraft_lock(proot: Path) -> threading.Lock:
    key = str(proot.resolve())
    with _AUTODRAFT_LOCKS_GUARD:
        lock = _AUTODRAFT_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _AUTODRAFT_LOCKS[key] = lock
        return lock


def _self_cert_script() -> str:
    """fenixd 自证 CLI 绝对路径（本仓 bin/fenix_verify_contract.py）。

    起草目标是任意被监控项目，不能假设目标仓里有该脚本；脚本自身处理
    sys.path，cwd 无关，绝对路径跨项目可用。
    """
    return str(Path(__file__).resolve().parents[3] / "bin" / "fenix_verify_contract.py")


def _autodraft_prompt(proot: Path, project_name: str, full_contract: bool) -> str:
    """同步起草提示词：自包含（不依赖目标项目里有 agents/administrator.md）。

    内容浓缩自 agents/administrator.md 的「验证契约起草手册」两节
    （regression 段起草 / 仅补 regression 段），边界一致：不臆造测试命令、
    format 仅 junit、自证通过才落位。
    """
    if full_contract:
        task = (
            f"该项目尚无 .fenix/verify.yaml。请起草**完整验证契约**（prepare/serve/ready），"
            f"草稿写到临时路径（如 /tmp/verify-draft-{project_name}.yaml），运行自证脚本三段"
            f"全通后复制落位到 {proot / '.fenix' / 'verify.yaml'}。"
        )
        boundary = ""
    else:
        task = (
            f"该项目的 .fenix/verify.yaml 已有效（prepare/serve/ready 齐备）。请**只补 regression 段**："
            f"MUST NOT 改动 prepare / serve / ready 与其它任何顶层键，只追加（或替换同名的）regression 段。"
        )
        boundary = (
            "补段后自证必须三段仍全通、且 regression 行显示成功，才算数。"
            "项目无可用测试体系时维持原契约不变并输出 no_test_system marker 结案。\n"
        )
    return f"""你是验证契约起草器。目标项目根：{proot}（项目名 {project_name}），以它为工作目录。
fenixd 自证脚本（绝对路径，任意 cwd 可用）：python3 {_self_cert_script()} <项目根>

任务：{task}

【验证契约结构】.fenix/verify.yaml 声明：prepare（构建步骤列表）、serve（kind: static → root
静态目录；或 kind: command → cmd 启动服务 + ready 就绪探针 url/expect）、regression（可选，
全量回归声明）。

【regression 段要求】
1. 识别测试体系：读 package.json 的 scripts.test（Jest/Vitest）、pyproject.toml /
   requirements*.txt 的 pytest、go.mod 的 Go test、pom.xml 的 surefire 等，确认语言、框架、
   测试目录（tests/、__tests__、src/**/*.test.*）。
2. cmd 必须产出 JUnit XML，output 为该 XML 相对项目根路径。例：
   pytest → cmd: python3 -m pytest tests/ -q --junit-xml=.fenix/regression/junit.xml，
   output: .fenix/regression/junit.xml；Jest/Go/surefire 等找各自 JUnit 报告器。
   timeout_seconds 按实测套件耗时设合理值（缺省 1800）；format 仅支持 junit 一值。
3. 自证门：python3 {_self_cert_script()} {proot}
   regression 段自证会按 cmd 真跑一次确认 output 产出可解析 JUnit XML（独立一行输出，
   不计入三段退出码）——该行显示成功才把 regression 段落位。
4. 无测试体系 / 探测不出可产出 JUnit XML 的命令：MUST 省略该段，**不臆造命令**
   （臆造会让周期回归每天 parse_error 空转，比不配更糟）。
{boundary}
【落位后】git add .fenix/verify.yaml && git commit -m "[fenix] dashboard: AI 生成回归段配置"
（pathspec 严格限定 .fenix/verify.yaml，不得卷入工作区其它未提交修改；非 git 仓或提交
失败不视为整体失败，继续输出 marker）。

【完成前】stdout 最后一行必须输出且仅输出一个 marker：
- 已落位 regression 段（或整契约含 regression 段）且自证通过 → FENIX_REGRESSION_DRAFT_RESULT: drafted
- 项目无可用测试体系，未臆造回归命令 → FENIX_REGRESSION_DRAFT_RESULT: no_test_system
- 起草失败（自证不过/无法完成）→ FENIX_REGRESSION_DRAFT_RESULT: failed"""


class H12RegressionRoutesMixin:
    """H12 regression（design 表 C H12）。"""

    def _coded_error(self, status: int, msg: str, code: str) -> None:
        """带稳定机器可读 ``code`` 的错误响应。

        code-review item 934af264345f：前端控制流按业务错误码分支，不依赖
        中文消息子串（措辞/locale 改动不再静默落入通用错误分支）。仅本
        mixin 需要编码的业务拒绝走此helper，其余错误照旧 ``_error``。
        """
        self._json({"error": msg, "code": code}, status)

    def _api_regression_result(self, query):
        """GET /api/regression/result?project=<name>

        返回 ``.fenix/regression/last-run.json`` 快照全字段（200）；快照缺失 →
        ``{status: "never_run"}``（200）；快照损坏 → ``{status: "parse_error",
        reason}``（200）。项目不存在 → 404。MUST NOT 因快照问题抛 500。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        self._json(dashboard_data.read_regression_result(str(project["path"])))

    def _api_regression_config(self, query):
        """GET /api/regression/config?project=<name>

        返回项目 ``.fenix/verify.yaml`` 的 regression 段解析状态（权威判定走
        ``load_verify_contract``，与周期检查点 / 手动触发的口径完全一致）：

        - ``exists``：verify.yaml 文件是否存在
        - ``contract_valid``：契约文件存在且可解析（``load_verify_contract`` 非 None）
        - ``regression``：有效 regression 段的字段映射；无段 / 整段无效 → ``null``
        - ``autodraft_in_flight``：同步 AI 生成是否在途（per-project 单飞锁的
          ``locked()``）。质量页签组件是条件渲染（切页签即卸载），按钮本地
          loading state 随之丢失；前端重挂载时重拉本端点即可恢复 loading 态，
          在途期间防重复触发（后端 409 兜底仍在）。

        设置页「质量」页签据 ``regression`` 是否为空展示段配置 / 缺失提示，
        并提供「AI 自动生成」「手工编辑」按钮。项目不存在 → 404。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))
        exists = (proot / ".fenix" / "verify.yaml").is_file()
        regression = None
        if contract is not None and contract.regression is not None:
            spec = contract.regression
            regression = {
                "cmd": spec.cmd,
                "output": spec.output,
                "timeout_seconds": spec.timeout_seconds,
                "format": spec.format,
                "long_test_threshold_seconds": spec.long_test_threshold_seconds,
            }
        self._json(
            {
                "project": project["name"],
                "exists": exists,
                "contract_valid": contract is not None,
                "regression": regression,
                "autodraft_in_flight": _autodraft_lock(proot).locked(),
            }
        )

    def _api_regression_run(self, query):
        """POST /api/regression/run — query project

        写 ``.fenix/regression_request.json`` 文件信号 → daemon 主循环消费
        （不直接同步跑回归）。

        - 项目不存在 → 404
        - 项目 verify.yaml 无有效 regression 段 → 400「该项目未配置全量回归」
          （MUST NOT 派发空跑）
        - 已有回归在跑（单飞）→ 409「已有回归在进行中」（基于既有运行中判定）
        - 消费方守卫：daemon 未受 supervisor 托管（hosting_state ==
          "unmanaged"）→ 409 明确拒绝；stopped → 400「daemon 未运行」
        - 受理 → 200 + {ok, requested_at}
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])

        # 项目未配置回归守卫（verify.yaml regression 段缺失/无效 → 400）
        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))
        if contract is None or contract.regression is None:
            self._coded_error(
                400, "该项目未配置全量回归（verify.yaml regression 段）",
                "regression_not_configured",
            )
            return

        # 运行中守卫（已有回归在跑 → 409，单飞不并发；基于 marker 新鲜度
        # 判定，与 code_review 的 progress.running 同义——marker 不存在
        # 或超窗 stale 即视为未运行）
        if dashboard_data.is_regression_running(proot):
            self._coded_error(409, "已有回归在进行中", "regression_already_running")
            return

        # 消费方守卫（hosting_state 判据，先例 request_spec_approve_push）
        from core.fenix_session import hosting_state as _hosting_state

        try:
            state = _hosting_state(str(proot))
        except Exception as exc:
            # 判定异常按未运行兜底，宁拒勿假放行；降级可观测（item 0d1ba0c6efc0）
            state = "stopped"
            _log = getattr(self, "logger", None)
            if _log is not None:
                _log.warning(
                    "regression_routes",
                    f"hosting_state 判定异常，按 stopped 兜底（宁拒勿假放行）: {exc!r}",
                )
        if state == "unmanaged":
            self._error(
                409,
                "本项目 daemon 未受 supervisor 托管，回归信号不会被消费。"
                "经项目页「安装托管」或 /fenix-setup 恢复 supervisor 托管后重试",
            )
            return
        if state != "managed":
            self._error(400, "daemon 未运行，请先启动 daemon")
            return

        # 原子创建信号文件（O_CREAT|O_EXCL 独占创建，对齐 code-review）：
        # ThreadingHTTPServer 并发线程下非原子 exists 检查会互相覆盖信号，
        # 独占创建成功即胜出；FileExistsError → 409（已有未消费请求）。
        created = datetime.now(timezone.utc).isoformat()
        # 键名与消费者契约一致（fenixd._check_regression_requests 读
        # requested_at；item 117af27b759a：写 created 使 daemon 恒记空时间戳）
        payload = {"source": "dashboard", "requested_at": created}
        req_path = proot / REGRESSION_REQUEST
        try:
            req_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            # mkdir 与其余写路径一并包 try（code-review item 6c873c1c07ed）：
            # 权限/IO 失败不再逃逸 handler 被 dispatcher 转成通用 Internal
            # Server Error（具体错误文本泄漏进 HTTP 响应），与其余写路径
            # 一致报告。
            self._error(500, f"回归触发信号写入失败: {e}")
            return
        try:
            fd = os.open(str(req_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            self._error(409, "已有未消费的回归触发请求（请稍后重试）")
            return
        except OSError:
            self._error(500, "回归触发信号写入失败")
            return
        f = None
        try:
            # fdopen 失败路径显式关 fd（code-review item 655c860e2e6e）：旧
            # `with os.fdopen(...)` 形态下 fdopen() 自身抛错时裸 fd 未被包装
            # 也无人关闭（with 的 close 只在 fdopen 成功后才生效）——请求线程
            # 描述符泄漏。改为显式接管：f 为 None（fdopen 未成功）时兜底
            # os.close；成功后统一经 finally close（等价 with 语义）。
            f = os.fdopen(fd, "w", encoding="utf-8")
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        except Exception as exc:
            if f is None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            # 写中途失败：清掉半写文件，避免残留被 daemon 误消费（半写文件
            # 存活会让后续每个 POST 都 409 直到 daemon 消费）。清理失败必须
            # 留痕并携带底层异常——静默吞掉会让 500 无从诊断。
            try:
                os.unlink(str(req_path))
            except OSError as un_err:
                _log = getattr(self, "logger", None)
                if _log is not None:
                    _log.warning(
                        "regression_routes",
                        f"回归触发信号半写文件清理失败 {req_path}: {un_err!r}"
                        f"（原写入异常: {exc!r}）；残留文件将使后续触发持续 409",
                    )
            self._error(500, f"回归触发信号写入失败: {exc}")
            return
        finally:
            if f is not None:
                f.close()
        self._json({"ok": True, "requested_at": created})

    def _api_regression_autodraft_post(self, query):
        """POST /api/regression/autodraft — query project

        同步 AI 生成 regression 段（设置页「质量」页签回归卡片「使用 AI 生成」）。
        对齐 /api/project/describe 范式：HTTP 线程内 headless claude 直接
        探测测试体系 → 起草 → 自证 → 落位 verify.yaml，请求返回即终态
        （旧「写 AdminStore 信号 → 巡检唤起 Administrator」异步通道已废弃；
        两类信号类型保留给其它生产者——code_fix 验证撞墙、周期检查点——继续使用）。

        按契约状态分流（判定走 ``load_verify_contract``）：

        - 契约有效且已有有效 regression 段 → ``skipped``（人工/既有配置权威）
        - 契约缺失（``contract is None``）→ 起草完整契约（有测试体系时含 regression 段）
        - 契约有效但无有效 regression 段 → 仅补段（MUST NOT 动 prepare/serve/ready）

        结果判定（权威 = 重新 ``load_verify_contract``，不信 claude 自述；
        stdout 的 marker 只用于区分「无测试体系结案」与真失败）：

        - 段有效 → ``success``
        - 段无效且 marker=no_test_system → ``no_test_system``
        - 其余（超时/非零退出/marker failed/段仍缺失）→ ``{ok: False, error}``

        错误契约与 describe 一致：project 校验失败走 _error(404)；执行失败走
        HTTP 200 + {ok: False, error}，细节降级进服务端日志（不外泄）。同项目
        并发单飞 → 409。
        """
        project = self._project_from_query(query)
        if project is None or not project.get("exists"):
            self._error(404, "project not found")
            return
        proot = Path(project["path"])

        from core.verify_contract import load_verify_contract

        contract = load_verify_contract(proot, logger=getattr(self, "logger", None))

        # 已有有效 regression 段 → 不生成（人工/既有配置权威）
        if contract is not None and contract.regression is not None:
            self._json(
                {
                    "ok": True,
                    "project": project["name"],
                    "status": "skipped",
                    "message": "regression 段已配置，无需生成。如需调整请在「项目简介」面板编辑 verify.yaml。",
                }
            )
            return

        # 同项目单飞：在途时第二个请求直接 409（ThreadingHTTPServer 并发线程
        # 各起一个 claude 起草进程会互相踩 verify.yaml / git index）
        lock = _autodraft_lock(proot)
        if not lock.acquire(blocking=False):
            self._error(409, "该项目的 AI 生成正在进行中，请稍候")
            return
        try:
            full_contract = contract is None
            prompt = _autodraft_prompt(proot, project["name"], full_contract)
            try:
                proc = subprocess.run(
                    ["claude", "-p", prompt, "--permission-mode", "bypassPermissions"],
                    cwd=str(proot),
                    timeout=AUTODRAFT_TIMEOUT_SECONDS,
                    shell=False,
                    capture_output=True,
                    text=True,
                )
            except subprocess.TimeoutExpired:
                _log = getattr(self, "logger", None)
                if _log is not None:
                    _log.warning(
                        "regression_routes",
                        f"AI 生成 regression 段超时（>{AUTODRAFT_TIMEOUT_SECONDS}s，"
                        f"project={project['name']}，full_contract={full_contract}）",
                    )
                self._json({"ok": False, "error": "生成超时（AI 起草未在预算时间内完成）"})
                return
            except Exception as exc:
                # 不外泄裸异常文本（describe 同款）：str(exc) 可能携带内部路径/
                # 命令细节，细节降级经服务端日志留痕，客户端收通用消息。
                _log = getattr(self, "logger", None)
                if _log is not None:
                    _log.warning(
                        "regression_routes",
                        f"调用 claude CLI 异常（project={project['name']}）: "
                        f"{type(exc).__name__}: {exc!r}",
                    )
                self._json({"ok": False, "error": "调用 claude CLI 失败"})
                return

            if proc.returncode != 0:
                _log = getattr(self, "logger", None)
                if _log is not None:
                    _log.warning(
                        "regression_routes",
                        f"claude CLI 非零退出码（project={project['name']}）: "
                        f"{proc.returncode}；stderr 尾部: {(proc.stderr or '')[-400:]}",
                    )
                self._json({"ok": False, "error": "调用 claude CLI 失败"})
                return

            # marker 解析：取 stdout 尾部最后一个 marker 行（claude 可能用代码块
            # 包裹输出，剥反引号后前缀匹配）
            marker = ""
            stdout_tail = (proc.stdout or "")[-2000:]
            for line in stdout_tail.splitlines():
                s = line.strip().strip("`").strip()
                if s.startswith("FENIX_REGRESSION_DRAFT_RESULT:"):
                    marker = s.split(":", 1)[1].strip()

            # 权威判定：以契约解析结果为准
            contract_after = load_verify_contract(proot, logger=getattr(self, "logger", None))
            if contract_after is not None and contract_after.regression is not None:
                self._json(
                    {
                        "ok": True,
                        "project": project["name"],
                        "status": "success",
                        "message": (
                            "已生成 regression 段并写入 .fenix/verify.yaml"
                            if not full_contract
                            else "已起草验证契约（含 regression 段）并写入 .fenix/verify.yaml"
                        ),
                    }
                )
                return

            if marker == "no_test_system":
                self._json(
                    {
                        "ok": True,
                        "project": project["name"],
                        "status": "no_test_system",
                        "message": "项目无可用测试体系，未臆造回归命令（周期回归保持未配置）。",
                    }
                )
                return

            _log = getattr(self, "logger", None)
            if _log is not None:
                _log.warning(
                    "regression_routes",
                    f"AI 生成 regression 段未落位（project={project['name']}，"
                    f"full_contract={full_contract}，marker={marker!r}）；"
                    f"stdout 尾部: {stdout_tail[-400:]}",
                )
            self._json(
                {
                    "ok": False,
                    "error": "AI 生成未成功：regression 段未通过自证落位，可重试或查看服务端日志",
                }
            )
        finally:
            lock.release()