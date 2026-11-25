#!/usr/bin/env python3
"""fenix_update.py — fenixd 框架与 dsh-plugins 更新 CLI。

bin/fenix_update.py check|apply|status —— 与 dashboard 更新面共用同一引擎
（core/self_update.py 检查 / core/self_update_apply.py 应用编排），无
dashboard 的 CLI-only 部署可用（design D7）。

用法：
    python3 bin/fenix_update.py check    # 同步检查并回写状态（可加 --json）
    python3 bin/fenix_update.py apply    # 触发分离编排进程后立即退出（受理即返）
    python3 bin/fenix_update.py status   # 打印 status.json 摘要（可加 --json）

退出码：0 = 成功（有可用更新 / 受理 / 状态读取成功）；1 = 无更新（仅
check：已是最新或 source/无插件安装态）；2 = 失败（查询失败 / 409 冲突 /
编排受理失败）。
"""

import argparse
import json
import sys
from pathlib import Path

# bin/ 直跑形态：框架根入 sys.path（与 bin/ 既有 CLI 同款装配）
_FRAMEWORK_ROOT = Path(__file__).resolve().parents[1]
if str(_FRAMEWORK_ROOT) not in sys.path:
    sys.path.insert(0, str(_FRAMEWORK_ROOT))

EXIT_OK = 0
EXIT_NO_UPDATE = 1
EXIT_FAILURE = 2


def _cmd_check(args) -> int:
    from core.self_update import load_update_config, run_check

    cfg = load_update_config()
    status = run_check("cli", framework_root=_FRAMEWORK_ROOT, config=cfg)
    framework = status.get("framework") or {}
    plugins = status.get("plugins") or {}
    if args.json:
        print(json.dumps(status, ensure_ascii=False, indent=1))
        return EXIT_OK
    if status.get("last_error"):
        print(f"检查失败: {status['last_error']}")
        return EXIT_FAILURE
    print(f"框架: 本地 {framework.get('local_version') or '—'}"
          f"（{framework.get('form')}）"
          f" 远端 {framework.get('remote_version') or '—'}")
    print(f"插件: 本地 {plugins.get('local_version') or '—'}"
          f"（{plugins.get('form')}）"
          f" 远端 {plugins.get('remote_version') or '—'}")
    if framework.get("update_available"):
        print(f"框架可更新 → {framework.get('remote_version')}："
              "执行 python3 bin/fenix_update.py apply 一键更新")
    if plugins.get("update_available"):
        print(f"dsh-plugins 可更新 → {plugins.get('remote_version')}")
    if not framework.get("update_available") and not plugins.get("update_available"):
        if framework.get("form") == "source":
            print("已是最新（源码形态：请以 git pull 更新，不参与制品更新）")
        else:
            print("已是最新")
        return EXIT_NO_UPDATE
    return EXIT_OK


def _cmd_apply(args) -> int:
    from core.self_update import FORM_SOURCE, read_framework_version, read_status
    from core.self_update_apply import spawn_apply

    local = read_framework_version(_FRAMEWORK_ROOT)
    if local.form == FORM_SOURCE:
        print("框架为源码形态（无 VERSION 文件），不参与制品更新——请 git pull")
        return EXIT_FAILURE
    st = read_status() or {}
    framework = st.get("framework") or {}
    if not framework.get("update_available"):
        print("无可用的框架更新（请先执行 check）")
        return EXIT_NO_UPDATE
    result = spawn_apply(framework_root=_FRAMEWORK_ROOT, source="cli")
    if result.get("ok"):
        print(f"更新编排已受理（分离进程 pid={result.get('pid')}）——"
              "进度与结果经 python3 bin/fenix_update.py status 轮询查看")
        return EXIT_OK
    print(f"更新受理失败: {result.get('error')}"
          + ("（409 冲突）" if result.get("conflict") else ""))
    return EXIT_FAILURE


def _cmd_status(args) -> int:
    from core.self_update import STATUS_PATH, read_status

    status = read_status()
    if args.json:
        print(json.dumps(status or {"checked": False}, ensure_ascii=False, indent=1))
        return EXIT_OK
    if not status:
        print(f"尚无更新检查记录（{STATUS_PATH} 不存在）——"
              "执行 python3 bin/fenix_update.py check 发起首次检查")
        return EXIT_OK
    framework = status.get("framework") or {}
    plugins = status.get("plugins") or {}
    apply_seg = status.get("apply") or {}
    print(f"上次检查: {status.get('last_check_at') or '—'}"
          + (f"（上次成功: {status['last_success_at']}）"
             if status.get("last_success_at") else ""))
    if status.get("last_error"):
        print(f"最近失败: {status['last_error']}")
    print(f"框架: {framework.get('local_version') or '—'}"
          f"（{framework.get('form')}） ← {framework.get('remote_version') or '—'}"
          + ("  [可更新]" if framework.get("update_available") else ""))
    print(f"插件: {plugins.get('local_version') or '—'}"
          f"（{plugins.get('form')}） ← {plugins.get('remote_version') or '—'}"
          + ("  [可更新]" if plugins.get("update_available") else ""))
    phase = apply_seg.get("phase")
    if phase and phase != "idle":
        print(f"应用编排: {phase}"
              + (f"（阶段: {' → '.join(s.get('stage', '?') for s in apply_seg.get('stages') or [])}）"
                 if apply_seg.get("stages") else "")
              + (f"  [失败阶段: {apply_seg['failed_stage']}]" if apply_seg.get("failed_stage") else ""))
    return EXIT_OK


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="fenix_update", description="fenixd 框架与 dsh-plugins 更新 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="同步检查更新并回写状态")
    p_check.add_argument("--json", action="store_true", help="输出完整状态 JSON")
    p_check.set_defaults(fn=_cmd_check)

    p_apply = sub.add_parser("apply", help="触发一键更新（分离编排进程，受理即返）")
    p_apply.add_argument("--json", action="store_true", help="输出受理结果 JSON")
    p_apply.set_defaults(fn=_cmd_apply)

    p_status = sub.add_parser("status", help="查看更新状态摘要")
    p_status.add_argument("--json", action="store_true", help="输出完整状态 JSON")
    p_status.set_defaults(fn=_cmd_status)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
