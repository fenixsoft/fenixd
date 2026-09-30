"""core.pm_engine.verification.serving — serving 工作树供给/实例管理/端口（refactor-verification-module D2）。

从 VerificationPipeline 摘出的 serving 工作树供给（_ensure_serving_worktree）、
静态/命令服务启动、实例登记/驱逐、应用可达性探测、端口探测、日志尾部读取
场景 URL 端口改写、verify round 追踪。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。
"""

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from core.proc_utils import find_free_port
from core.serving_registry import ServingRegistry, pid_alive
from core.verify_contract import (
    CommandVerifyServer,
    StaticVerifyServer,
    entry_preflight_error,
    provision_worktree_node_modules,
    resolve_deps_mode,
)

# 探针通过后的静置秒数与 legacy 兜底自启探活轮询（随 serving 组迁移）
POST_READY_SETTLE_SECONDS = 10
LEGACY_START_PROBE_ATTEMPTS = 30
LEGACY_START_PROBE_INTERVAL_SECONDS = 1

# 端口前向边界（单一份正则，收集/内存改写/持久化改写共用）：``:port`` 后随
# 路径/查询/片段/引号或串尾。各处自写一份会漂移——场景 URL 带 #fragment 或
# 引号边界时收集判定命中而改写不生效，重探持续失败走兜底路径。
_PORT_BOUNDARY = r"(?=[/\?#\"']|$)"


