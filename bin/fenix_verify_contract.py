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
    1 — 契约文件不存在或解析失败（亦是其他契约无效原因的兜底码：
        fail_kind 缺失/None 等未归类的无效同样退出 1，见 main() 退出码判定）
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

import argparse
import sys
import uuid
from pathlib import Path

# 确保项目根在 sys.path 中（运行脚本时可能不在工作目录）
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from core.verify_contract import (
    FAIL_CONTRACT_MISSING,
    FAIL_CONTRACT_PARSE,
    FAIL_SERVE_INVALID,
    load_verify_contract,
    validate_contract,
)
from core.regression import parse_junit_xml


def selfcheck_regression(project_root: Path, contract=None) -> tuple:
    """可选 regression 段自证：按 cmd 跑一次确认 output 产出可解析 JUnit XML。

    contract 可传入已加载的契约对象（code-review item 708cdd624733 /
    73047bb4e140）：CLI main() 传入 validate_contract 随 ValidateResult 返回的
    同一契约对象，三段判定与本次自证使用同一版本 verify.yaml，消除两次读取
    之间文件被改写的 TOCTOU 窗口；缺省 None 时内部自行加载，保持既有调用
    形态兼容。

    返回 (ok, note)：ok 为 True/False/None（None=无 regression 段，跳过）。
    执行有硬超时（spec.timeout_seconds，对齐执行车道 D8 进程组中止），
    但失败/超时不改变退出码——三段自证语义不变（design: 回归可跑 1800s，
    不得把既有自证门拖成小时级）。
    """
    if contract is None:
        contract = load_verify_contract(project_root)
    if contract is None or contract.regression is None:
        return None, None
    spec = contract.regression

    import subprocess

    cmd = spec.cmd
    output_rel = str(spec.output)
    # output 原样读自 verify.yaml：绝对路径或 .. 穿越会把 unlink/解析
    # 指向项目外文件，触达前先约束解析路径在项目根内
    root = Path(project_root).resolve()
    output_abs = (root / output_rel).resolve()
    try:
        output_abs.relative_to(root)
    except ValueError:
        return False, f"regression.output 越界项目根，拒绝触达: {output_rel}"
    # 白名单化约束（code-review item d503c2228418）：output 是 verify.yaml 里
    # 人工填写的自由路径，contained-in-root 只防外溢不防内伤——误填 src/ 源码
    # 或 .fenix/ 配置键文件时，下面的清理会先真实删除该文件且回归命令不会重写
    # 它，配置笔误升级为项目内文件丢失。unlink 前收紧为 JUnit XML 产物形态，
    # 并显式拒绝契约文件本身与 .fenix/ 下的配置键文件。
    if not output_rel.endswith(".xml"):
        return False, (
            f"regression.output 须为 .xml 产物路径，拒绝清理非 XML 文件: {output_rel}"
        )
    protected = {
        (root / ".fenix" / "verify.yaml").resolve(),
        (root / ".fenix" / "config.yaml").resolve(),
    }
    if output_abs in protected:
        return False, (
            f"regression.output 不得指向契约/配置键文件（verify.yaml/config.yaml），"
            f"拒绝清理: {output_rel}"
        )
    # 清理旧产物——不直接 unlink（code-review item b44a846dc7b4）：.xml 后缀 +
    # 保护集挡不住误填项目内其他合法 XML 文档/测试夹具，先 unlink 而回归命令
    # 不会重写它时，配置笔误升级为不可逆丢失。改为先在原目录改名暂存（同 fs
    # 原子、不新建目录），自证成功后才删暂存；失败路径保留暂存文件，误删可
    # 从暂存名手动找回。
    stale_stage = None
    if output_abs.is_file():
        stale_stage = output_abs.with_name(
            f"{output_abs.name}.stale-{uuid.uuid4().hex[:8]}"
        )
        try:
            output_abs.rename(stale_stage)
        except OSError as e:
            # 移开失败与旧 unlink 失败同语义（code-review item e0100af58b0f）：
            # 陈旧 XML 留在 output 路径且后续回归命令失败未重写文件时，会被
            # 解析并报成功（假通过）。显式失败退出自证，交人工处置。
            return False, (
                f"陈旧 JUnit XML 暂存失败（{e}），无法确保解析的是本次执行"
                f"产出，拒绝自证: {output_rel}"
            )

    def _stale_stage_hint() -> str:
        """失败路径的暂存附记（code-review item a73f9bdeeaf8）：暂存旧产物仅
        在自证成功路径删除，启动失败/超时/XML 不可解析等失败路径同样会遗留
        暂存文件——统一附上暂存名，避免误删找回线索缺失。"""
        if stale_stage is None:
            return ""
        return f"（旧产物已暂存为 {stale_stage.name}，如系误指非产物路径可手动找回）"

    use_shell = isinstance(cmd, str)
    try:
        proc = subprocess.Popen(
            cmd,
            shell=use_shell,
            cwd=str(project_root),
            # stderr 与 stdout 同走 DEVNULL（code-review item 5ca4b05ef37a，
            # critical）：本函数只关心退出码与 JUnit XML 产物、从不读
            # proc.stderr——PIPE 从不排空，verbose 回归命令（pytest/node 输出）
            # 写满约 64KB 管道缓冲后 write() 永久阻塞，子进程挂死、
            # wait(timeout) 必然超时，run 被误报「回归命令超时」。
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except (OSError, TypeError, ValueError) as e:
        # 不只 OSError：load_verify_contract 原样存 regression.cmd（仅 truthiness
        # 检查，非字符串/含非字符串项的列表会漏到这里），Popen 对畸形 cmd 抛
        # TypeError/ValueError——须与 OSError 同转 (False, "回归命令启动失败: …")
        # 而非裸 traceback（code-review item 92ffb7d32798）。
        return False, f"回归命令启动失败: {e}" + _stale_stage_hint()
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
                # SIGKILL 后也须回收（code-review item c50faac102e7）：
                # 否则子进程在 CLI 退出前保持 zombie，收尾与 SIGTERM
                # 分支不对称
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        except (OSError, ProcessLookupError):
            pass
        return False, (
            f"回归命令超时（>{spec.timeout_seconds}s），未能确认产出 JUnit XML"
            + _stale_stage_hint()
        )
    if not output_abs.is_file():
        return False, (
            f"回归命令退出码 {proc.returncode}，但 JUnit XML 产物不存在: "
            f"{output_rel}{_stale_stage_hint()}"
        )
    try:
        parsed = parse_junit_xml(output_abs)
    except Exception as e:
        return False, f"JUnit XML 不可解析: {e}" + _stale_stage_hint()
    note = f"回归自证通过（{parsed['total']} 用例，产出 {output_rel}）"
    if stale_stage is not None:
        try:
            stale_stage.unlink()
        except OSError as e:
            # 暂存清理失败不影响自证结论（新产物已在 output 路径并通过解析），
            # 但残留不得静默——附记暂存名交人工处置。
            note += f"（注意: 陈旧产物暂存清理失败（{e}），残留于 {stale_stage.name}）"
    return True, note


def main():
    # 解析参数：项目根目录（可选）。改用 argparse（code-review item 06ca1a94ce95），
    # 口径对齐 bin/fenix_detect_artifacts.py：-h/--help 由 argparse 自动打印用法
    # 后 exit 0，不再把旗标误当项目路径走「目录不存在」报错路径。
    parser = argparse.ArgumentParser(
        description="验证契约校验 CLI（Administrator 自证入口）"
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=".",
        help="项目根目录（默认：当前目录）",
    )
    args = parser.parse_args()
    # expanduser（code-review item 4c3d33c2b64a）：引号包裹传入的 ~ 开头路径
    # 按字面落盘会误报「项目根目录不存在」，口径对齐 bin/fenix_detect_artifacts.py
    try:
        # 路径解析收口进 try（与 fenix_detect_artifacts.py/fenix_archive.py/
        # fenix_spec.py 同场景防护对齐）：expanduser 解析不出家目录抛
        # RuntimeError、含空字节路径在构造/resolve 阶段抛 ValueError，裸抛会
        # 绕过下方「项目根目录不存在」分支的 stderr 错误输出与 sys.exit(1)，
        # 进程以 traceback 收场、退出码不符 docstring 契约
        project_root = Path(args.project_root).expanduser().resolve()
    except (ValueError, OSError, RuntimeError) as e:
        print(f"错误: 项目根目录无法解析: {e}", file=sys.stderr)
        sys.exit(1)

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

    # 输出 prepare 结果。prepare 未实际执行时（serve 段结构非法被跳过等路径下
    # prepare_ok 只是初始 True）显示「未执行」而非「通过」，不谎报未执行的段
    # 已通过（code-review item f295bff223a0；退出码判定不受影响，仍按
    # prepare_ok，与 serve_ran/ready_ran 同口径）。
    if result.prepare_ran:
        print(f"[prepare] {'✓ 通过' if result.prepare_ok else '✗ 失败'}", end="")
    else:
        print("[prepare] 未执行", end="")
    # 声明步数（非实际执行步数——prepare_steps_run 在执行前赋值，第 1 步即
    # 失败时仍为全部声明步数；code-review item 69f20b76f5a2），避免误读。
    if result.prepare_steps_run > 0:
        print(f"（声明 {result.prepare_steps_run} 步）", end="")
    print()
    if result.prepare_error:
        print(f"  错误: {result.prepare_error}")

    # 输出 serve 结果。serve 未实际启动时（prepare 失败等路径下 serve_ok 只是
    # 初始 True）显示「未启动」而非「通过」，不谎报未执行的段已通过
    # （code-review item 3d9623096956；退出码判定不受影响，仍按 serve_ok）。
    if result.serve_ran:
        print(f"[serve]   {'✓ 通过' if result.serve_ok else '✗ 失败'}", end="")
    else:
        print("[serve]   未启动", end="")
    if result.serve_kind:
        print(f"（kind={result.serve_kind}", end="")
        if result.serve_port:
            print(f", port={result.serve_port}", end="")
        print("）", end="")
    else:
        print("（无 serve 段——纯 cli 场景集合法）", end="")
    print()
    if result.serve_error:
        print(f"  错误: {result.serve_error}")

    # 输出 ready 结果。探针未实际执行时（prepare 失败/serve 失败等路径下
    # ready_ok 只是初始 True）显示「未探测」而非「通过」，不谎报探针结果
    # （code-review item 944ef0f39f71；退出码判定不受影响，仍按 ready_ok）。
    if result.ready_ran:
        print(f"[ready]   {'✓ 通过' if result.ready_ok else '✗ 失败'}", end="")
    else:
        print("[ready]   未探测", end="")
    if result.ready_url:
        print(f"（url={result.ready_url}, expect={result.ready_expect}）", end="")
    else:
        print("（无 ready 探针——纯 cli 场景集合法）", end="")
    print()
    if result.ready_error:
        print(f"  错误: {result.ready_error}")

    # 可选 regression 段自证（独立一行，不计入退出码）。
    # 契约已失败（valid=False 或 prepare/serve/ready 任一失败）时跳过：带
    # regression 段时自证最长可跑满 timeout_seconds（缺省 1800s），在注定失败
    # 的契约上只会拖延失败反馈——长耗时自证留给全通过场景（code-review
    # item 2d16961e4ada）。退出码判定不受影响，仍按既有失败路径退出。
    contract_failed = (
        not result.valid
        or not result.prepare_ok
        or not result.serve_ok
        or not result.ready_ok
    )
    # 契约只加载一次（code-review item 708cdd624733 / 73047bb4e140）：三段校验、
    # 跳过自证分支的判定与 regression 自证全程复用 validate_contract 随
    # ValidateResult 返回的同一份契约对象——verify.yaml 整个生命周期只由
    # validate_contract 内部加载一次，消除两次读取之间文件被改写导致「校验
    # 结论与自证所用契约不是同一版本」的 TOCTOU 窗口。
    contract = result.contract
    if contract_failed:
        if contract is not None and contract.regression is not None:
            print()
            print("[regression] 跳过自证（因契约已失败跳过回归自证）")
    else:
        reg_ok, reg_note = selfcheck_regression(project_root, contract=contract)
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
    # 复用上方 contract_failed（code-review item 5c645f296fcc）：成功判定即其
    # 取反，避免同一组四元条件两处重写、日后增删判定段时只改一处致分支不一致
    if not contract_failed:
        print("校验通过（exit 0）: 三段契约全部通过，可作为有效验证契约生效")
        sys.exit(0)
    else:
        # 确定退出码（按优先级：契约无效 > prepare > serve > ready）。
        # valid=False 的细分映射走结构化 fail_kind 枚举（code-review item
        # fdb60ffde7a8），不依赖错误文案的中文子串匹配——文案漂移不再使退
        # 出码静默降级；枚举缺失/None 一律短路兜底 exit 1，不再对错误字段
        # 做子串 in 判断（顺带杜绝 in None TypeError）。
        if not result.valid:
            fail_kind = getattr(result, "fail_kind", None)
            if fail_kind == FAIL_SERVE_INVALID:
                exit_code = 5  # 契约格式无效（serve 段非法）
            elif fail_kind in (FAIL_CONTRACT_MISSING, FAIL_CONTRACT_PARSE):
                exit_code = 1  # 契约文件不存在 / 契约 YAML 解析失败
            else:
                exit_code = 1  # 其他无效原因（含 fail_kind 缺失/None 的兜底）
        elif not result.prepare_ok:
            exit_code = 2  # prepare 失败
        elif not result.serve_ok:
            exit_code = 3  # serve 失败
        elif not result.ready_ok:
            exit_code = 4  # ready 失败
        else:
            # 不可达（code-review item d43d9fd814db）：进入外层 else 意味着
            # valid/prepare_ok/serve_ok/ready_ok 至少一个为 False，前置分支已
            # 覆盖全部剩余组合（四者皆 True 时函数已在上方 exit 0）。不存在
            # 第五种失败模式——真到达此处属判定逻辑被改坏的编程错误，fail-fast
            # 而非伪装成退出码 1 的「契约无效」。
            raise RuntimeError(
                "fenix_verify_contract: 校验失败分支不可达（valid/prepare/serve/ready"
                " 全通过却未走 exit 0）——判定逻辑存在缺陷"
            )

        print(f"校验失败（exit {exit_code}）: 契约存在错误，无法作为有效验证契约生效")
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
