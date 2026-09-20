#!/usr/bin/env python3
"""fenix_verify_contract.py — 验证契约校验 CLI（Administrator 自证入口）。

用法:
    python bin/fenix_verify_contract.py [项目根目录]

    项目根目录缺省为当前目录。校验 .fenix/verify.yaml 三段契约（prepare/serve/ready），
    输出逐段结果，全通退出码 0。含 regression 段时额外做一次**可选**自证：按
    regression.cmd 跑一次确认 output 产出可解析 JUnit XML，结果作为独立一行输出，
    不计入退出码（三段判定语义不变——避免 1800s 级全量回归拖垮既有自证门）。

退出码:
    0 — 三段全部通过（prepare/serve/ready）
    1 — 契约文件不存在或解析失败
    2 — prepare 构建步骤失败
    3 — serve 实例启动/就绪失败
    4 — ready 就绪探针失败（含鉴别力自检）
    5 — 契约格式无效（serve 段非法）

示例:
    # 校验当前项目契约
    python bin/fenix_verify_contract.py

    # 校验指定项目契约
    python bin/fenix_verify_contract.py /path/to/project

    # 作为 Administrator 自证入口：草稿写临时路径后运行此 CLI，全通才落位
    python bin/fenix_verify_contract.py /path/to/project
    if [ $? -eq 0 ]; then
        cp /tmp/draft-verify.yaml /path/to/project/.fenix/verify.yaml
    fi
"""

import sys
from pathlib import Path

# 确保项目根在 sys.path 中（运行脚本时可能不在工作目录）
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.verify_contract import load_verify_contract, validate_contract
from core.regression import parse_junit_xml


def selfcheck_regression(project_root: Path) -> tuple:
    """可选 regression 段自证：按 cmd 跑一次确认 output 产出可解析 JUnit XML。

    返回 (ok, note)：ok 为 True/False/None（None=无 regression 段，跳过）。
    执行有硬超时（spec.timeout_seconds，对齐执行车道 D8 进程组中止），
    但失败/超时不改变退出码——三段自证语义不变（design: 回归可跑 1800s，
    不得把既有自证门拖成小时级）。
    """
    contract = load_verify_contract(project_root)
    if contract is None or contract.regression is None:
        return None, None
    spec = contract.regression

    import subprocess

    cmd = spec.cmd
    output_rel = str(spec.output)
    output_abs = Path(project_root) / output_rel
    # 清理旧产物，确保解析的是本次执行产出
    if output_abs.is_file():
        try:
            output_abs.unlink()
        except OSError:
            pass
    use_shell = isinstance(cmd, str)
    try:
        proc = subprocess.Popen(
            cmd,
            shell=use_shell,
            cwd=str(project_root),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as e:
        return False, f"回归命令启动失败: {e}"
    try:
        proc.wait(timeout=spec.timeout_seconds)
    except subprocess.TimeoutExpired:
        # 对齐执行车道：中止整个进程组
        import os
        import signal

        try:
            pgid = os.getpgid(proc.pid)
            os.killpg(pgid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(pgid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
        return False, f"回归命令超时（>{spec.timeout_seconds}s），未能确认产出 JUnit XML"
    if not output_abs.is_file():
        return False, f"回归命令退出码 {proc.returncode}，但 JUnit XML 产物不存在: {output_rel}"
    try:
        parsed = parse_junit_xml(output_abs)
    except Exception as e:
        return False, f"JUnit XML 不可解析: {e}"
    return (
        True,
        f"回归自证通过（{parsed['total']} 用例，产出 {output_rel}）",
    )


def main():
    # 解析参数：项目根目录（可选）
    if len(sys.argv) > 1:
        project_root = Path(sys.argv[1]).resolve()
    else:
        project_root = Path.cwd()

    # 检查项目根是否存在
    if not project_root.is_dir():
        print(f"错误: 项目根目录不存在: {project_root}", file=sys.stderr)
        sys.exit(1)

    # 检查契约文件是否存在
    contract_path = project_root / ".fenix" / "verify.yaml"
    if not contract_path.is_file():
        print(f"错误: 验证契约不存在: {contract_path}", file=sys.stderr)
        print("提示: 请先创建 .fenix/verify.yaml（参见 verify_contract.py 文档模板）")
        sys.exit(1)

    # 运行校验
    print(f"校验项目: {project_root}")
    print(f"契约文件: {contract_path}")
    print()

    result = validate_contract(project_root)

    # 输出 prepare 结果
    print(f"[prepare] {'✓ 通过' if result.prepare_ok else '✗ 失败'}", end="")
    if result.prepare_steps_run > 0:
        print(f"（{result.prepare_steps_run} 步）", end="")
    print()
    if result.prepare_error:
        print(f"  错误: {result.prepare_error}")

    # 输出 serve 结果
    print(f"[serve]   {'✓ 通过' if result.serve_ok else '✗ 失败'}", end="")
    if result.serve_kind:
        print(f"（kind={result.serve_kind}", end="")
        if result.serve_port:
            print(f", port={result.serve_port}", end="")
        print("）", end="")
    elif not result.serve_kind:
        print("（无 serve 段——纯 cli 场景集合法）", end="")
    print()
    if result.serve_error:
        print(f"  错误: {result.serve_error}")

    # 输出 ready 结果
    print(f"[ready]   {'✓ 通过' if result.ready_ok else '✗ 失败'}", end="")
    if result.ready_url:
        print(f"（url={result.ready_url}, expect={result.ready_expect}）", end="")
    elif not result.ready_url:
        print("（无 ready 探针——纯 cli 场景集合法）", end="")
    print()
    if result.ready_error:
        print(f"  错误: {result.ready_error}")

    # 可选 regression 段自证（独立一行，不计入退出码）
    reg_ok, reg_note = selfcheck_regression(project_root)
    if reg_ok is not None:
        print()
        print(f"[regression] {'✓ 通过' if reg_ok else '✗ 自证失败'}")
        if reg_note:
            print(f"  {reg_note}")
        if reg_ok is False:
            print(
                "  提示: regression 段可选——自证失败时 Administrator 应省略该段"
                "（不得臆造无效命令，否则周期回归将每天以 parse_error 空转）"
            )

    # 输出 valid 判定
    print()
    print(f"[valid]   {'✓ 有效' if result.valid else '✗ 无效'}")
    if not result.valid:
        print("  契约格式无效或存在错误，无法作为有效契约生效")

    # 输出摘要
    print()
    if result.valid and result.prepare_ok and result.serve_ok and result.ready_ok:
        print("校验通过（exit 0）: 三段契约全部通过，可作为有效验证契约生效")
        sys.exit(0)
    else:
        # 确定退出码（按优先级：契约无效 > prepare > serve > ready）
        if not result.valid:
            if "不存在" in result.prepare_error:
                exit_code = 1  # 契约文件不存在
            elif "解析失败" in result.prepare_error:
                exit_code = 1  # 契约 YAML 解析失败
            elif "非法" in result.serve_error:
                exit_code = 5  # 契约格式无效（serve 段非法）
            elif "为空" in result.serve_error:
                exit_code = 5  # 契约格式无效（必填字段为空）
            else:
                exit_code = 1  # 其他无效原因
        elif not result.prepare_ok:
            exit_code = 2  # prepare 失败
        elif not result.serve_ok:
            exit_code = 3  # serve 失败
        elif not result.ready_ok:
            exit_code = 4  # ready 失败
        else:
            exit_code = 1

        print(f"校验失败（exit {exit_code}）: 契约存在错误，无法作为有效验证契约生效")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