def _ensure_serving_worktree(pipeline, spec_name: str, contract, mode: str):
    """serving worktree 供给（static/command 两型共享）。

    HEAD 未变且目录存活时复用；否则停掉旧实例、重建 worktree、provision
    依赖（deps_mode）并执行契约 prepare（构建产物）。

    Returns:
        (wt_path, head, err, created)：wt_path=None 时 err 为人类可读原因；
        created 标记本轮是否新建 worktree（False=复用旧条目同一目录），
        供调用方失败早退分支清理孤儿目录（code-review e3d99b7b7862）。
        server 生命周期（启动/复用/停止）由调用方按 mode 管理。
    """
    serve_root = Path(pipeline._context.project_root) / ".fenix" / "verify-serving"
    serve_root.mkdir(parents=True, exist_ok=True)
    cache = pipeline.__dict__.setdefault("_contract_static_servers", {})
    # D9：经包命名空间延迟解析，使 patch("core.pm_engine.verification.run_prepare_steps") 生效
    import core.pm_engine.verification as _facade

    # code-review 205c8b9f37ed：校验 rev-parse returncode 并捕获 subprocess 异常，
    # 失败时走既有 (None, None, err) 失败路径（原先 git 失败时 head 静默为空串，
    # 缓存每轮落空全量重建；超时/OSError 则炸穿被兜成「新验证流程失败」）
    try:
        head_res = subprocess.run(
            ["git", "-C", str(pipeline._context.project_root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return None, None, f"获取验证 worktree HEAD 失败: {e}", False
    if head_res.returncode != 0:
        return None, None, (
            "获取验证 worktree HEAD 失败: "
            f"{(head_res.stderr or head_res.stdout).strip()[-200:]}"
        ), False
    head = head_res.stdout.strip()
    old = cache.get(spec_name)
    if (
        old is not None
        and old.get("head") == head
        and old.get("mode") == mode
        and Path(old["wt_path"]).is_dir()
    ):
        return old["wt_path"], head, None, False
    if old is not None:
        # verify-process-lifecycle D6：command 型旧实例 HEAD 变更前先移除登记
        old_server = old.get("server")
        if isinstance(old_server, CommandVerifyServer):
            pipeline._unregister_serving_instance(spec_name, old_server)
        try:
            old_server.stop()
        except Exception as e:
            # fix-deferred-findings 健壮性：stop() 失败不再静默吞掉，补日志
            # （对齐 _evict_spec_serving 样板；不调换 unregister 顺序）
            pipeline._context.logger.warning(
                "pm_engine",
                f"停止旧 serving 实例 '{spec_name}' 失败（不影响重建）: {e}",
            )
        # command-主树条目（_serve_command_in_main）只有 server/mode 两键：
        # 无 wt_path 时跳过 worktree 清理（对齐 _evict_spec_serving 防御形态）
        old_wt = old.get("wt_path")
        if old_wt:
            pipeline._remove_serving_worktree(old_wt)
    # code-review 340873fcc988：后缀用纳秒时间戳——秒级后缀在「上轮 worktree
    # 清理失败目录残留 + 本轮同秒重建」时与新路径撞名，git worktree add 因
    # 路径已存在直接失败（本轮以难懂的「worktree 创建失败」告终，下一轮才
    # 因时间戳变化自愈）
    # code-review 78057677e669/f7d8c757c7e8：目录命名契约 {spec}-{时间戳后缀}
    # （≥10 位数字：秒级 10 位 / 纳秒 19 位均合法）。回收侧
    # serving_reclaim.parse_spec_from_worktree_name 以 \d{10,} 解析同一契约
    # （解析函数不反向共享，避免 serving_reclaim → serving 依赖）——后缀
    # 形态变更须两侧联动，否则回收对新增命名整段空转（fail-safe 保留）。
    wt = serve_root / f"{spec_name}-{time.time_ns()}"
    # code-review a02f05cbf835：与上方 rev-parse 同口径兜底——git 缺失/权限/
    # 60s 超时抛出的 OSError/subprocess.SubprocessError 不再炸穿验证主流程，
    # 走既有 (None, None, err) 失败路径（对齐 _remove_serving_worktree 口径）
    try:
        r = subprocess.run(
            [
                "git",
                "-C",
                str(pipeline._context.project_root),
                "worktree",
                "add",
                "--detach",
                str(wt),
                "HEAD",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return None, None, f"验证 worktree 创建失败: {e}", False
    if r.returncode != 0:
        return None, None, (
            "验证 worktree 创建失败: " f"{(r.stderr or r.stdout).strip()[-200:]}"
        ), False
    # code-review 7470b5d89795：provision 抛异常（网络/npm 故障）时清理刚建的
    # worktree 再走既有失败路径，避免 .fenix/verify-serving/ 累积孤儿目录
    try:
        provision_worktree_node_modules(
            wt,
            pipeline._context.project_root,
            sorted({(s.cwd or ".") for s in contract.prepare}),
            mode=resolve_deps_mode(contract, pipeline._context.config_reader("verify.deps_mode", "")),
            logger=pipeline._context.logger,
        )
    except Exception as e:
        pipeline._remove_serving_worktree(wt)
        return None, None, f"验证 worktree 依赖供给失败: {e}", False
    err = _facade.run_prepare_steps(contract, wt)
    if err:
        pipeline._remove_serving_worktree(wt)
        return None, None, f"验证契约 prepare 失败（worktree 内）: {err}", False
    return str(wt), head, None, True


def _serve_static_in_main(pipeline, spec_name, contract, scenarios_path) -> tuple:
    """方案 1（默认）：主树构建 + 主树起服务。同 root 复用已启动实例。

    code-review a6337eba0acb：本路径只写共享键 ``"main"``、从不清 spec 键
    条目——上一轮以 worktree 作用域运行遗留的 spec 键条目（server/wt_path）
    会滞留：旧实例不 stop、旧 serving worktree 不清理，且
    ``_current_instance_base_url`` 对 spec 键优先，滞留旧实例的 base_url
    会被当作本轮实例供给引擎（与本轮新主树实例 split-brain）。供给前先按
    单一 ``_evict_spec_serving`` 清退样板驱逐 spec 键旧条目（幂等，无旧
    条目安全空转；共享键 ``"main"`` 不受影响）。
    """
    root_dir = Path(pipeline._context.project_root) / contract.serve.root
    if not root_dir.is_dir():
        return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
    pipeline._evict_spec_serving(spec_name)
    cache = pipeline.__dict__.setdefault("_contract_static_servers", {})
    srv = cache.get("main")
    if srv is None or srv.root != root_dir.resolve():
        if srv is not None:
            srv.stop()
        srv = StaticVerifyServer(root_dir)
        cache["main"] = srv
    return pipeline._finalize_static(srv, contract, scenarios_path, "主树")


def _serve_static_in_worktree(pipeline, spec_name, contract, scenarios_path) -> tuple:
    """方案 2：专用 serving worktree 内构建 + 起静态服务（隔离主树运行实例）。

    worktree 每次 HEAD 变化时重建（分离 HEAD、自管理生命周期，位于
    .fenix/verify-serving/，gitignore 排除）；HEAD 未变时复用已启动实例
    与产物（replan 循环不重复构建）。
    """
    wt, head, err, _created = pipeline._ensure_serving_worktree(
        spec_name, contract, mode="static"
    )
    if wt is None:
        return False, False, err
    cache = pipeline.__dict__.setdefault("_contract_static_servers", {})
    old = cache.get(spec_name)
    if (
        old is not None
        and old.get("mode") == "static"
        and old.get("head") == head
        and isinstance(old.get("server"), StaticVerifyServer)
        # code-review b7aa1db41ee6：与 _ensure_serving_worktree 同款目录存活
        # 校验——HEAD 未变而 worktree 被外部清掉时，旧实例服务根目录已不存在
        # （复用即场景整批 404），落到下方重建分支改用刚重建的 worktree
        and Path(old["wt_path"]).is_dir()
    ):
        return pipeline._finalize_static(
            old["server"], contract, scenarios_path, "验证 worktree（复用）"
        )
    root_dir = Path(wt) / contract.serve.root
    if not root_dir.is_dir():
        pipeline._remove_serving_worktree(wt)
        return False, False, f"验证契约 serve.root 不存在: {contract.serve.root}"
    cache[spec_name] = {
        "server": StaticVerifyServer(root_dir),
        "wt_path": wt,
        "head": head,
        "mode": "static",
    }
    return pipeline._finalize_static(
        cache[spec_name]["server"], contract, scenarios_path, "验证 worktree"
    )


def _serve_command_in_worktree(pipeline, spec_name, contract, scenarios_path) -> tuple:
    """命令型被测实例的 worktree 隔离（serve.kind=command + static_scope=worktree）。

    full-stack 验证的解法：serving worktree 内 prepare 构建产物，再以
    worktree 为 cwd 启动 serve.cmd——后端 API 与前端产物同为本次 HEAD 的
    真实形态（static 模式无 API，交付物端点被迫 mock＝假阴性放大器）。
    端口注入（与 static 模式「框架分配、实例消费」同范式）：启动前分配
    空闲端口，经 {port} 占位符替换 + FENIX_VERIFY_PORT 环境变量双通道
    注入——实例永不与既有实例（主树常驻实例等）争抢端口；未消费注入的
    存量契约由 CommandVerifyServer 进程归属/邻近扫描兜底发现。HEAD 未变
    时复用已启动实例。

    与 ``_serve_command_in_main`` 约 90 行同构（legacy 参数解析/入口预检/
    Popen spawn/boot.log/就绪收尾近乎逐行重复），结构性差异仅 cwd 与
    worktree 生命周期——两侧改动须同步另一侧（code-review dbe41e3fd97b）。
    """
    wt, head, err, created = pipeline._ensure_serving_worktree(
        spec_name, contract, mode="command"
    )
    if wt is None:
        return False, False, err
    cache = pipeline.__dict__.setdefault("_contract_static_servers", {})
    old = cache.get(spec_name)
    if (
        old is not None
        and old.get("mode") == "command"
        and old.get("head") == head
        and isinstance(old.get("server"), CommandVerifyServer)
        and old["server"].ok
        # code-review b7aa1db41ee6：同 _serve_static_in_worktree——目录消失
        # 不复用，落到下方重启分支复用刚重建的 worktree
        and Path(old["wt_path"]).is_dir()
    ):
        return pipeline._finalize_static(
            old["server"], contract, scenarios_path, "命令 worktree（复用）"
        )
    port = find_free_port()
    # legacy 兜底参数：邻近扫描基准（serve.port 或 cmd 内端口数字）与
    # 启动前监听快照（跳过既有实例端口）。cmd 引用 {port} 后两者皆不需要
    # （code-review 43f462839c68：以 {port} 引用为门跳过 legacy 解析与 pre
    # 快照——注入成功的正常路径不消费这组参数，不再白付 51 端口并发探测；
    # 实例无视注入端口自绑时仍有进程归属发现兜底），仅存量无 {port} 命令
    # 才做邻近扫描准备。
    orig_cmd = contract.serve.cmd or ""
    m = re.search(r"(?:--port|-p)\s+(\d+)", orig_cmd)
    legacy_hint = (
        None
        if "{port}" in orig_cmd
        else contract.serve.port or (int(m.group(1)) if m else None)
    )
    pre = (
        _probe_ports_responding(range(legacy_hint, legacy_hint + 51))
        if legacy_hint
        else set()
    )
    # 入口存在性预检（design D1）：{port} 替换前的原 cmd 检查（{port} 不在
    # 路径段）；入口文件不存在 → fail-fast，不 spawn、不跑场景，场景执行数=0。
    preflight_err = entry_preflight_error(orig_cmd, Path(wt))
    if preflight_err:
        pipeline._write_verify_contract_missing(
            spec_name,
            f"{preflight_err}（入口存在性预检失败，spawn 前 fail-fast）",
            f"serve.cmd 原文={orig_cmd!r}; cwd={wt}",
            recommended_action=(
                "Administrator 修正 .fenix/verify.yaml serve.cmd 入口路径："
                "按错误信息中「候选」提示修正，或确认构建产物已生成后重验"
            ),
        )
        # code-review e3d99b7b7862：本轮新建的 serving worktree 随预检失败
        # 清理（对齐 provision/prepare 失败即清理纪律，code-review
        # 7470b5d89795）；复用态不动——旧缓存条目仍引用同一目录
        if created:
            pipeline._remove_serving_worktree(wt)
        return False, False, preflight_err
    cmd_str = orig_cmd.replace("{port}", str(port))
    env = {**os.environ, "FENIX_VERIFY_PORT": str(port)}
    # design D3：worktree 路径同样落盘 boot.log（非 DEVNULL 吞掉），
    # 启动即死错误证据经 CommandVerifyServer 句柄关闭前可读。
    boot_log = pipeline._open_boot_log(spec_name)
    try:
        proc = subprocess.Popen(
            cmd_str,
            shell=True,
            cwd=str(wt),
            stdout=boot_log,
            stderr=boot_log,
            start_new_session=True,
            env=env,
        )
    except Exception as e:
        boot_log.close()
        return False, False, f"验证命令实例启动失败: {e}"
    srv = CommandVerifyServer(
        proc,
        port,
        timeout=contract.ready.timeout or 60,
        legacy_hint=legacy_hint,
        legacy_pre=pre,
        boot_log=boot_log,
    )
    if not srv.ok:
        # 启动即死：boot.log 尾部附入失败描述（Cannot find module 等）
        boot_tail = pipeline._read_boot_log_tail(spec_name, boot_log)
        srv.stop()
        # code-review e3d99b7b7862：本轮新建的 serving worktree 随启动即死
        # 清理（复用态不动）；boot.log 句柄已由 srv.stop() 关闭，仅目录本体
        # 滞留——不再等 serving_reclaim 600s 周期兜底回收
        if created:
            pipeline._remove_serving_worktree(wt)
        return (
            False,
            False,
            ((srv.failure_note or "验证命令实例未就绪（注入端口未被消费）") + boot_tail),
        )
    if old is not None:
        # code-review 73a34755ac94：重启分支（复用门不满足，如实例中途死亡
        # ok=False）覆盖缓存前对旧 server 补一次 unregister + stop——与
        # _ensure_serving_worktree 重建路径 / _evict_spec_serving 同口径，
        # 半死实例的进程组清理不拖延到 serving_registry 周期清扫、boot.log
        # 句柄不靠 GC 兜底（stop 对已死进程安全）。
        old_server = old.get("server")
        if isinstance(old_server, CommandVerifyServer):
            pipeline._unregister_serving_instance(spec_name, old_server)
        try:
            old_server.stop()
        except Exception as e:
            pipeline._context.logger.warning(
                "pm_engine",
                f"停止旧 serving 实例 '{spec_name}' 失败（不影响重启）: {e}",
            )
    cache[spec_name] = {
        "server": srv,
        "wt_path": wt,
        "head": head,
        "mode": "command",
    }
    # verify-process-lifecycle D6：command 型实例创建时登记
    # （pid/port/spec/worktree），终局/周期清扫按 liveness 收割。
    pipeline._register_serving_instance(spec_name, srv, wt_path=wt)
    return pipeline._finalize_static(srv, contract, scenarios_path, "命令 worktree")


def _serve_command_in_main(pipeline, spec_name, contract, scenarios_path) -> tuple:
    """命令型被测实例的主树路径（serve.kind=command + static_scope=main）。

    与 ``_serve_command_in_worktree`` 同构，仅 cwd 换为主树项目根（主树
    prepare 已在其上游完成构建）：``{port}`` 替换 + FENIX_VERIFY_PORT
    注入、CommandVerifyServer 三段式端口发现、serving 实例登记、
    ``_finalize_static``（BASE_URL 全量改写 + 就绪探针）收尾。

    **不复用缓存、每验证新建实例**：worktree 版的 HEAD 缓存复用依赖
    「HEAD 未变 ⇒ 产物未变」这一 worktree 专属不变量，主树工作区状态比
    HEAD 变化更频繁（未提交改动 + prepare 重建产物），照搬会测得旧产物、
    违 BASE_URL 新鲜性铁律。但仍以 ``spec_name`` 为键写入
    ``_contract_static_servers``（server/mode 元数据），供
    ``_evict_spec_serving`` 终局回收——禁用键 ``"main"``（该键为 static
    主树共享实例专属、多 spec 共享、终局豁免）。code-review a6337eba0acb：
    覆写条目前先经 ``_evict_spec_serving`` 清退上一轮旧条目（unregister →
    stop → worktree 清理，对作用域翻转遗留的 worktree 形态条目同样兼容），
    同 spec 连轮不再滞留旧实例与其 servers.json 登记。

    与 ``_serve_command_in_worktree`` 约 90 行同构——两侧改动须同步另一侧
    （清退口径已分叉：本侧走 ``_evict_spec_serving`` 单一样板，worktree 侧
    手工 unregister + stop；code-review dbe41e3fd97b）。
    """
    cache = pipeline.__dict__.setdefault("_contract_static_servers", {})
    port = find_free_port()
    # legacy 兜底参数：邻近扫描基准（serve.port 或 cmd 内端口数字）与
    # 启动前监听快照（跳过既有实例端口）。cmd 引用 {port} 后两者皆不需要
    # （code-review 43f462839c68：以 {port} 引用为门跳过 legacy 解析与 pre
    # 快照——注入成功的正常路径不消费这组参数，不再白付 51 端口并发探测；
    # 实例无视注入端口自绑时仍有进程归属发现兜底），仅存量无 {port} 命令
    # 才做邻近扫描准备。
    orig_cmd = contract.serve.cmd or ""
    m = re.search(r"(?:--port|-p)\s+(\d+)", orig_cmd)
    legacy_hint = (
        None
        if "{port}" in orig_cmd
        else contract.serve.port or (int(m.group(1)) if m else None)
    )
    pre = (
        _probe_ports_responding(range(legacy_hint, legacy_hint + 51))
        if legacy_hint
        else set()
    )
    # 入口存在性预检（design D1）：{port} 替换前的原 cmd 检查（{port} 不在
    # 路径段）；入口文件不存在 → fail-fast，不 spawn、不跑场景，场景执行数=0。
    preflight_err = entry_preflight_error(orig_cmd, pipeline._context.project_root)
    if preflight_err:
        pipeline._write_verify_contract_missing(
            spec_name,
            f"{preflight_err}（入口存在性预检失败，spawn 前 fail-fast）",
            f"serve.cmd 原文={orig_cmd!r}; cwd={pipeline._context.project_root}",
            recommended_action=(
                "Administrator 修正 .fenix/verify.yaml serve.cmd 入口路径："
                "按错误信息中「候选」提示修正，或确认构建产物已生成后重验"
            ),
        )
        return False, False, preflight_err
    cmd_str = orig_cmd.replace("{port}", str(port))
    env = {**os.environ, "FENIX_VERIFY_PORT": str(port)}
    # design D3：主树路径同样落盘 boot.log（非 DEVNULL 吞掉），
    # 启动即死错误证据经 CommandVerifyServer 句柄关闭前可读。
    boot_log = pipeline._open_boot_log(spec_name)
    try:
        proc = subprocess.Popen(
            cmd_str,
            shell=True,
            cwd=str(pipeline._context.project_root),
            stdout=boot_log,
            stderr=boot_log,
            start_new_session=True,
            env=env,
        )
    except Exception as e:
        boot_log.close()
        return False, False, f"验证命令实例启动失败: {e}"
    srv = CommandVerifyServer(
        proc,
        port,
        timeout=contract.ready.timeout or 60,
        legacy_hint=legacy_hint,
        legacy_pre=pre,
        boot_log=boot_log,
    )
    if not srv.ok:
        # 启动即死：boot.log 尾部附入失败描述（Cannot find module 等）
        boot_tail = pipeline._read_boot_log_tail(spec_name, boot_log)
        srv.stop()
        return (
            False,
            False,
            ((srv.failure_note or "验证命令实例未就绪（注入端口未被消费）") + boot_tail),
        )
    # code-review a6337eba0acb：覆写条目前先按单一清退样板驱逐旧条目——
    # 上一轮可能以 static_scope=worktree 运行（旧条目含 server/wt_path 与
    # servers.json 登记），直接覆写会让旧实例不 stop、登记不 unregister、
    # 旧 serving worktree 不 _remove_serving_worktree（旧 pid 登记永久
    # 残留到 daemon 周期清扫）。_evict_spec_serving 幂等（无旧条目安全
    # 空转），对缺 wt_path 的 command-主树旧条目同型兼容；主树 static
    # 共享键 "main" 不受影响。
    pipeline._evict_spec_serving(spec_name)
    cache[spec_name] = {
        "server": srv,
        "mode": "command",
    }
    # verify-process-lifecycle D6：command 型实例创建时登记
    # （pid/port/spec），终局/周期清扫按 liveness 收割。
    pipeline._register_serving_instance(spec_name, srv)
    return pipeline._finalize_static(srv, contract, scenarios_path, "命令主树")


def _finalize_static(pipeline, srv, contract, scenarios_path, scope_label) -> tuple:
    """BASE_URL 注入 + 就绪探针：static 两类 scope 的共同收尾。

    探针通过后静置 ``POST_READY_SETTLE_SECONDS`` 再放行开跑场景：探针
    语义只保证「探针路径此刻可达」，冷实例的后端收尾/前端首帧渲染仍有
    长尾（add-spec-hooks 第 1 轮 4 个 web 场景白屏 env 事故——探针通过
    与场景开跑同一秒）。与 browser 首帧渲染等待、探针鉴别力自检同层，
    白屏防复发第三道纵深。用户指令 2026-09-06。
    """
    # D9：经包命名空间延迟解析，使 patch("core.pm_engine.verification.rewrite_scenarios_origin") 生效
    import core.pm_engine.verification as _facade

    # 防御式取 logger：既有测试以 `VerificationPipeline.__new__` 裸构造（不设
    # _pm/_context，D10「测试零修改」契约），getattr 缺省兜 None——真实链路
    # （有 _pm）仍能拿到 logger 供 rewrite_scenarios_origin 记 WARNING。
    _ctx = getattr(pipeline, "_context", None)
    _logger = getattr(_ctx, "logger", None)
    n = _facade.rewrite_scenarios_origin(scenarios_path, srv.base_url, _logger)
    # -1 = 已解析出候选目标但写盘失败（BASE_URL 铁律未落盘，WARNING 已由
    # rewrite_scenarios_origin 记录）——note 与「本无需改写」(0) 可判别，
    # 不再同值混淆（code-review item 90ca963ad6e7）。
    rewrite_note = (
        f"场景 origin 改写 {n} 处"
        if n >= 0
        else "场景 origin 改写写盘失败（BASE_URL 未落盘）"
    )
    ok, probe_note = _facade.probe_ready(srv.base_url, contract.ready)
    if not ok:
        note = (
            f"验证契约 static[{scope_label}]: 被测实例 {srv.base_url}"
            f"（{rewrite_note}）— {probe_note}"
        )
        return (False, False, note)
    # D9：POST_READY_SETTLE_SECONDS 经门面解析（测试 patch 包级常量生效）
    settled = _facade.POST_READY_SETTLE_SECONDS
    time.sleep(settled)
    note = (
        f"验证契约 static[{scope_label}]: 被测实例 {srv.base_url}"
        f"（{rewrite_note}，探针通过后静置 "
        f"{settled}s）— {probe_note}"
    )
    return (True, False, note)


def _remove_serving_worktree(pipeline, wt_path) -> None:
    # best-effort 清理不向上抛：调用点（_ensure_serving_worktree /
    # _evict_spec_serving）均在各自 try 块之外，git worktree remove
    # 超时（进程占用/NFS 挂起）或 OSError 炸穿会把清理失败变成验证
    # 主流程异常——对齐本文件其余 subprocess 写点的异常兜底与
    # _evict_spec_serving 的非阻塞语义
    try:
        r = subprocess.run(
            [
                "git",
                "-C",
                str(pipeline._context.project_root),
                "worktree",
                "remove",
                "--force",
                str(wt_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        # code-review 40d00d0ca687：非零返回码（目录被进程占用/权限等）不抛
        # 异常但目录滞留，只能靠 serving_reclaim 600s 周期兜底回收——不留痕
        # 则排障时无法从日志区分「未清理」与「已清理」（对齐本文件其余
        # subprocess 写点的失败留痕口径；重试/rmtree 降级归 serving_reclaim）
        if r.returncode != 0:
            pipeline._context.logger.warning(
                "pm_engine",
                f"serving worktree 清理失败 '{wt_path}'（非阻塞，rc={r.returncode}）: "
                f"{(r.stderr or r.stdout).strip()[-200:]}",
            )
        prune = subprocess.run(
            ["git", "-C", str(pipeline._context.project_root), "worktree", "prune"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if prune.returncode != 0:
            pipeline._context.logger.warning(
                "pm_engine",
                f"serving worktree prune 失败 '{wt_path}'（非阻塞，rc={prune.returncode}）: "
                f"{(prune.stderr or prune.stdout).strip()[-200:]}",
            )
    except (OSError, subprocess.SubprocessError) as e:
        pipeline._context.logger.warning(
            "pm_engine", f"serving worktree 清理失败 '{wt_path}'（非阻塞）: {e}"
        )


# ── 被测实例登记制（verify-process-lifecycle D6）─────────────────
# serve.kind=command 与 _ensure_app_reachable 兜底 spawn 的实例创建时
# 向 .fenix/verify-serving/servers.json 登记（pid/port/spec/worktree），
# 停止时移除；spec 终局与 daemon 周期清扫按 /proc liveness 收割。


def _register_serving_instance(
    pipeline, spec_name: str, server, wt_path=None, hint_port=None
) -> None:
    """command 型实例创建时登记。幂等：同 (pid,spec) 已登记则跳过。"""
    try:
        port = getattr(server, "port", None) or hint_port or 0
        ServingRegistry(pipeline._context.project_root, pipeline._context.logger).register(
            server.pid, port, spec_name, wt_path or ""
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine", f"serving 实例登记失败 '{spec_name}'（非阻塞）: {e}"
        )


def _unregister_serving_instance(pipeline, spec_name: str, server) -> None:
    """command 型实例停止时移除登记。幂等：无匹配条目安全空转。"""
    try:
        ServingRegistry(pipeline._context.project_root, pipeline._context.logger).remove(
            server.pid, spec_name
        )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine", f"serving 实例登记移除失败 '{spec_name}'（非阻塞）: {e}"
        )


def _evict_spec_serving(pipeline, spec_name: str) -> None:
    """spec 终局（done/verified）后回收其被测实例并驱逐缓存。

    command 型：stop 进程 + 移除 servers.json 登记 + 移除 serving worktree；
    static 型：stop 实例。幂等：无缓存条目/无登记时安全空转。
    主树 static 共享实例（缓存键 "main"）不在此列（多 spec 共享，保留）。
    """
    cache = pipeline.__dict__.get("_contract_static_servers", {})
    old = cache.pop(spec_name, None)
    if old is None:
        return
    server = old.get("server")
    try:
        if server is not None and hasattr(server, "pid"):
            # 登记过的实例（CommandVerifyServer 或兜底 spawn Popen）同步移除
            pipeline._unregister_serving_instance(spec_name, server)
        if server is not None:
            # code-review 07bce05c191b：去掉 ok 门——CommandVerifyServer 的
            # boot.log 句柄唯一关闭点是 stop()，ok=False 跳过会泄漏 fd；
            # stop 自身对已死进程安全（killpg 已捕 ProcessLookupError），
            # 与 _ensure_serving_worktree 的无条件清理口径对齐
            server.stop()
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine", f"spec 终局实例回收失败 '{spec_name}'（非阻塞）: {e}"
        )
    wt = old.get("wt_path")
    if wt:
        pipeline._remove_serving_worktree(wt)


def _current_instance_base_url(pipeline, spec_name: str) -> str:
    """本轮被测实例的 base_url（契约统一供给，引擎分发给各 Runner）。

    取代旧「从候选场景 navigate 步骤文本正则考古 base_url」的回退逻辑
    （该逻辑在场景失联时会漏判）：serve 流程已确定实例地址，直接取。

    优先级：
      1. ``_contract_static_servers`` 缓存中的 server.base_url
         （契约 static/command 两型：worktree 作用域键=spec_name、
         主树 static 共享实例键="main"）；
      2. 无契约兜底 spawn（commands.start）时查 serving 登记；
      3. 均无 → 空串（引擎/web runner 落回 navigate 考古，api runner
         无实例形态探针保守健康）。
    """
    cache = pipeline.__dict__.get("_contract_static_servers", {})
    for key in (spec_name, "main"):
        entry = cache.get(key)
        if entry is None:
            continue
        srv = entry.get("server") if isinstance(entry, dict) else entry
        if srv is not None and getattr(srv, "base_url", ""):
            # verify-process-lifecycle D6 配套：缓存实例可能已被
            # serving_registry 周期清扫收割（spec 轮间回 implementing 时
            # 「无在飞 spec」即杀进程）——对已死实例不得当作现存可达
            # 实例返回，否则契约轻量自证/探针探死端口永久失败，
            # 环境死循环（fix-dashboard-fault-isolation 实证）。
            # StaticVerifyServer 无 ok 属性（线程驻留），getattr 默认
            # True 保持原行为；CommandVerifyServer.ok 含进程 liveness。
            if not getattr(srv, "ok", True):
                continue
            return srv.base_url
    # 兜底 spawn（commands.start，无契约）：serving 登记里的端口。
    # code-review a2acf612103e：登记按追加序落盘（entries() 最老在前），
    # 实例死亡后重 spawn 的场景下同 spec 会同时存在旧死条目与新活条目，
    # 命中首个（最老）匹配会把整轮请求打向死端口——按 /proc 存活过滤
    # （复用 serving_registry.pid_alive，pid 非法/非正按死亡剔除，口径同
    # sweep），多匹配时取 registered_at 最新；与上方缓存路径的死亡实例
    # 守卫（ok 门）同口径。
    try:
        reg = ServingRegistry(pipeline._context.project_root, pipeline._context.logger).entries()
        candidates = [
            e
            for e in reg or []
            if isinstance(e, dict)
            and e.get("spec") == spec_name
            and e.get("port")
            and isinstance(e.get("pid"), int)
            and e["pid"] > 0
            and pid_alive(e["pid"])
        ]
        if candidates:
            newest = max(candidates, key=lambda e: e.get("registered_at") or 0)
            return f"http://127.0.0.1:{newest['port']}"
    except Exception:
        pass
    return ""


# ── serving dist 新鲜度探针（fix-verdict-env-exemption-admin-handshake 2.1/2.2）──
# add-session-composer 2026-09-25 事故：verify prepare 的 build 在 serving
# worktree 侧跑，刷不到主树常驻被测实例——merge-back 重建是唯一刷新点且
# 失败仅 logger.error，主树 dist 陈旧无人现场重建，空态文案类断言整轮伪
# env 失败被裁决豁免放行。探针把「产物新鲜」变成开跑前置条件，重建动作
# 自 merge-back 单点扩散到 serving 层（design D3：构建契约与 merge-back
# 同源，不在 serving 层硬编码 npm run build）。


def _dist_probe_scenario_sid(sc) -> str:
    """场景元素 → sid（TestScenario 对象 / dict 双形态归一，防御性兜底空串）。"""
    if isinstance(sc, dict):
        return str(sc.get("scenario_id") or sc.get("id") or "")
    to_dict = getattr(sc, "to_dict", None)
    if callable(to_dict):
        try:
            d = to_dict()
            if isinstance(d, dict):
                return str(d.get("scenario_id") or d.get("id") or "")
        except Exception:  # noqa: BLE001
            pass
    return str(getattr(sc, "scenario_id", "") or getattr(sc, "id", "") or "")


def _probe_dist_freshness(pipeline, spec_name: str) -> str:
    """verify run 前 dist 新鲜度探针（serving-dist-freshness-probe）。

    比对口径（design D3）：dashboard static src 树最新 mtime vs served dist
    入口产物（``dist/index.html``）mtime——src 较新即判滞后。不做内容哈希
    （全树哈希开销大且 vite 产物 hash 文件名会误报）。探针在验证场景开跑前
    执行一次（每次 run 至多一次），场景间不重复。

    直通形态（零动作零副作用，恒返回空串）：
      - 被测实例为 worktree 自建形态（``_contract_static_servers`` 缓存条目
        带 wt_path：prepare 已在本 worktree 构建，产物天然新鲜）；
      - 无被测实例登记（纯 cli 轮 / serving 未建立）；
      - dashboard static src 树不存在（被测项目非 dashboard 形态，探针无对象）；
      - served dist 入口产物不存在（从未构建，交既有 prepare 流程兜底，
        不在本探针制造新失败模式）；
      - dist 新鲜（构建时间不早于 src 最新内容时间）。

    Returns:
        空串 = 探针通过（新鲜或直通），可以开跑场景；
        非空 = 探针判滞后且自动重建失败的错误现场（构建失败尾部日志）——
        调用方 MUST NOT 以陈旧 dist 静默开跑，按环境性失联语义处置。
    """
    from core.worktree_manager import DASHBOARD_STATIC_ROOT
    from core.worktree_manager.dist_conflicts import run_dist_build

    # ── 被测实例形态判定：worktree 自建形态直通 ──
    # 缓存形态：worktree 条目为 dict 且带 wt_path；主树 static 共享实例
    # （键 "main"）缓存的是 server 对象本身；主树 command 实例为 dict 无
    # wt_path。取本轮实例与 _current_instance_base_url 同优先级（spec 优先，
    # 回落 "main"）。
    cache = pipeline.__dict__.get("_contract_static_servers", {})
    entry = cache.get(spec_name)
    if not isinstance(entry, dict):
        entry = cache.get("main")
    if isinstance(entry, dict) and entry.get("wt_path"):
        return ""  # worktree 自建：本轮产物即 prepare 构建，探针天然新鲜

    project_root = Path(pipeline._context.project_root)
    src_root = project_root / DASHBOARD_STATIC_ROOT / "src"
    if not src_root.is_dir():
        return ""  # dashboard static src 不存在：非该形态，探针无对象
    dist_entry = project_root / DASHBOARD_STATIC_ROOT / "dist" / "index.html"
    if not dist_entry.exists():
        return ""  # served dist 从未构建：交既有 prepare 流程兜底

    # rglob 枚举与 stat 之间存在文件系统竞态（并发构建清理、编辑器临时文件
    # 消失、权限变化）：单文件 stat 失败跳过该文件，不向上抛 OSError——
    # 探针恒直通或判滞后，不制造新失败模式（code-review item 77b966f9c240）。
    src_mtimes: list = []
    for p in src_root.rglob("*"):
        if not p.is_file():
            continue
        try:
            src_mtimes.append(p.stat().st_mtime)
        except OSError:
            continue
    if not src_mtimes:
        return ""  # src 树无可 stat 文件（竞态清空）：直通
    src_latest = max(src_mtimes)
    try:
        dist_mtime = dist_entry.stat().st_mtime
    except OSError:
        return ""  # mtime 不可读：不制造新失败模式，直通
    if dist_mtime >= src_latest:
        return ""  # dist 新鲜：零动作直通（无重建、无额外副作用）

    # ── 滞后：先自动重建再开跑（构建契约与 merge-back 同源）──
    pipeline._context.logger.warning(
        "pm_engine",
        f"dist 新鲜度探针判滞后 '{spec_name}'（src 最新 mtime {src_latest:.0f} "
        f"> dist/index.html mtime {dist_mtime:.0f}）— 自动重建 dist 后开跑",
    )
    error_detail: list = []
    if run_dist_build(
        project_root, DASHBOARD_STATIC_ROOT, pipeline._context.logger,
        error_detail=error_detail,
    ):
        pipeline._context.logger.info(
            "pm_engine",
            f"dist 自动重建成功 '{spec_name}' — served dist 已含最新 src，开跑场景",
        )
        return ""
    detail = (error_detail[-1] if error_detail else "").strip() or "构建失败（无尾部日志）"
    err = f"dist 新鲜度探针判滞后且自动重建失败，拒绝以陈旧 dist 静默开跑：{detail}"
    pipeline._context.logger.error("pm_engine", f"dist 重建失败 '{spec_name}': {err}")
    return err


def _dist_probe_block_report(pipeline, spec_name: str, scenarios, probe_err: str) -> dict:
    """探针重建失败的环境性失联报告（重建失败 MUST NOT 静默开跑）。

    合成全批 blocked-env 报告（每场景 ``env_probe_detail`` 携带构建失败
    尾部日志，与引擎 env 门探针失联轮同形态），交既有阶段 2.6
    ``_handle_env_blocked_inconclusive`` 处置——该轮按 blocked-env/inconclusive
    路径回 implemented 重验（重验轮探针先行，重建成功即真实复跑），穷尽后
    走既有 B7 升级通道呼叫 admin，供豁免握手与 admin 升级链消费。
    """
    from core.verdict_check import save_report

    blocked = [
        {
            "scenario_id": sid or f"scenario-{i + 1}",
            "status": "blocked-env",
            "env_blocked": True,
            "env_probe_detail": probe_err,
        }
        for i, sid in enumerate(_dist_probe_scenario_sid(sc) for sc in scenarios)
    ]
    report = {
        "spec": spec_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total": len(blocked),
            "passed": 0,
            "warnings": len(blocked),
            "failed": 0,
            "errors": 0,
            "blocked_env": len(blocked),
        },
        "scenarios": blocked,
        "dist_probe": {"stale": True, "error": probe_err},
    }
    try:
        save_report(pipeline._context.project_root, spec_name, report)
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"dist 探针阻断报告写盘失败 '{spec_name}'（不影响本轮处置）: "
            f"{type(e).__name__}: {e}",
        )
    return report


def _ensure_app_reachable(pipeline, spec_name: str) -> tuple:
    """验证前确保应用可达：自动启动 commands.start、处理端口冲突。

    最终用户验证为必选项：场景执行前先保证应用可被浏览器访问；
    若不可达则自动启动服务（commands.start），端口冲突时换端口重试
    （改写场景 URL）。仅在「需用户参与（如收验证码/登录）」或
    「判定无法解决」时才返回不可达，由上层判定而非静默通过。

    Returns:
        (reachable, user_blocked, note)
        - reachable: 自愈后应用是否可达
        - user_blocked: 是否为需用户参与而无法自动验证（预留判定位）
        - note: 人类可读说明（供错误展示）
    """
    # D9：经包命名空间延迟解析，使 patch(
    #   "core.pm_engine.verification.load_verify_contract") /
    #   "core.pm_engine.verification.ensure_main_tree_deps" /
    #   "core.pm_engine.verification.run_prepare_steps" 生效
    import core.pm_engine.verification as _facade

    scenarios_path = (
        pipeline._context.project_root
        / ".fenix"
        / "verify-progress"
        / spec_name
        / "test_scenarios.json"
    )
    if not scenarios_path.exists():
        return True, False, ""
    try:
        data = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except Exception as e:
        # code-review 82db4da2af52：解析失败与下方根非数组同属「场景集损坏」
        # 形态，同级 WARNING 留痕（附异常类型摘要）后再按既有放行语义返回，
        # 不静默放行断排障线索。
        pipeline._context.logger.warning(
            "pm_engine",
            f"验证场景文件解析失败（场景集损坏），可达性门禁跳过: "
            f"{scenarios_path} ({type(e).__name__}: {e})",
        )
        return True, False, ""
    # code-review bbf71fc97695：根非数组＝场景集损坏——直接迭代会产出字符串
    # 键、全被 isinstance 过滤，kinds 恒空而提前判可达（serve/ready 门禁整段
    # 跳过）。正常链路里上层 load_scenarios 已先拒非数组并退回 plan，此处为
    # 纵深防御：留痕后按既有放行形态返回，不静默按空 kinds 放行。
    if not isinstance(data, list):
        pipeline._context.logger.warning(
            "pm_engine",
            f"验证场景文件根非数组（场景集损坏），可达性门禁跳过: {scenarios_path}",
        )
        return True, False, ""

    # ── 契约形态按场景集反推（verify-runner-engine D4：serve/ready 必要性
    # 由场景集 kind 组成决定，零新增字段）──
    # 纯 cli 场景集：serve/ready 全省（不回退 commands.start——无人消费的
    # 实例不拉起）；契约 prepare 仍执行（构建/命令可用性是唯一环境门）。
    # 含 web/api 场景：serve（或 commands.start 兜底）必须有效，缺失时
    # 下方报明确错误打回 plan。
    kinds = {str(sc.get("kind", "web")) for sc in data if isinstance(sc, dict)}
    if kinds and kinds <= {"cli"}:
        contract = _facade.load_verify_contract(
            pipeline._context.project_root, pipeline._context.logger
        )
        if contract is not None and contract.prepare:
            # 纯 cli 无实例形态：不建 serving worktree，prepare 在主树执行
            # （add-main-tree-deps-provision：主树 prepare 前按 prepare cwd
            # 集合预装依赖，防 add-ssh-foundation 事故 exit 127 复发；本 SPEC
            # 入口预检在其后的 spawn 点——顺序：供给 → prepare → 预检 → spawn。）
            _facade.ensure_main_tree_deps(
                pipeline._context.project_root,
                sorted({(s.cwd or ".") for s in contract.prepare}),
                mode=resolve_deps_mode(
                    contract, pipeline._context.config_reader("verify.deps_mode", "")
                ),
                logger=pipeline._context.logger,
            )
            err = _facade.run_prepare_steps(contract, pipeline._context.project_root)
            if err:
                return False, False, f"验证契约 prepare 失败: {err}"
        return True, False, "纯 cli 场景集，跳过 serve/ready（无实例形态）"
    if not kinds:
        return True, False, ""

    # 收集场景实例入口 URL（web navigate / api http_request、sse_connect）
    urls: list[str] = []
    for sc in (data if isinstance(data, list) else []):
        if not isinstance(sc, dict):
            continue
        for step in sc.get("steps", []) or []:
            if not isinstance(step, dict):
                continue
            action = step.get("action")
            if action == "navigate":
                # navigate 目标 URL 存于 value（见 scenarios.TestStep）：191 个场景
                # 全部用 value 携带链接，target/url 为空。旧代码读 url/target 导致
                # urls 恒空，_ensure_app_reachable 恒判可达，可达性门禁永不触发。
                u = str(step.get("value") or step.get("url") or step.get("target") or "")
            elif action in ("http_request", "sse_connect"):
                # api 场景打同一实例（BASE_URL 铁律扩展：URL origin 全量改写），
                # 入口 URL 同样参与可达性探测
                u = str(step.get("url") or "")
            else:
                continue
            if u.startswith("http") and u not in urls:
                urls.append(u)

    # ── 声明式验证契约（.fenix/verify.yaml，字段语义见 verify_contract.py）──
    # 场景必须打「被测实现 fresh 构建出的可运行形态」。契约存在时：prepare
    # 重建产物 → static 无条件新鲜服务 + 场景 origin 全量改写（下方「已可达
    # 即跳过」捷径对构建型应用＝陈旧产物陷阱，契约 static 模式禁用）→ ready
    # 探针放行。契约缺失时维持 commands.start 旧行为（存量项目零迁移）。
    contract = _facade.load_verify_contract(
        pipeline._context.project_root, pipeline._context.logger
    )
    if contract is not None:
        serve = contract.serve
        scope = (
            str(pipeline._context.config_reader("verify.static_scope", "main") or "main")
            .strip()
            .lower()
        )
        wt_scope = scope == "worktree"
        # 主树 prepare 仅在实例落于主树时需要——worktree 作用域在
        # serving worktree 内构建（共享助手），主树构建纯属双倍等待
        # （add-main-tree-deps-provision 锚点：该案在此主树 prepare 前做
        # 依赖供给，本 SPEC 预检在其后 spawn 前——供给 → prepare → 预检
        # → spawn。）
        if contract.prepare and not wt_scope:
            # add-main-tree-deps-provision：主树 prepare 前按 prepare cwd
            # 集合预装依赖（本 SPEC 预检在其后 spawn 前——供给 → prepare
            # → 预检 → spawn）
            _facade.ensure_main_tree_deps(
                pipeline._context.project_root,
                sorted({(s.cwd or ".") for s in contract.prepare}),
                mode=resolve_deps_mode(
                    contract, pipeline._context.config_reader("verify.deps_mode", "")
                ),
                logger=pipeline._context.logger,
            )
            err = _facade.run_prepare_steps(contract, pipeline._context.project_root)
            if err:
                return False, False, f"验证契约 prepare 失败: {err}"
        if serve and serve.kind == "static":
            if wt_scope:
                return pipeline._serve_static_in_worktree(spec_name, contract, scenarios_path)
            return pipeline._serve_static_in_main(spec_name, contract, scenarios_path)
        if serve and serve.kind == "command" and serve.cmd:
            if wt_scope:
                return pipeline._serve_command_in_worktree(spec_name, contract, scenarios_path)
            # command + main：主树项目根为 cwd 的契约实例路径（D2），
            # 不再穿透 legacy（start_cmd_override/serve_port_hint 仅供
            # legacy 链消费，此处已无浆可流）。
            return pipeline._serve_command_in_main(spec_name, contract, scenarios_path)

    def _probe(u: str, timeout: float = 2.0, http_error_ok: bool = False) -> bool:
        try:
            req = urllib.request.Request(
                u, method="GET", headers={"User-Agent": "fenix-verify-probe"}
            )
            with urllib.request.urlopen(req, timeout=timeout):
                return True
        except urllib.error.HTTPError:
            # 4xx/5xx 同样说明该端口已有 HTTP 服务在应答：根路径 404 的
            # API-only 应用不应被判不可达（连接拒绝/超时仍为阴性）
            return http_error_ok
        except Exception:
            return False

    # code-review 9105bbfb5bc7：urls 为空时下方 all() 恒真（vacuous true），
    # 可达性门禁与 commands.start 自启会被整体跳过——场景集含 web/api（纯
    # cli 已在上方 return）但步骤无 http 绝对 URL 时显式留痕，不静默放行
    if not urls:
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景 kind 集={','.join(sorted(kinds))} 但未收集到 http 绝对 URL，"
            "可达性探测跳过（空集合 all() 恒真）：请检查场景 navigate/"
            "http_request 步骤是否携带绝对地址，或补 .fenix/verify.yaml serve 契约",
        )

    # 1) 直接探测：已可达则无需自愈（4xx/5xx 同样视为服务在应答——urls 均
    #    经上方 http 前缀过滤，语义与探活环/恢复路径统一，见 _probe 注释）
    if all(_probe(u, http_error_ok=True) for u in urls):
        return True, False, ""

    # 2) 自愈：无契约路径（契约 command 分支已在上方 return），
    # 直接回退 commands.start（旧行为）
    start_cmd = str(pipeline._context.config_reader("commands.start", "") or "").strip()
    if not start_cmd or start_cmd in ("echo 'No start command configured yet'",):
        kind_label = "、".join(sorted(kinds))
        # 契约缺失/损坏：产生 verify_contract_missing 信号派发 Administrator 起草
        # （设计 D1：确定性死局不等 4 次失败计数与升级冷却）
        note = (
            f"场景集含 {kind_label} 场景但无 serve 配置"
            f"（.fenix/verify.yaml serve 段或 config commands.start 兜底）"
            f"——已派发 Administrator 起草验证契约"
        )
        # 检测是否为契约解析失败（文件存在但 YAML 解析失败）
        contract_path = pipeline._context.project_root / ".fenix" / "verify.yaml"
        parse_error = False
        if contract_path.is_file() and contract is None:
            # 文件存在但 load_verify_contract 返回 None = 解析失败
            parse_error = True
        # code-review 3f06a4894b5b：信号写入收敛到共用助手
        # pipeline._write_verify_contract_missing（契约相关 fail-fast 统一出口，
        # 失败由助手内部记 error），parse_error 等差异并入 evidence 字符串
        pipeline._write_verify_contract_missing(
            spec_name,
            note,
            (
                f"项目根={pipeline._context.project_root}; "
                f"场景kind集={','.join(sorted(kinds))}; "
                f"parse_error={'是' if parse_error else '否'}"
            ),
            recommended_action=(
                "Administrator 起草 .fenix/verify.yaml 验证契约："
                "检查项目构建命令、静态目录、服务启动方式；"
                "草稿写临时路径 → bin/fenix_verify_contract.py 自证 → "
                "全通才落位 → git 提交 → spec 复位 ready 触发重验证"
            ),
        )
        return False, False, note

    # 端口注入（与 worktree 路径同机制）：cmd 引用 {port} 时分配空闲
    # 端口替换并导出 FENIX_VERIFY_PORT——主树兜底自启同样不撞既有实例。
    # 无契约路径无 serve.port 提示，base_port 仅来自 {port} 注入或
    # cmd 内 --port|-p 数字（commands.start 形态）。
    base_port = None
    injected_port = None
    # 入口存在性预检见原文（code-review 77e9753fae9c）：保留替换前的原 cmd，
    # {port} 替换只作用于 spawn 用的 start_cmd（与契约 spawn 路径同口径）
    orig_start_cmd = start_cmd
    if "{port}" in start_cmd:
        injected_port = find_free_port()
        start_cmd = start_cmd.replace("{port}", str(injected_port))
        base_port = injected_port
    else:
        pm = re.search(r"(?:--port|-p)\s+(\d+)", start_cmd)
        if pm:
            base_port = int(pm.group(1))

    pipeline._context.logger.warning(
        "pm_engine",
        f"验证目标应用不可达，自动启动服务: {start_cmd}",
    )

    # 入口存在性预检（design D1）：{port} 替换前的原 cmd 检查（与契约
    # spawn 路径同口径——{port} 不在路径段）；主树兜底自启同样在 spawn
    # 前校验入口存在性——serve.cmd 入口指向不存在文件时 fail-fast（场景
    # 执行数=0，确定性错误不等探活超时浪费 30s）；commands.start 等非脚本
    # 型运行时形态由解析器返回 None 放行（零误杀）。
    preflight_err = entry_preflight_error(orig_start_cmd, pipeline._context.project_root)
    if preflight_err:
        pipeline._write_verify_contract_missing(
            spec_name,
            f"{preflight_err}（入口存在性预检失败，spawn 前 fail-fast）",
            (
                f"start_cmd 原文={orig_start_cmd!r}; cwd={pipeline._context.project_root}; "
                f"来源=config commands.start 兜底"
            ),
            recommended_action=(
                "Administrator 修正入口路径：按错误信息中「候选」提示修正 "
                ".fenix/verify.yaml serve.cmd（或 commands.start），确认构建"
                "产物已生成后重验"
            ),
        )
        pipeline._escalate_env_blocked(
            spec_name,
            [preflight_err],
            title="验证环境阻塞（入口存在性预检失败）",
        )
        return False, False, preflight_err

    # 启动一次（后台、脱离会话、stdout/stderr 落盘 boot.log）；
    # 随后等待可达或扫描邻近端口。启动即死错误（Cannot find module 等）
    # 从 DEVNULL 吞掉改为落盘（design D3），探活失败时尾部附入告警。
    boot_log = pipeline._open_boot_log(spec_name)
    env = {**os.environ}
    if injected_port:
        env["FENIX_VERIFY_PORT"] = str(injected_port)
    try:
        proc = subprocess.Popen(
            start_cmd,
            shell=True,
            cwd=str(pipeline._context.project_root),
            stdout=boot_log,
            stderr=boot_log,
            start_new_session=True,
            env=env,
        )
    except Exception as e:
        boot_log.close()
        return False, False, f"启动验证目标应用失败: {e}"
    # verify-process-lifecycle D6：兜底 spawn 同登记纳入管理
    # （pid/spec/worktree 空、端口先按 hint，实际可达端口由探测修正）
    pipeline._register_serving_instance(spec_name, proc, hint_port=base_port)

    for _ in range(LEGACY_START_PROBE_ATTEMPTS):
        time.sleep(LEGACY_START_PROBE_INTERVAL_SECONDS)
        if all(_probe(u, http_error_ok=True) for u in urls):
            boot_log.close()
            return True, False, "已自动启动应用服务"

    # 场景 URL 端口 ≠ commands.start 端口（场景声明端口与框架分配端口不一致，
    # 如 3000 vs 8787）：应用已在 base_port 可达时，错的是场景端口而非应用——
    # 改写场景端口为实际端口后重探。原逻辑只改写 base_port 的出现处
    # （base_port → 扫描到的邻近端口），对「场景写了别的端口」完全无能为力，
    # 导致应用明明已启动却被判不可达、spec 永久卡死在 testing
    # （fix-fix-improve-verify-adjudication）。
    if base_port and _probe(f"http://127.0.0.1:{base_port}/", http_error_ok=True):
        foreign_ports = {
            m.group(1)
            for u in urls
            for m in [re.search(r":(\d+)" + _PORT_BOUNDARY, u)]
            if m and int(m.group(1)) != base_port
        }
        if foreign_ports:
            urls_new = []
            for u in urls:
                v = u
                for p in foreign_ports:
                    v = re.sub(r":%s" % p + _PORT_BOUNDARY, f":{base_port}", v)
                urls_new.append(v)
            # 复核探针与同函数其余探活点语义统一：4xx/5xx 同样证明 HTTP
            # 服务在应答（API-only 应用根路径 404/405 不判不可达）
            # code-review a736820044fb：先复核后改写（对齐下方邻近扫描块
            # 「探针全部通过后才改写」纪律）——改写经 _atomic_write_text
            # 持久落盘且无回滚，复核失败时残留的「外来端口→base_port」改写
            # 会让场景文件从此指向不被服务的端口、影响后续轮次。
            if all(_probe(u, http_error_ok=True) for u in urls_new):
                # code-review c0637b767434：改写成败向上反馈——持久化失败时
                # 内存探针虽通过，场景文件仍指向旧端口（下一轮复现同一
                # 「不可达→改写」循环），成功文案降级为可判别的警告性 note
                # （reachable 判定不变）
                persisted = [
                    pipeline._rewrite_scenario_port(scenarios_path, int(p), base_port)
                    for p in sorted(foreign_ports, key=int)
                ]
                boot_log.close()
                mismatch = (
                    f"场景声明端口 {sorted(foreign_ports, key=int)} "
                    f"与框架分配端口 {base_port} 不符"
                )
                if all(persisted):
                    return (True, False, f"{mismatch}，已改写场景端口并确认可达")
                return (
                    True,
                    False,
                    (
                        f"{mismatch}，内存探针通过但场景端口持久化失败"
                        "——场景文件仍指向旧端口，下一轮将复现同一改写循环"
                    ),
                )

    # 端口自动递增场景（如 --port 被占用时服务上探到邻近端口）：
    # 扫描 base_port 附近的端口，命中则改写场景 URL 并确认可达。
    # code-review 15745b057144：并发探测（复用 _probe_ports_responding，对齐
    # 契约路径）——原串行逐端口 _probe（timeout 2.0s）全部不响应时最坏
    # 50×2s≈100s 阻塞主流程；先并发取响应端口集合再升序复核，命中语义与
    # 串行版一致（首个复核通过的响应端口）。
    if base_port:
        # 探测口径与 _probe(http_error_ok=True) 一致：4xx/5xx 同样证明
        # HTTP 服务在应答（API-only 应用根路径 404 不判不响应）
        ports = sorted(
            _probe_ports_responding(
                range(base_port + 1, base_port + 51),
                probe=lambda p: _probe(f"http://127.0.0.1:{p}/", http_error_ok=True),
            )
        )
        for port in ports:
            urls_new = [
                re.sub(r":%d" % base_port + _PORT_BOUNDARY, f":{port}", u) for u in urls
            ]
            if all(_probe(u, http_error_ok=True) for u in urls_new):
                # code-review c0637b767434：持久化失败时成功文案降级为可判别
                # 的警告性 note（reachable 判定不变）
                persisted = pipeline._rewrite_scenario_port(
                    scenarios_path, base_port, port
                )
                boot_log.close()
                note = f"已自动启动应用服务（端口冲突，改用 {port}）"
                if persisted:
                    return True, False, note
                return (
                    True,
                    False,
                    (
                        f"{note}——但场景端口持久化失败，"
                        f"场景文件仍指向 {base_port}，下一轮将复现同一改写循环"
                    ),
                )

    # 探活最终失败：boot.log 尾部（≤2KB）附入错误串，启动即死错误
    # （Cannot find module 等）对 admin 直接可读（design D3）
    boot_tail = pipeline._read_boot_log_tail(spec_name, boot_log)
    boot_log.close()
    return (
        False,
        False,
        (
            "应用仍不可达：已自动执行 commands.start 并扫描邻近端口，"
            "仍无法连接（可能需人工启动/换端口，或属需用户参与的验证场景）" + boot_tail
        ),
    )


def _open_boot_log(pipeline, spec_name: str):
    """打开 .fenix/verify-serving/<spec>-boot.log（覆盖写句柄，design D3）。

    兜底/命令型 spawn 的 stdout/stderr 落盘于此（替代 DEVNULL 吞掉），
    启动即死错误（Cannot find module 等）对 admin 可读。启动前 truncate
    控制单轮大小（验证实例生命周期短，分钟级，接受无界增长）。
    """
    log_dir = Path(pipeline._context.project_root) / ".fenix" / "verify-serving"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        return open(log_dir / f"{spec_name}-boot.log", "wb")
    except OSError as e:
        # 打开 boot.log 失败时回退写 os.devnull，保持可 close 的文件对象语义
        # （subprocess.DEVNULL 是 int 哨兵值，调用方 boot_log.close() 会
        # AttributeError 炸穿降级路径）
        pipeline._context.logger.warning("pm_engine", f"boot.log 打开失败（回退写 os.devnull）: {e}")
        return open(os.devnull, "wb")


def _read_boot_log_tail(pipeline, spec_name: str, handle) -> str:
    """读 boot.log 尾部 ≤2KB 附入探活失败错误串（design D3）。

    句柄关闭前调用以 flush 子进程残留输出；读失败/空文件返回空串
    （不因取证自身异常改动错误判定）。
    """
    try:
        handle.flush()
    except Exception:
        pass
    try:
        log_path = (
            Path(pipeline._context.project_root)
            / ".fenix"
            / "verify-serving"
            / f"{spec_name}-boot.log"
        )
        # 只取尾部 ≤2KB：先 stat 定位再 seek 读取，不把整份 boot.log 读进
        # 内存（崩溃循环重启等失控子进程可把文件写到 GB 级）；尾部不足时
        # 从头读（seek 0）
        size = log_path.stat().st_size
        with log_path.open("rb") as f:
            f.seek(max(0, size - 2048))
            data = f.read(2048)
        if not data.strip():
            return ""
        tail = data.decode("utf-8", errors="replace").rstrip()
        return f"\n── boot.log 尾部（≤2KB）──\n{tail}"
    except Exception:
        return ""


def _rewrite_scenario_port(pipeline, scenarios_path: Path, old_port: int, new_port: int):
    """端口冲突换端口后，重写 test_scenarios.json 中**导航目标**的 URL 端口。

    2026-09-17 同类缺口修复（承 92228d33 的 origin 毒化事故）：旧实现与
    ``rewrite_scenarios_origin`` 同型——对 test_scenarios.json **整份文本**跑
    端口正则，会落进 CSS 属性选择器（``input[placeholder='http://127.0.0.1:55187']``）、
    注入数据（``seed.value``）、断言 ``expected`` 等字段，把「选择器字面量／
    测试数据」当「导航目标」改写。与 origin 路径共用
    ``_rewrite_scenario_target_values`` 骨架，只动作于 ``navigate`` /
    ``http_request`` / ``sse_connect`` 步骤的目标字段（见 verify_contract 的
    ``_ORIGIN_TARGET_FIELDS``）。

    与 origin 改写不同，端口替换 MUST NOT 要求 ``http(s)://`` 前缀：项目可能
    显式声明 ``http://localhost:3000`` 等地址，端口形态才是本函数的判定依据；
    正则自身以 ``:port`` + 边界锚定，裸域名与非 URL 文本不会被误改。

    Returns:
        bool：改写是否落盘——True 含「无待改写目标/非列表场景文件（无需
        落盘）」与原子写成功；JSON 解析/原子写异常为 False（WARNING 已记，
        异常不向上抛）。调用方据此把成功文案降级为可判别的警告性 note
        （code-review c0637b767434：改写未落盘时内存探针虽通过，场景文件
        仍指向旧端口，下一轮会复现同一「不可达→改写」循环）。
    """
    from core.verify_contract import _rewrite_scenario_target_values
    # code-review 22e59d9a5ffb：原子写复用 scenario_gate 助手（失败时清理
    # 残留 .tmp 再上抛，与 fastlane 同一收敛点），不再手写 tmp+replace
    from core.pm_engine.verification.scenario_gate import _atomic_write_text

    port_re = re.compile(r":%d" % old_port + _PORT_BOUNDARY)

    def _rewrite_value(value: str) -> tuple[str, int]:
        return port_re.subn(f":{new_port}", value)

    try:
        raw = json.loads(scenarios_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return True
        rewritten, n = _rewrite_scenario_target_values(
            raw, requires_http_scheme=False, rewrite_value=_rewrite_value
        )
        if not n:
            return True
        # 原子写（tmp+replace 收敛到 scenario_gate._atomic_write_text）：裸写
        # 中途 SIGKILL 会留下截断 JSON，下一轮加载误判 corrupt 触发人工裁决停摆；
        # 失败时助手清理残留 .tmp 再上抛，验证进度目录不再留孤儿 .tmp
        _atomic_write_text(
            scenarios_path, json.dumps(rewritten, ensure_ascii=False, indent=2)
        )
        pipeline._context.logger.info("pm_engine", f"已重写验证场景端口 {old_port} → {new_port}")
        return True
    except Exception as e:
        pipeline._context.logger.warning("pm_engine", f"重写验证场景端口失败: {e}")
        return False


def _serving_port_for_spec(pipeline, spec_name: str):
    """本轮 serving 端口（从契约 base_url 解析）；无实例形态返回 None。"""
    base_url = pipeline._current_instance_base_url(spec_name)
    if not base_url:
        return None
    try:
        from urllib.parse import urlparse

        return urlparse(base_url).port
    except Exception:
        return None


def _current_verify_round(pipeline, spec_name: str) -> int:
    """推导本轮验证轮次：``_verify_fail_rounds + 1``（首轮=1）。"""
    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    try:
        fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        fail_rounds = 0
    return fail_rounds + 1


def _port_responds(port: int) -> bool:
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                f"http://127.0.0.1:{port}/", headers={"User-Agent": "fenix-verify-probe"}
            ),
            timeout=1.0,
        ):
            return True
    except Exception:
        return False


def _probe_ports_responding(ports, probe=None) -> set:
    """并发探测一组端口，返回响应端口集合（fix-deferred-findings 性能修复）。

    legacy 邻近扫描（range(legacy_hint, legacy_hint+51)）原为串行 urlopen
    探测（每端口 timeout=1.0，最坏 2×51s 量级），改造为 ThreadPoolExecutor
    并发后总耗时收敛到单端口探测上限。每个端口探测结果独立（_port_responds
    无共享状态），并发仅缩短墙钟时间，返回集合与原串行探测逐元素一致。
    probe 可注入替代判定（code-review 15745b057144：兜底邻近扫描复用本函数
    并保持 _probe(http_error_ok=True) 的 4xx/5xx 亦算应答口径）。
    """
    from concurrent.futures import ThreadPoolExecutor

    # code-review 3efbae4631cf：入口归一为 list——pool.map 调用时即耗尽传入
    # 可迭代对象建 futures，zip 再迭代同一对象时，生成器/一次性迭代器会恒空、
    # 本函数静默返回空集；归一后不再隐式依赖可重复迭代性。
    ports = list(ports)

    if probe is None:
        probe = _port_responds

    with ThreadPoolExecutor(max_workers=16) as pool:
        return {p for p, ok in zip(ports, pool.map(probe, ports)) if ok}
