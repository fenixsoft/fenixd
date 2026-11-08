#!/usr/bin/env python3
"""
migrate_to_systemd.py — tmux 承载链 → systemd unit 一次性搬迁编排（add-systemd-hosting）。

编排顺序（design 决策 5，顺序即安全）：

  ① 写 unit 文件与 EnvironmentFile 候选稿（**不 enable**）
  ② 旧语义专用路径拆旧 tmux 承载链 + 旧 dashboard 实例 kill pid 等端口释放
  ③ env 候选稿提升（正式 env 缺失时补位）+ ``systemctl enable --now`` 两条 unit
  ④ 验收（进程 / 端口 / 退出码语义 / env 冒烟）

「先启用再拆」被否：撞单实例锁与 8787 接管守卫，进崩溃循环，且迁移后 stop
对 unit 不拥有的旧 tmux 链拆不动。② MUST NOT 复用迁移后启停函数（stop_daemon
已迁 systemctl 双轨，对 unit 不拥有的旧链按 no-op 谎报成功）——旧链拆解在此处
内联复刻退役前的直接信号链（快照/不重扫/补杀复核契约逐条保持），底层 /proc
探测复用 core.fenix_session 的既有实现（注释契约明令禁止复制第二套解析）。

安全门：

  - 缺省（无参数）＝ dry-run 预演：输出完整编排步骤清单（unit 全文、env 候选
    稿键名摘要——值含密钥不打印）、旧链定位结果、验收项；零副作用（不写文件、
    不动进程、不 enable）。``--dry-run`` 为显式同义。
  - ``--execute`` 才执行真切换。真切换是人工步骤（拆的是在跑 daemon 本尊），
    Agent 交付脚本落位 + dry-run 预演，人工审核 env 候选稿后自行执行。
  - stopped 项目拒绝迁移（design Non-Goals：不迁移 stopped 项目——env 候选稿
    以在跑进程 environ 为源，stopped 无源可捕）。

用法
----
    python3 bin/migrate_to_systemd.py [--project-root ROOT] [--dry-run] [--execute]

    --project-root   待迁移项目根（缺省＝框架主树自身，即 /fenix-setup 的常规
                     单项目部署）；其他项目显式传参。
    --dry-run        预演（与缺省行为相同，显式声明用）。
    --execute        执行真切换（人工步骤，先 dry-run 审核后再来）。

回滚（验收失败时按此恢复）：``systemctl disable --now`` 两条 unit → 旧配方
（tmux）重启托管链（见 /fenix-setup 配方的回滚小节）。
"""

import argparse
import hashlib
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

_THIS_DIR = Path(__file__).absolute().parent
_FENIX_DIR = _THIS_DIR.parent
if str(_FENIX_DIR) not in sys.path:
    sys.path.insert(0, str(_FENIX_DIR))

# 框架主树根（含 .fenix 的目录）＝ core 包解析路径的父目录：主树直启时
# _FENIX_DIR 即主树根；经任意项目 .fenix/bin 软链调用时 core 软链回主树
# （<主树>/core），resolve().parent 恒落回主树根——dashboard unit 的
# WorkingDirectory/entry/env 必须锚定主树而非调用入口项目。
FRAMEWORK_ROOT = (_FENIX_DIR / "core").resolve().parent

from core import systemd_hosting as sh  # noqa: E402
from core.fenix_session import (  # noqa: E402
    _alive_pids,
    _fenix_pids_under,
    _is_daemon_cmdline,
    _is_snapshot_proc_cmdline,
    is_running,
    resolve_root,
    supervisor_running,
)

# 旧 tmux 链拆除专用参数（与退役前 stop_daemon 同值）：轮询上界 30s、补杀后
# 复核 2s；dashboard 端口释放等待 15s（dashboard 无排水窗，秒级退出足够）
_STOP_POLL_SECONDS = 30
_STOP_POLL_INTERVAL = 0.5
_SIGKILL_RECHECK_SECONDS = 2
_DASHBOARD_RELEASE_SECONDS = 15
# 旧版固定 session 名（LEGACY_SESSION，退役前 _legacy_session_matches 兜底对象）
LEGACY_SESSION = "fenixd"
# ④ 验收探测：进程就绪轮询与端口 HTTP 探测上界（unit enable --now 后 supervisor
# 拉起 daemon 在秒级；20×0.5s=10s 足够，dashboard 同窗）
_ACCEPT_POLL_ATTEMPTS = 20
_ACCEPT_POLL_INTERVAL = 0.5


def log(msg: str) -> None:
    print(f"[migrate] {msg}", flush=True)


def retired_session_name(proot: Path) -> str:
    """内联复刻退役 session_name（tmux 拆链专用；core 已退役此派生）。

    与退役实现逐字同口径（md5(str(proot))[:6] + 非法字符折叠 + 点号折叠），
    保证拆链打中的就是旧链实际住着的那个会话名——派生口径漂移会让 kill-session
    打空、只能靠 SIGKILL 快照收口。
    """
    digest = hashlib.md5(str(proot).encode()).hexdigest()[:6]
    base = re.sub(r"[^A-Za-z0-9-]+", "-", proot.name).strip("-") or "project"
    return f"fenixd-{base}-{digest}"


def _legacy_session_matches(proot: Path) -> bool:
    """旧版固定 session ``fenixd`` 是否属于本项目（pane cwd 归一化比较）。

    复刻退役前 _legacy_session_matches：/proc 快照为空的退化路径下，daemon
    可能仍以旧版固定会话方式运行，仅 kill 唯一名会话打不中它。异常吞掉与
    退役实现同风格（是否真停由收口复核计入 error，不谎报）。
    """
    try:
        r = subprocess.run(
            ["tmux", "list-panes", "-t", LEGACY_SESSION, "-F", "#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return False
    if r.returncode != 0:
        return False
    for line in r.stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            if Path(line).expanduser().resolve() == proot:
                return True
        except Exception:
            continue
    return False


def port_occupied(port: int, host: str = "127.0.0.1") -> bool:
    """端口是否仍被监听（TCP connect 探测，0.5s 超时；connect 失败＝已释放）。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def dashboard_port(froot: Path) -> int:
    """dashboard 服务端口：config dashboard.port 合法则用之，否则 8787。

    与 hook_engine._dashboard_port 同口径（bool 前判排除、0 < port < 65536），
    验收端口探测须打真实配置端口而非字面 8787（自定义端口部署下打 8787
    会探到空端口误判失败）。
    """
    default = 8787
    try:
        from core.config import ConfigLoader

        config = ConfigLoader.load(froot / ".fenix" / "config.yaml")
        port = ConfigLoader.get(config, "dashboard.port", default)
        if isinstance(port, bool):
            return default
        port = int(port)
        if 0 < port < 65536:
            return port
    except Exception:
        pass
    return default


# ── ② 旧链拆解（旧语义专用路径；MUST NOT 复用迁移后启停函数）───────────────


def teardown_old_project_chain(proot: Path, dry_run: bool) -> dict:
    """拆旧 tmux 承载链：复刻退役前 stop_daemon 的直接信号链 + kill-session。

    契约逐条保持（fix-supervisor-hosting-chain 验证修复 BUG-01 及后续评审项）：
    入口一次快照停止目标；SIGTERM 只发快照中 daemon 形态的进程（supervisor 见
    stop 旗标自行退出）；超时兜底只杀快照内残留、绝不重扫（防误杀并发 start
    新拉起的进程）；补杀前 cmdline 结构化复核防 pid 复用误杀；无论成败清
    .fenix/stop。/proc 快照为空时无可杀目标——迁移前置条件已要求项目在跑
    （stopped 拒迁），快照为空属 /proc 异常，如实计入 error 不谎报。
    """
    session = retired_session_name(proot)
    stop_flag = proot / ".fenix" / "stop"
    target_pids = _fenix_pids_under(proot)
    if not target_pids:
        return {
            "ok": True,
            "error": None,
            "session": session,
            "was_running": False,
            "detail": "项目下未定位到 supervisor/daemon 进程（无需拆链）",
        }
    if dry_run:
        return {
            "ok": True,
            "error": None,
            "session": session,
            "was_running": True,
            "detail": f"[dry-run] 将拆链：session={session}，快照 pid={sorted(target_pids)}"
            f"（写 .fenix/stop → SIGTERM daemon → ≤{_STOP_POLL_SECONDS}s 轮询"
            f" → kill-session + 快照补杀 → 清 stop）",
        }

    # ① 写 stop（supervisor 主循环开头与 daemon 退出后都会检查）
    try:
        stop_flag.parent.mkdir(parents=True, exist_ok=True)
        stop_flag.touch()
    except OSError as e:
        return {
            "ok": False,
            "error": f"写 .fenix/stop 失败: {e}",
            "session": session,
            "was_running": True,
            "detail": None,
        }
    kill_errors = []
    try:
        # ② SIGTERM 快照中的 daemon 进程（supervisor 见 stop 旗标自行退出；
        # 项目根锚定复核防快照到信号之间 pid 复用误杀）
        for pid in target_pids:
            if _is_daemon_cmdline(pid, proot):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    pass
        # ③ 轮询等待快照进程全退（≤30s，只等快照 pid）
        deadline = time.time() + _STOP_POLL_SECONDS
        while time.time() < deadline:
            if not _alive_pids(target_pids):
                break
            time.sleep(_STOP_POLL_INTERVAL)
        # ④ 超时兜底：kill-session + 快照残留补 SIGKILL（绝不重扫）
        remaining = _alive_pids(target_pids)
        if remaining:
            for target in (session, LEGACY_SESSION):
                # 唯一名会话直接打；旧版固定会话先确认归属本项目再打
                #（pane cwd 匹配），不存在的会话/他项目的旧版会话不打
                if target == LEGACY_SESSION and not _legacy_session_matches(proot):
                    continue
                try:
                    subprocess.run(
                        ["tmux", "kill-session", "-t", target],
                        capture_output=True,
                        text=True,
                        timeout=5,
                    )
                except Exception:
                    pass
            for pid in remaining:
                # 补杀前复核：False（cmdline 已非本项目形态，疑似 pid 复用）
                # 跳过计入 error；None（/proc 不可读，进程已退出/不可判）照旧
                # 尝试，由 ProcessLookupError 兜底
                if _is_snapshot_proc_cmdline(pid, proot) is False:
                    kill_errors.append(
                        f"SIGKILL pid {pid} 补杀前复核失败"
                        "（cmdline 已非本项目 daemon/supervisor，疑似 pid 复用），跳过补杀"
                    )
                    continue
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                except PermissionError as e:
                    kill_errors.append(f"SIGKILL pid {pid} 权限不足: {e}")
            # 补杀后短轮询复核（D 态进程 SIGKILL 不响应时不谎报成功）
            recheck_deadline = time.time() + _SIGKILL_RECHECK_SECONDS
            while _alive_pids(target_pids) and time.time() < recheck_deadline:
                time.sleep(0.2)
            for pid in _alive_pids(target_pids):
                kill_errors.append(
                    f"SIGKILL pid {pid} 后仍存活（疑似不可中断态），daemon 可能未退出"
                )
        return {
            "ok": not kill_errors,
            "error": "; ".join(kill_errors) if kill_errors else None,
            "session": session,
            "was_running": True,
            "detail": f"旧链已拆（session={session}，快照 {len(target_pids)} 进程全退）",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": f"拆旧链失败: {e}",
            "session": session,
            "was_running": True,
            "detail": None,
        }
    finally:
        # ⑤ 无论成败清除 stop（避免项目永久拒绝启动）
        try:
            stop_flag.unlink()
        except OSError:
            pass


def teardown_old_dashboard(froot: Path, dry_run: bool) -> dict:
    """拆旧 dashboard 实例：旧配方直接 kill pid 并等待端口释放。

    不走 systemctl（unit 尚未接管）、不走 serve 接管守卫（那是启动方语义）——
    搬迁编排 own 旧实例生命周期。SIGTERM → 等端口释放（≤15s）→ 残留 SIGKILL
    → 再等（≤5s）。dashboard 无排水窗，SIGTERM 即干净退出 0。
    """
    pid = sh.find_framework_dashboard_pid()
    if pid is None:
        return {
            "ok": True,
            "error": None,
            "was_running": False,
            "detail": "未定位到在跑 dashboard 进程（无需拆旧实例）",
        }
    port = dashboard_port(froot)
    if dry_run:
        return {
            "ok": True,
            "error": None,
            "was_running": True,
            "detail": f"[dry-run] 将拆旧 dashboard：pid={pid}（SIGTERM → 等 :{port} 释放"
            f" ≤{_DASHBOARD_RELEASE_SECONDS}s → 残留 SIGKILL）",
        }
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError) as e:
        return {
            "ok": False,
            "error": f"SIGTERM 旧 dashboard pid {pid} 失败: {e}",
            "was_running": True,
            "detail": None,
        }
    errors = []
    deadline = time.time() + _DASHBOARD_RELEASE_SECONDS
    while time.time() < deadline:
        if not port_occupied(port):
            break
        time.sleep(0.5)
    if port_occupied(port):
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError) as e:
            errors.append(f"SIGKILL 旧 dashboard pid {pid} 失败: {e}")
        recheck = time.time() + 5
        while port_occupied(port) and time.time() < recheck:
            time.sleep(0.5)
        if port_occupied(port):
            errors.append(f"旧 dashboard 退出后 :{port} 仍未释放（疑似被无关进程占用）")
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "was_running": True,
        "detail": f"旧 dashboard 已退场（pid={pid}，:{port} 已释放）",
    }


# ── ①/③ 阶段 ────────────────────────────────────────────────────────────


def _project_hosting_pid(proot: Path) -> int | None:
    """env 捕获源 pid：优先 supervisor（unit ExecStart 即 supervisor），退 daemon。

    tmux 链下 supervisor→daemon 环境透传一致，但 unit 直接拉起的是 supervisor，
    supervisor 的 environ 才是迁移后 unit 环境的精确基线。
    """
    # 归类前先探活过滤（code-review item edac8c2b6952）：快照到分类之间退出
    # 的 pid，_is_daemon_cmdline 因 /proc/<pid>/cmdline 已不可读返回 False，
    # 会被误归入 supervisors 当作 env 捕获源（stage1 捕获与 stage4 冒烟随后
    # 对死 pid 读 environ，前者报误导性失败、后者漏检真实 supervisor）。
    # _alive_pids 只滤死 pid，活 pid 的归类行为不变；全灭时返回 None 走
    # 「未定位到进程」显式报错分支。
    pids = _alive_pids(_fenix_pids_under(proot))
    supervisors = [p for p in pids if not _is_daemon_cmdline(p, proot)]
    daemons = [p for p in pids if _is_daemon_cmdline(p, proot)]
    if supervisors:
        return int(supervisors[0])
    if daemons:
        return int(daemons[0])
    return None


def stage1_write_units_and_env(proot: Path, froot: Path, dry_run: bool) -> dict:
    """① 写 unit 文件与 EnvironmentFile 候选稿（不 enable）。

    dry-run 零副作用：env 只读进程 environ 出键名摘要（不落候选稿文件）、
    unit 只打印全文不写 systemd 目录。
    """
    errors = []
    plan = []

    def _env_summary(keys: dict, target: Path) -> str:
        return (
            f"env 候选稿 {target}{sh.ENV_CANDIDATE_SUFFIX}"
            f"（{len(keys)} 键：{', '.join(sorted(keys))}；值不打印，含密钥）"
        )

    # env 候选稿（源＝在跑进程 environ；stopped 项目已在 precondition 拒绝）
    sup_pid = _project_hosting_pid(proot)
    if sup_pid is not None:
        if dry_run:
            env = sh.read_process_env(sup_pid)
            if not env:
                errors.append(
                    f"无法读取进程 {sup_pid} 的 /proc/<pid>/environ，env 候选稿摘要缺失"
                )
            else:
                plan.append(_env_summary(sh.filter_session_identity(env), sh.project_env_file(proot)))
                # PATH 卫生结论行（add-dispatch-precheck-true-fallback 3.3）
                missing = sh.path_baseline_missing(env.get("PATH", ""))
                plan.append(
                    "PATH 卫生：完整（基线目录齐备）"
                    if not missing
                    else f"PATH 卫生：补齐 {'、'.join(missing)}（候选稿头部留痕原因）"
                )
        else:
            try:
                # path_report 收集实际追加目录（3.1 基线并集），摘要据此出
                # 「完整」/「补齐 <清单>」结论行（3.3）
                path_report: list = []
                keys = sh.capture_env_candidate(
                    sup_pid, sh.project_env_file(proot), path_report=path_report)
                plan.append(_env_summary(keys, sh.project_env_file(proot)))
                plan.append(
                    "PATH 卫生：完整（基线目录齐备）"
                    if not path_report
                    else f"PATH 卫生：补齐 {'、'.join(path_report)}（候选稿头部留痕原因）"
                )
            except sh.SystemdHostingError as e:
                errors.append(str(e))
    elif sh.project_env_file(proot).exists():
        # 已迁移态幂等重跑（code-review item 396d27404d7b）：前置检查对
        # 「无在跑进程但 unit 已装」按已迁移态放行，此态下不再有 env 捕获
        # 源；正式 env 在场即够用（stage3 提升与 stage4 冒烟均以正式 env
        # 为准），记 plan 放行使幂等修补（补 unit/重验）可走完编排
        plan.append(
            f"项目无在跑进程，正式 env 已在场，跳过 env 候选稿捕获（复用 {sh.project_env_file(proot)}）"
        )
    else:
        errors.append(
            "项目下未定位到 supervisor/daemon 进程，env 候选稿捕获跳过"
            "（unit 的 EnvironmentFile=- 可选前缀允许缺失，但迁移后 env 冒烟将失据）"
        )
    dash_pid = sh.find_framework_dashboard_pid()
    if dash_pid is not None:
        if dry_run:
            env = sh.read_process_env(dash_pid)
            if not env:
                # 与 project 分支同口径（code-review item 9e76b4403578）：读取
                # 失败显式报错留原因，预演输出不再静默缺 dashboard env 摘要
                errors.append(
                    f"无法读取进程 {dash_pid} 的 /proc/<pid>/environ，"
                    "dashboard env 候选稿摘要缺失"
                )
            else:
                plan.append(_env_summary(sh.filter_session_identity(env), sh.dashboard_env_file(froot)))
        else:
            try:
                keys = sh.capture_env_candidate(dash_pid, sh.dashboard_env_file(froot))
                plan.append(_env_summary(keys, sh.dashboard_env_file(froot)))
            except sh.SystemdHostingError as e:
                errors.append(str(e))
    else:
        plan.append("未定位到在跑 dashboard 进程，dashboard env 候选稿跳过（旧实例未跑）")

    # unit 文本（写入或预演打印；unit 本身无密钥可全文打印）
    project_unit = sh.unit_name_for(proot)
    project_text = sh.render_project_unit(proot)
    dashboard_text = sh.render_dashboard_unit(froot)
    if not dry_run:
        try:
            sh.write_unit_file(project_unit, project_text)
            sh.write_unit_file(sh.DASHBOARD_UNIT, dashboard_text)
        except sh.SystemdHostingError as e:
            errors.append(str(e))
    plan.append(f"unit {project_unit}（全文见上）→ {sh.SYSTEMD_UNIT_DIR}（不 enable）")
    plan.append(f"unit {sh.DASHBOARD_UNIT}（全文见上）→ {sh.SYSTEMD_UNIT_DIR}（不 enable）")
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "plan": plan,
        "project_unit": project_unit,
        "project_unit_text": project_text,
        "dashboard_unit_text": dashboard_text,
    }


def stage3_enable_units(proot: Path, froot: Path, dry_run: bool) -> dict:
    """③ env 候选稿提升 + ``systemctl enable --now`` 两条 unit。"""
    if dry_run:
        return {
            "ok": True,
            "error": None,
            "detail": "[dry-run] 将提升 env 候选稿（正式缺失时补位 0600）→ "
            f"systemctl daemon-reload + enable --now {sh.unit_name_for(proot)} "
            f"{sh.DASHBOARD_UNIT}",
        }
    errors = []
    # env 候选稿提升：正式 env 缺失时以候选稿补位（0600，同目录 rename 保权限）；
    # 已有正式 env 以正式为准（人工可能已审改，候选稿不覆盖）
    for env_path in (sh.project_env_file(proot), sh.dashboard_env_file(froot)):
        candidate = Path(f"{env_path}{sh.ENV_CANDIDATE_SUFFIX}")
        if env_path.exists() or not candidate.exists():
            continue
        try:
            os.replace(candidate, env_path)
            os.chmod(env_path, 0o600)
            log(f"env 候选稿已提升为正式 EnvironmentFile：{env_path}")
        except OSError as e:
            errors.append(f"env 候选稿提升 {env_path} 失败: {e}")
    # project unit 安装失败两种形态同口径（code-review item 8da64459abed）：
    # 软失败（ok=False）与硬失败（SystemdHostingError）都短路返回、不再安装
    # dashboard unit，detail 说明 dashboard unit 实际未落位——否则两条失败
    # 路径下 dashboard unit 是否安装取决于失败形态，回滚面不可预期。
    try:
        project = sh.install_project_unit(proot)
    except sh.SystemdHostingError as e:
        errors.append(str(e))
        return {
            "ok": False,
            "error": "; ".join(errors),
            "detail": f"project unit（{sh.unit_name_for(proot)}）安装异常，"
            f"{sh.DASHBOARD_UNIT} 未安装",
        }
    if not project["ok"]:
        errors.append(project["error"])
        return {
            "ok": False,
            "error": "; ".join(errors),
            "detail": f"project unit（{sh.unit_name_for(proot)}）安装失败，"
            f"{sh.DASHBOARD_UNIT} 未安装",
        }
    try:
        dash = sh.install_dashboard_unit(froot)
        if not dash["ok"]:
            errors.append(dash["error"])
    except sh.SystemdHostingError as e:
        errors.append(str(e))
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "detail": f"两条 unit 已 enable --now（project={sh.unit_name_for(proot)}，"
        f"dashboard={sh.DASHBOARD_UNIT}）",
    }


# ── ④ 验收 ───────────────────────────────────────────────────────────────


def probe_dashboard_http(port: int) -> bool:
    """端口 HTTP 可服务探测（任何 HTTP 响应即视为服务在场，与 hook_engine 同口径）。"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
            return True
    except urllib.error.HTTPError:
        return True  # 服务已响应（返回错误码也算在场，与 hook_engine._probe_dashboard 同口径）
    except Exception:
        return False


def _advance_quote_state(line: str, in_quote: bool) -> bool:
    """按 systemd EnvironmentFile 引号语义推进单引号折叠态（行内扫描）。

    引号区外的 ``\\'`` 是转义字面引号（_quoted_env_value 的 '\'' 序列）不翻
    转状态、引号区内 ``\\`` 为字面量——逐字符扫描而非引号计数，转义序列不
    破坏奇偶配对。
    """
    i = 0
    while i < len(line):
        ch = line[i]
        if not in_quote and ch == "\\":
            i += 2  # 引号区外反斜杠转义下一字符（串尾截断由切片语义兜底）
            continue
        if ch == "'":
            in_quote = not in_quote
        i += 1
    return in_quote


def _env_file_keys(env_path: Path) -> set:
    """EnvironmentFile 真实键名提取：按单引号配对折叠跨行值后逐行取键。

    正式 env 值由 systemd_hosting._quoted_env_value 落盘（含空白/引号/#/\\/$
    的值单引号包裹；裸值不含引号也不含换行），值内含换行时一个键跨多物理
    行，逐物理行 split("=") 会把续行中的 "x=y" 片段解析成伪键，env 冒烟据此
    误报「键缺席、EnvironmentFile 未被消费」（code-review item c84c230ef1f2）。
    折叠口径对齐 _quoted_env_value 的落盘形态语义：仅在单引号值外认 KEY= 行；
    systemd_hosting 侧只有渲染向函数、无文本解析函数可复用，故按其落盘形态
    在此处做键提取，不另造第二套值转义语义。
    """
    keys = set()
    in_quote = False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if not in_quote:
            if "=" in line and not line.lstrip().startswith("#"):
                keys.add(line.split("=", 1)[0])
            elif not line.strip() or line.lstrip().startswith("#"):
                continue  # 注释/空行不参与折叠态（人工注释含引号不污染配对）
        in_quote = _advance_quote_state(line, in_quote)
    return keys


def stage4_accept(proot: Path, froot: Path, dry_run: bool) -> dict:
    """④ 验收四件套：进程 / 端口 / 退出码语义 / env 冒烟。"""
    checks = []
    errors = []
    port = dashboard_port(froot)

    if dry_run:
        return {
            "ok": True,
            "error": None,
            "checks": [
                f"[dry-run] 将验收：① supervisor_running+is_running（≤"
                f"{_ACCEPT_POLL_ATTEMPTS * _ACCEPT_POLL_INTERVAL:.0f}s 轮询）"
                f"② :{port} HTTP 可服务 ③ unit 文本含 Restart=on-failure/"
                f"SuccessExitStatus={sh.SUPERVISOR_GAVE_UP_EXIT_CODE}"
                f"/FENIX_DASHBOARD_DETACH=1 ④ 新进程 environ 冒烟"
                f"（FENIX_DASHBOARD_DETACH=1 在场、CLAUDE_PID 缺席、"
                f"正式 env 键在 supervisor environ 复现）",
            ],
            "detail": None,
        }

    # ① 进程：unit 拉起的 supervisor 出现且 daemon 在跑
    deadline = time.time() + _ACCEPT_POLL_ATTEMPTS * _ACCEPT_POLL_INTERVAL
    while time.time() < deadline:
        if supervisor_running(proot) and is_running(proot):
            break
        time.sleep(_ACCEPT_POLL_INTERVAL)
    if supervisor_running(proot) and is_running(proot):
        checks.append("进程：unit 承载的 supervisor 与 daemon 均已就位")
    else:
        errors.append(
            f"enable --now 后 {_ACCEPT_POLL_ATTEMPTS * _ACCEPT_POLL_INTERVAL:.0f}s 内"
            " supervisor/daemon 未就位（journalctl -u "
            f"{sh.unit_name_for(proot)} 看现场）"
        )

    # ② 端口：dashboard HTTP 可服务
    deadline = time.time() + _ACCEPT_POLL_ATTEMPTS * _ACCEPT_POLL_INTERVAL
    while time.time() < deadline:
        if probe_dashboard_http(port):
            break
        time.sleep(_ACCEPT_POLL_INTERVAL)
    if probe_dashboard_http(port):
        checks.append(f"端口：:{port} HTTP 可服务")
    else:
        errors.append(
            f"dashboard 未在 :{port} 恢复 HTTP 可服务"
            f"（journalctl -u {sh.DASHBOARD_UNIT} 看现场）"
        )

    # ③ 退出码语义：unit 文本携带重启策略字段（真熔断演练不在迁移验收面，
    # 由 tests/test_systemd_hosting.py 与 supervisor 退出码单测覆盖）。
    # 验收对象取 /etc/systemd/system 下已落盘的 unit 文件（already 幂等路径
    # 不重写文件，落盘可能是旧模板版本）；落盘读取失败回退现场渲染模板
    try:
        project_text = (sh.SYSTEMD_UNIT_DIR / sh.unit_name_for(proot)).read_text(
            encoding="utf-8"
        )
    except OSError:
        project_text = sh.render_project_unit(proot)
    try:
        dashboard_text = (sh.SYSTEMD_UNIT_DIR / sh.DASHBOARD_UNIT).read_text(
            encoding="utf-8"
        )
    except OSError:
        dashboard_text = sh.render_dashboard_unit(froot)
    for label, text, needle in (
        (
            "退出码语义",
            project_text,
            f"SuccessExitStatus={sh.SUPERVISOR_GAVE_UP_EXIT_CODE}",
        ),
        ("退出码语义", project_text, "Restart=on-failure"),
        ("退出码语义", dashboard_text, "Restart=on-failure"),
        ("退出码语义", dashboard_text, "Environment=FENIX_DASHBOARD_DETACH=1"),
    ):
        if needle not in text:
            errors.append(f"{label}：unit 文本缺 {needle}")
    if not any("退出码语义" in e for e in errors):
        checks.append(
            f"退出码语义：unit 文本含 Restart=on-failure + "
            f"SuccessExitStatus={sh.SUPERVISOR_GAVE_UP_EXIT_CODE}（项目 unit）"
            " + FENIX_DASHBOARD_DETACH=1（dashboard unit）"
        )

    # ④ env 冒烟：新 dashboard 进程环境无会话身份键、DETACH 在场；正式 env
    # 的键在新 supervisor environ 复现（值不比对——进程可能已改写部分值，
    # 键集在场即 EnvironmentFile 被消费的证据）
    dash_pid = sh.find_framework_dashboard_pid()
    if dash_pid is None:
        errors.append("env 冒烟：未定位到 unit 承载的新 dashboard 进程")
    else:
        try:
            with open(f"/proc/{dash_pid}/stat", "rb") as f:
                stat = f.read().decode("utf-8", "replace")
            ppid = int(stat[stat.rindex(")") + 2 :].split()[1])
            if ppid != 1:
                errors.append(f"env 冒烟：dashboard pid {dash_pid} PPID={ppid}≠1（非 unit 承载形态）")
        except (OSError, ValueError, IndexError):
            pass
        denv = sh.read_process_env(dash_pid)
        if denv.get("FENIX_DASHBOARD_DETACH") != "1":
            errors.append("env 冒烟：新 dashboard environ 缺 FENIX_DASHBOARD_DETACH=1")
        leaked = [k for k in denv if k.startswith(("CLAUDE_PID", "CLAUDECODE", "CLAUDE_CODE_"))]
        if leaked:
            errors.append(f"env 冒烟：新 dashboard environ 泄漏会话身份键 {sorted(leaked)}")
        if not any("env 冒烟" in e for e in errors):
            checks.append(f"env 冒烟（dashboard）：DETACH=1 在场、会话身份键缺席（pid={dash_pid}）")
    sup_pid = _project_hosting_pid(proot)
    env_path = sh.project_env_file(proot)
    if sup_pid is not None and env_path.exists():
        formal_keys = _env_file_keys(env_path)
        senv = sh.read_process_env(sup_pid)
        missing = sorted(k for k in formal_keys if k not in senv)
        if missing:
            errors.append(
                f"env 冒烟：正式 EnvironmentFile 键在新 supervisor environ 缺席 {missing}"
                "（EnvironmentFile 未被消费或键被 systemd 拒解析）"
            )
        else:
            checks.append(
                f"env 冒烟（supervisor pid={sup_pid}）：正式 env {len(formal_keys)} 键全部复现"
            )
    return {
        "ok": not errors,
        "error": "; ".join(errors) if errors else None,
        "checks": checks,
        "detail": None,
    }


# ── 编排主入口 ───────────────────────────────────────────────────────────


def migrate(project_root: Path, framework_root: Path, dry_run: bool) -> int:
    """四阶段编排。返回进程退出码（0 成功，1 失败）。"""
    proot = resolve_root(str(project_root))
    froot = resolve_root(str(framework_root))
    mode = "dry-run 预演（零副作用）" if dry_run else "真切换（--execute）"
    log(f"迁移目标：项目 {proot}")
    log(f"框架主树：{froot}")
    log(f"执行模式：{mode}")

    # 前置检查：systemd 在位；项目非 stopped（design Non-Goals）；非双托管态
    if not sh.systemctl_available():
        log("FAIL：需要 systemd（systemctl 不可用）。tmux 承载已退役，请在 systemd 环境迁移。")
        return 1
    if dry_run:
        log("前置：systemctl 可用 ✓")
    old_pids = _fenix_pids_under(proot)
    project_unit_installed = False
    try:
        project_unit_installed = sh.unit_installed(sh.unit_name_for(proot))
    except sh.SystemdHostingError as e:
        log(f"FAIL：{e}")
        return 1
    if not old_pids and not project_unit_installed:
        log(
            "FAIL：项目为 stopped 态且 unit 未安装——不迁移 stopped 项目"
            "（design Non-Goals：env 候选稿以在跑进程 environ 为源，stopped 无源可捕）。"
            "请先以旧配方启动项目再迁移。"
        )
        return 1
    if dry_run:
        if old_pids:
            log(f"前置：项目在跑（快照 pid={sorted(old_pids)}）✓；unit 已装={project_unit_installed}")
        else:
            log(f"前置：项目无在跑进程（已迁移态，unit 已装={project_unit_installed}）✓")
    elif project_unit_installed:
        try:
            already_active = sh.unit_active(sh.unit_name_for(proot))
        except sh.SystemdHostingError:
            already_active = False
        if already_active:
            log(
                f"NOTE：{sh.unit_name_for(proot)} 已安装且活跃（可能已迁移过）；"
                "将继续拆旧链（若有残留）并幂等 enable，不会重建/重启已活跃 unit"
            )

    # ① 写 unit + env 候选稿（不 enable）
    log("--- ① 写 unit 文件与 env 候选稿（不 enable）---")
    s1 = stage1_write_units_and_env(proot, froot, dry_run)
    for line in s1["plan"]:
        log(line)
    if dry_run:
        print("--- 将写入的 unit 全文（无密钥）---")
        print(s1["project_unit_text"], end="")
        print(s1["dashboard_unit_text"], end="")
        print("--- unit 全文结束 ---")
    if not s1["ok"]:
        log(f"FAIL ①：{s1['error']}")
        _print_rollback(proot)
        return 1

    # ② 旧语义专用路径拆旧链
    log("--- ② 拆旧 tmux 承载链与旧 dashboard 实例（旧语义专用路径）---")
    t1 = teardown_old_project_chain(proot, dry_run)
    log(t1["detail"] or t1["error"] or "旧项目链拆解完成")
    if not t1["ok"]:
        log(f"FAIL ②：{t1['error']}")
        _print_rollback(proot)
        return 1
    t2 = teardown_old_dashboard(froot, dry_run)
    log(t2["detail"] or t2["error"] or "旧 dashboard 拆解完成")
    if not t2["ok"]:
        log(f"FAIL ②（dashboard）：{t2['error']}")
        _print_rollback(proot)
        return 1
    if not dry_run:
        log("无双托管窗口确认：旧链全退后才 enable（design 决策 5）✓")

    # ③ enable --now
    log("--- ③ env 候选稿提升 + systemctl enable --now ---")
    s3 = stage3_enable_units(proot, froot, dry_run)
    log(s3["detail"] or s3["error"] or "")
    if not s3["ok"]:
        log(f"FAIL ③：{s3['error']}")
        _print_rollback(proot)
        return 1

    # ④ 验收
    log("--- ④ 验收（进程/端口/退出码语义/env 冒烟）---")
    s4 = stage4_accept(proot, froot, dry_run)
    for line in s4["checks"]:
        log(f"验收 ✓ {line}")
    if not s4["ok"]:
        log(f"FAIL ④：{s4['error']}")
        _print_rollback(proot)
        return 1

    if dry_run:
        log("dry-run 预演完成：以上为真切换将执行的完整编排。")
        log("下一步（人工）：① 审核 env 候选稿（*.candidate，0600）补删 load-bearing 键"
            " → ② 确认无误后 `python3 bin/migrate_to_systemd.py --execute` 真切换"
            " → ③ 按验收清单核对 → 最小 agent spawn 冒烟")
    else:
        log("迁移完成：daemon/dashboard 已由 systemd unit 承载（开机自启）。")
        log("建议人工补一项最小 agent spawn 冒烟（design：切换冒烟=最小 agent spawn）。")
    return 0


def _print_rollback(proot: Path) -> None:
    log(
        "回滚配方：systemctl disable --now "
        f"{sh.DASHBOARD_UNIT} {sh.unit_name_for(proot)} → "
        "旧配方（tmux）重启托管链（/fenix-setup 回滚小节）"
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="tmux 承载链 → systemd unit 一次性搬迁编排（缺省 dry-run 预演）"
    )
    parser.add_argument(
        "--project-root",
        default=None,
        help="待迁移项目根（缺省＝框架主树自身）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="预演模式（与缺省行为相同，显式声明用）",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="执行真切换（人工步骤；先 --dry-run 审核后再来）",
    )
    args = parser.parse_args(argv)
    dry_run = not args.execute
    if args.dry_run and args.execute:
        parser.error("--dry-run 与 --execute 互斥")
    return migrate(
        Path(args.project_root) if args.project_root else FRAMEWORK_ROOT,
        FRAMEWORK_ROOT,
        dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
