"""core.pm_engine.verification.scenario_gate — 场景冻结/交互契约/静态检查（refactor-verification-module D2）。

从 VerificationPipeline 摘出的场景冻结（_apply_scenario_freeze）、交互契约
（_apply_interaction_contract）、冻结场景读取、场景变更报告段渲染、契约缺失
标记、场景静态检查与契约静态检查。纯结构搬移，零行为变化。

本模块 MUST NOT `import _legacy`（D2b 规则 1：门面依赖以显式 `pipeline` 参数注入）。

实例缓存态 `_last_scenario_diff` / `_last_interaction_contract` /
`_last_freeze_rejected*` 写入 pipeline 实例属性（engine.py 经
`self._verification._last_scenario_diff` 读取，路径不变）。
"""

import json
from pathlib import Path

# 原子写收口共享助手 core.fs_utils.atomic_write_text（code-review item
# abfbfb073153）：本模块原自持一份无 chmod 的 mkstemp+fsync+replace 实现，
# 落盘产物恒为 mkstemp 缺省 0600、os.replace 整体替换静默收紧既有 0644
# 文件，与收口单点的权限口径持续漂移。收口为薄委托（对齐
# deliverables._atomic_write_text 先例 e42aabcf003a），mkstemp 唯一临时名
# + fsync + 权限修复 + 尽力而为目录 fsync 纪律单点维护于 fs_utils。
# 别名 import：模块尾部 ``atomic_write_text = _atomic_write_text`` 公开
# 别名会遮蔽同名 import，直名 import 将令薄委托自递归。
from core.fs_utils import atomic_write_text as _fs_atomic_write_text


def _atomic_write_text(
    path: Path, content: str, inherit_existing_mode: bool = False
) -> None:
    """mkstemp 唯一临时文件 + fsync + os.replace 原子写（薄委托 fs_utils 收口版）。

    本文件四处写点共用助手（写点收敛 code-review 83f6bb98613c；实现收敛
    63f474ae0e08）。唯一临时名保证并发写不产生截断产物；任何写失败都在
    清理残留临时文件后原样上抛，由调用点按各自语义留痕（各写点日志级别/
    文案不同，收敛后调整原子写实现只改这一处）。

    权限口径（item abfbfb073153）：缺省 False 无条件 chmod 0644——mkstemp
    缺省 0600 经 os.replace 整体替换会静默收紧既有 0644 文件，而 JSON
    场景产物须对非 root 辅助进程/人工其它账号可读；True 继承既有文件
    权限（新文件放宽 0644），用于运维可能刻意收紧权限的既有产物
    （verification-report.md 场景变更小节写点）。

    持久性边界：随收口升级为 fs_utils 版纪律——SIGKILL/进程崩溃场景
    rename 前内容必已完整落盘，rename 后尽力而为 fsync 父目录（失败不
    阻断写入）。各写点均为可重生成/可重写产物，不追断电级 durability
    （item a18b40f1af36 的取舍不变，纪律细节由 fs_utils 单点承载）。
    """
    _fs_atomic_write_text(path, content, inherit_existing_mode=inherit_existing_mode)


# 公开别名（跨模块消费走公开名，不 import 私有符号；同 commit_verification_report
# 先例，code-review item 157daf7507c0）
atomic_write_text = _atomic_write_text


def _apply_scenario_freeze(pipeline, spec_name: str) -> dict:
    """应用场景集冻结：planner 产出 vs 持久化集 diff，写回 scenarios.json。

    design D3：确定性、纯 Python，planner 无法通过输出文本绕过。
    在场景执行前调用（_run_three_stage_verification 阶段1 之后）。

    写端 schema 门（fix-frozen-scenario-orphan-reservoir D1/D2/D3）：
    - 收编写回 / 补齐写回 test_scenarios.json 前过 ``validate_scenario_dicts``
      同源校验（与读端 load_scenarios 同源），坏条目剔除留痕（id 清单）、
      不整批拒绝；剔除数超本轮 20% 时 ERROR 升级（Task 2.4）。
    - ``_scenarios_full.json`` 备份仅当 planner 产出全部合法时更新
      （备份价值在「可恢复」，存毒即失去价值）；含非法条目时保留旧备份
      + WARNING 留痕。
    - 无理由缺场景且备份缺定义 → 改弃场景（D3）：登记「定义不可恢复」
      剔除清单，不再写 ``{"id","description"}`` 非法占位，验证以剩余
      场景继续；备份有完整定义时维持既有补回行为（Task 3.2）。

    写前客户端预校验（evo-planner-scenario-schema-alignment 3.1-3.10）：
    - planner 产出进入阶段2 前逐条过与写端一致的校验器
      （``validate_scenario_dicts``，与读端同源且含旧 schema 迁移），
      非法条目剔除留痕（场景 id + 缺失字段），合法部分照常进入执行，
      MUST NOT 等整批落盘后整批剔除（09-13 两批 100% 剔除 → 阶段2
      整轮失败退回的既有路径）。
    - 3.3 移除声明豁免：携带 ``remove_reason`` 的声明条目不过滤
      （纯移除声明过不了 validate_scenario_dicts——缺 navigate 步骤等），
      令 diff 仍看到移除声明、仅对「实际写入集」过滤——否则理由丢失、
      planner 显式移除被静默反转为保留。
    - 3.2 主路径写回（MUST）：过滤得合法集后，于主路径把合法子集整体
      重写回 test_scenarios.json（事故实证条件——第 1 轮 / persisted 为空 /
      无理由缺失 0——永不进补齐分支，若只把写回挂补齐分支，非法条目仍留
      在文件、阶段2 仍旧整轮失败）；与补齐分支写回互斥（补齐分支已写即
      不再写），两处写回内容均为过滤后集合。
    - 3.5/3.8 空集显式兜底：过滤后无合法场景 → 不写空 test_scenarios.json、
      不 save_scenario_set（防止持久化集被写成空集——load_scenario_set 对
      ``scenarios: []`` 返回非 None、下一轮 diff 从首轮全量口径退化增量
      口径），以结构化返回值 ``{'aborted': 'no_valid_scenarios', ...}``
      承载信号，由调用点消费（阶段1 主路径退回 plan / 重排预算耗尽显式
      结束；judge 重入路径拒绝重入）——MUST NOT 依赖加载报错通道
      （写回合法子集后该报错不再触发，0 场景报告会被洗白门 fail-open
      放行判 verified）。
    - 3.9 剔除比例口径：超本轮 20% 的 ERROR 升级以写回前最终合法集为
      基准统计（两遍剔除——过滤 pass 与补齐 pass——合并）。
    - 3.10 剔除留痕：剔除条目 id 与 covers 存实例属性，紧随其后的
      ``_apply_interaction_contract`` 据此把「条目非法剔除」与「设计漏项」
      缺口区分开，避免「重排-剔除」循环。

    Returns:
        dict：{'diff': <DiffResult>, 'path': <写入路径>}，便于报告渲染复用；
        空集显式兜底时返回 {'aborted': 'no_valid_scenarios', 'rejected':
        [<逐条剔除描述>], 'total': <原始总数>, 'path': <场景文件路径>}。
    """
    from core.verify_scenarios import (
        load_scenario_set,
        diff_planner_output,
        save_scenario_set,
    )
    from core.verify_engine.scenarios import (
        validate_scenario_dicts,
        prepare_scenarios_for_write,
    )
    # code-review ef247f2792d2：verify-progress 目录解析收敛到
    # verify_progress_dir 净化单源（延迟导入防环，与 judge_gate 先例同款），
    # 病理 spec_name 时与冻结复用读点/裁决读点恒同源、不落到未净化目录。
    from core.pm_engine.verification.report_gate import verify_progress_dir

    # code-review 3dd5194ce79b：pipeline 实例被 engine 跨 spec 串行复用，本函数
    # 是三个实例缓存（_last_freeze_rejected / _last_freeze_rejected_covers /
    # _last_scenario_diff）的唯一写点。冻结轮开始时先清空并按 spec 登记归属，
    # 早退路径（文件缺失/解析失败/整批非法）不遗留上一 spec 或上一轮的陈旧值；
    # 冻结复用轮（不经本函数重算冻结）据归属戳校验，不消费异 spec 缓存。
    pipeline._last_freeze_owner = spec_name
    pipeline._last_freeze_rejected = []
    pipeline._last_freeze_rejected_covers = set()
    pipeline._last_scenario_diff = None
    # code-review f0309026fbc9：_last_interaction_contract 同属跨 spec 串行复用的
    # 实例缓存，冻结轮开始时一并清空——本函数早退或后续契约校验异常跳过时，
    # 不遗留上一 spec/上一轮的 ContractResult（赋值点在
    # _apply_interaction_contract，其入口另有同款清空）。
    pipeline._last_interaction_contract = None

    verify_dir = verify_progress_dir(pipeline, spec_name)
    scenarios_path = verify_dir / "test_scenarios.json"
    if not scenarios_path.exists():
        # planner 未产出场景文件属正常状态，debug 留痕即可（code-review
        # 4999e4231bba：早退路径不得零痕迹，排障可区分「无需冻结」与「坏数据」）
        pipeline._context.logger.debug(
            "pm_engine",
            f"场景冻结跳过 '{spec_name}'（场景文件不存在，planner 尚未产出）:"
            f" {scenarios_path}",
        )
        return {}
    try:
        planner_scenarios = json.loads(scenarios_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        # 解析失败属数据损坏信号（code-review 26c1f77eb84a）：冻结层留 WARNING
        # 现场，衔接阶段2 _load_frozen_or_escalate 的 corrupt 报错归因链
        # （3.6 留痕口径：失败不得零痕迹）。
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景冻结跳过 '{spec_name}'（test_scenarios.json 解析失败，"
            f"阶段2 加载将另行报错）: {type(e).__name__}: {e}",
        )
        return {}
    if not isinstance(planner_scenarios, list):
        pipeline._context.logger.warning(
            "pm_engine",
            f"场景冻结跳过 '{spec_name}'（test_scenarios.json 顶层非列表，"
            f"实际为 {type(planner_scenarios).__name__}，阶段2 加载将另行报错）",
        )
        return {}

    entry = pipeline._context.state_machine.read_one(spec_name) or {}
    current_round = pipeline._current_verify_round(spec_name)

    # ── 写前客户端预校验（3.1/3.3）：逐条过与写端一致的校验器 ──
    # 过滤出「实际写入集」（valid_planner）与「diff 输入集」（diff_input ＝
    # 合法集 + 携带 remove_reason 的移除声明，3.3 移除声明豁免）。
    valid_planner: list = []
    rejected: list[str] = []
    rejected_ids: list[str] = []
    diff_input: list = []
    for idx, item in enumerate(planner_scenarios):
        if not isinstance(item, dict):
            rejected.append(f"[{idx}]非对象({type(item).__name__})")
            continue
        item_id = item.get("id") or f"[{idx}]"
        if isinstance(item.get("remove_reason"), str) and item["remove_reason"]:
            # 3.3：纯移除声明条目保留进 diff 输入（移除理由照常生效），
            # 不参与写回（其形态本就不是可执行场景）。
            diff_input.append(item)
            continue
        errs = validate_scenario_dicts([item])
        if errs:
            rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
            rejected_ids.append(str(item_id))
            continue
        valid_planner.append(item)
        diff_input.append(item)

    # 3.10：剔除条目 id 与 covers 留痕（交互契约消费——被剔除场景覆盖的
    # 候选不属「设计漏项」缺口，避免「重排-剔除」循环）。
    pipeline._last_freeze_rejected = list(rejected_ids)
    rejected_covers: set = set()
    rejected_set = set(rejected_ids)
    for idx, item in enumerate(planner_scenarios):
        if not isinstance(item, dict):
            continue
        # 反查侧与登记侧（item.get("id") or f"[{idx}]" 后
        # rejected_ids.append(str(item_id))）共用同一 id 规整：原始 id 为
        # 非字符串（如 int）时裸值 in 集合恒不命中，3.10「条目非法剔除」
        # 去噪失效（code-review 99e826fde331）；id 为空/缺失时登记侧落
        # "[idx]" 而裸反查算出 ""/"None"，同样永不命中（code-review
        # 7a961175fded），故同样走 or f"[{idx}]" 兜底。
        if str(item.get("id") or f"[{idx}]") in rejected_set:
            covers = item.get("covers")
            if isinstance(covers, list):
                rejected_covers.update(str(c) for c in covers if c)
    pipeline._last_freeze_rejected_covers = rejected_covers

    # ── 空集显式兜底（3.5/3.8）：全部条目非法 → 不写空文件、不持久化 ──
    # 写回合法子集后「全部非法」不再触发阶段2 load_scenarios 报错（既有
    # 退回路径依赖的正是该报错），必须在此显式判定；0 场景经 engine.run([])
    # 产出无 env_error 的全绿报告、会被洗白门 fail-open 放行判 verified，
    # 故空集 MUST NOT 以 0 场景继续进入阶段2。空集判定先于 save_scenario_set
    # （3.8）：持久化集保持不变，下一轮 diff 维持首轮全量口径。
    if not valid_planner:
        all_removals = 0
        if rejected:
            reject_note = "、".join(rejected)
            pipeline._context.logger.error(
                "pm_engine",
                f"场景写前预校验整批拒绝 '{spec_name}'（{len(rejected)}/"
                f"{len(planner_scenarios)} 条全部非法），无合法场景可执行 "
                f"— 不写空文件/不持久化，退回 plan 重排: {reject_note}",
            )
        else:
            # code-review item fcc8527b798a：rejected 为空的空集=全部条目均为
            # 3.3 移除声明（或输入本就为空列表）——移除声明走 diff_input 豁免、
            # 既不进 rejected 也不进 valid_planner，原先此处零留痕 abort，排障
            # 无法区分「整批校验拒绝」与「全量移除声明」。ERROR 留痕 + 返回值
            # 附 all_removals 结构化说明（消费方只读 aborted 键，新增键向后
            # 兼容）。
            all_removals = sum(
                1
                for it in planner_scenarios
                if isinstance(it, dict)
                and isinstance(it.get("remove_reason"), str)
                and it["remove_reason"]
            )
            pipeline._context.logger.error(
                "pm_engine",
                f"场景写前预校验空集 '{spec_name}'（输入 {len(planner_scenarios)} "
                f"条、其中移除声明 {all_removals} 条，无可执行场景）— "
                f"不写空文件/不持久化，退回 plan 重排",
            )
        return {
            "aborted": "no_valid_scenarios",
            "rejected": rejected,
            # fcc8527b798a：仅 rejected 空的空集附移除声明构成说明。
            **({"all_removals": all_removals} if not rejected else {}),
            "total": len(planner_scenarios),
            "path": str(scenarios_path),
        }

    # ── 剔除留痕（第一遍，3.4 既有语义：超本轮 20% ERROR 升级）──
    # code-review item 5ea8a25aeeae：本段比例基准为 planner 原始条目数
    # （len(planner_scenarios)），与下方 3.9 合并统计（以写回前最终合法集
    # len(final_valid) 为基准、两遍剔除合并）口径不同且有意并存——同轮两段
    # 日志可能一段判超、一段判未超，排障勿据本段单边下结论。
    if rejected:
        reject_note = "、".join(rejected)
        total = len(planner_scenarios) or 1
        ratio = len(rejected) / total
        log_fn = pipeline._context.logger.error if ratio > 0.2 else pipeline._context.logger.warning
        log_fn(
            "pm_engine",
            f"场景写前预校验剔除 {len(rejected)}/{len(planner_scenarios)} "
            f"条非法条目（基准=planner 原始条目数，"
            f"{'超本轮20%' if ratio > 0.2 else '未超20%'}；与 3.9 合并口径"
            f"「写回前最终合法集」基准不同，两套口径有意并存），"
            f"合法部分照常执行: {reject_note}",
        )

    diff = diff_planner_output(
        pipeline._context.project_root, spec_name, entry, diff_input, current_round
    )
    if rejected:
        reject_note = "、".join(rejected)
        diff.change_lines.append(
            f"- 写前预校验剔除 {len(rejected)} 条非法条目（未落盘）：{reject_note}"
        )

    # 写回 scenarios.json（原子写；首轮写入 / 合并追加 / 补齐后稳定集）
    # code-review a06e1d42116f：3.6 口径对齐——本写点原为裸调，OSError 上抛后
    # 只被调用方外层 except 以 WARNING 收场，冻结持久化失败无 ERROR 归因，
    # 还会连坐跳过下方 test_scenarios.json 合法子集写回。比照同函数各写点：
    # ERROR 留痕后继续本轮（持久化集未更新，下轮 diff 退化首轮全量口径）。
    # persisted_updated（code-review item 416f69c853dc）：登记持久化集是否
    # 真已写入，供下方补齐分支空集 abort 的分叉留痕区分「已写入」与
    # 「写失败未动」两种事实（留痕措辞必须与实际落盘状态一致）。
    persisted_updated = False
    try:
        path = save_scenario_set(pipeline._context.project_root, diff.scenario_set)
        persisted_updated = True
    except OSError as e:
        pipeline._context.logger.error(
            "pm_engine",
            f"持久化场景集写回失败 '{spec_name}'（scenarios.json 未更新，"
            f"下轮 diff 退化为首轮全量口径）: {e}",
        )
        path = scenarios_path  # 写失败占位：供返回值 path 字段（当前无消费方）
    # 全量场景定义备份（_scenarios_full.json）：供无理由缺场景时按持久化集
    # 补齐 test_scenarios.json 的原始定义（design D2：不丢回归面）。
    # 仅当本轮未删减既有场景时更新备份（保留最全的历史定义）。
    # D2 特例：备份仅当 planner 产出全部合法时更新——存毒即失去可恢复价值，
    # 含非法条目时保留旧备份并 WARNING 留痕。
    # D3 交互：当存在无理由缺场景（unreasoned_missing）时，旧备份是补回
    # 所需的历史定义源——此时 MUST NOT 覆盖（否则 reconcile 无法取回定义，
    # 缺定义场景被误判为不可恢复）。仅当 diff.ok（无无理由缺失）时更新。
    if not diff.removed and not diff.unreasoned_missing:
        if rejected:
            pipeline._context.logger.warning(
                "pm_engine",
                f"场景备份未更新 '{spec_name}'：planner 产出含 "
                f"{len(rejected)} 条非法条目（_scenarios_full.json 存毒即"
                f"失去可恢复价值，保留旧备份）",
            )
        else:
            full_backup = verify_dir / "_scenarios_full.json"
            try:
                # frozen-scenario-schema-migration 2.1：写端恒定写入
                # schema_version 标记（旧字段先迁移再落盘，读侧直通）
                # tmp+replace 原子写（共用 _atomic_write_text 助手）：裸写
                # 中途被 SIGKILL/断电会留下截断备份，下轮无理由缺场景补齐
                # 读备份失败（backup_map 置空），场景被判「定义不可恢复」剔除。
                _atomic_write_text(
                    full_backup,
                    json.dumps(
                        prepare_scenarios_for_write(valid_planner),
                        ensure_ascii=False,
                        indent=2,
                    ),
                )
            except OSError as e:
                # 3.6：写失败不得零痕迹——备份是后续无理由缺场景补齐的唯一
                # 恢复源，写失败后下轮补齐将因 backup_map 为空把场景判
                # 「定义不可恢复」剔除（静默缩小回归面），ERROR 留痕可归因。
                pipeline._context.logger.error(
                    "pm_engine",
                    f"全量场景备份写回失败 '{spec_name}'（_scenarios_full.json "
                    f"未更新，缺场景补齐将失去恢复源）: {e}",
                )
    pipeline._context.logger.info(
        "pm_engine",
        f"场景集冻结 '{spec_name}'（第 {current_round} 轮）：稳定集 "
        f"{len(diff.scenario_set.scenarios)} 个，新增 {len(diff.added)}，"
        f"有理由移除 {len(diff.removed)}，无理由缺失 {len(diff.unreasoned_missing)}",
    )

    # ── 写回 test_scenarios.json 的合法子集（3.2/3.6/3.9）──
    # 两处写点互斥 3.2：补齐分支（无理由缺场景时以持久化集补齐后写回）与
    # 主路径写回；两处内容均为过滤后集合。第二遍剔除（write_rejected，补齐
    # pass 对备份取回条目再剔一批 + id 缺失/为空防御剔除）与第一遍合并统计
    # 3.9；covers 累积供 3.10 去噪登记。
    write_rejected: list[str] = []
    write_rejected_covers: set = set()
    final_valid: list = []
    if not diff.ok and diff.unreasoned_missing:
        # 无理由缺场景 → 以持久化集补齐 test_scenarios.json（不中断验证，
        # design D2）：planner 实际执行的场景文件必须含全部既有场景，否则
        # 回归面丢失。优先从上一轮全量备份 _scenarios_full.json 取回被丢弃
        # 场景的原始定义。
        missing_ids = {e.id for e in diff.unreasoned_missing}
        # code-review item d41d5e55b933：id 缺失/为空的条目原先被静默丢弃
        # （前置 validate_scenario_dicts 下合法条目恒有 id、该分支不可达；
        # 若校验器放松 id 要求则成静默缩小验证集的暗道），补 WARNING 留痕。
        idless = [
            (i, s)
            for i, s in enumerate(valid_planner)
            if isinstance(s, dict) and not s.get("id")
        ]
        if idless:
            pipeline._context.logger.warning(
                "pm_engine",
                f"场景补齐分支剔除 id 缺失/为空条目 {len(idless)} 条 "
                f"'{spec_name}'（不进补齐写回，缩小本轮验证集；前置校验下"
                f"不应出现）",
            )
            # code-review b5b04c5c291d：并入两遍剔除台账——write_rejected
            # 计数进 3.9 合并比例统计（经下方「补齐写回剔除」WARNING/
            # change_lines 留痕），covers 进 write_rejected_covers 供 3.10
            # 去噪；否则该防御剔除游离于台账外，条目携带 covers 时其候选
            # 会被交互契约误判「设计漏项」退回 replan。条目无 id 可登记，
            # 仅 covers 入集合（[i] 定位为 valid_planner 下标）。
            for i, s in idless:
                write_rejected.append(f"[{i}]id 缺失/为空")
                covers = s.get("covers")
                if isinstance(covers, list):
                    write_rejected_covers.update(str(c) for c in covers if c)
        reconciled = [
            s
            for s in valid_planner
            if isinstance(s, dict) and s.get("id") and s.get("id") not in missing_ids
        ]
        backup = verify_dir / "_scenarios_full.json"
        backup_map = {}
        if backup.exists():
            try:
                backup_data = json.loads(backup.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                backup_map = {}
            else:
                # code-review e2441291ebbb：备份可能被外部损坏成「合法 JSON 但
                # 根为非可迭代标量」（null/数字等），直接 for 迭代会抛 TypeError
                # 炸穿整个 _apply_scenario_freeze——连坐跳过 3.2 合法子集写回，
                # planner 原始文件（可能含非法条目）将原样进入阶段2。与上方
                # test_scenarios.json 顶层非列表同口径：WARNING 留痕后置空，
                # 缺失场景走「定义不可恢复」剔除。
                if not isinstance(backup_data, list):
                    pipeline._context.logger.warning(
                        "pm_engine",
                        f"场景备份不可用 '{spec_name}'（_scenarios_full.json 顶层"
                        f"非列表，实际为 {type(backup_data).__name__}，缺场景补齐"
                        f"将按「定义不可恢复」剔除）",
                    )
                    backup_map = {}
                else:
                    for s in backup_data:
                        if isinstance(s, dict) and s.get("id"):
                            backup_map[s["id"]] = s
        # D3：备份缺定义 → 改弃场景（不再写 {"id","description"} 占位）。
        # 备份取回的条目可能来自旧备份（未经写端门），统一过下方
        # 收编写回 schema 门剔除坏条目；备份缺定义的条目登记「定义不可恢复」
        # 从本轮验证集剔除（宁少验一个，不写必败文件）。
        unrecoverable: list[str] = []
        # sorted() 使补齐写回的字节序确定：missing_ids 是 set，直接迭代则
        # 依哈希序（跨进程不稳定），test_scenarios.json 条目顺序逐轮漂移，
        # 放大按文件指纹做缓存失效的误失效面。
        for mid in sorted(missing_ids):
            if mid in backup_map:
                reconciled.append(backup_map[mid])
            else:
                unrecoverable.append(mid)
        if unrecoverable:
            pipeline._context.logger.error(
                "pm_engine",
                f"无理由缺失且备份缺定义的场景定义不可恢复，从本轮验证集"
                f"剔除（宁少验一个，不写必败文件）: {'、'.join(unrecoverable)}",
            )
            diff.change_lines.append(
                f"- 无理由缺失且备份缺定义的场景 {len(unrecoverable)} 个"
                f"定义不可恢复，已剔除：{'、'.join(unrecoverable)}"
            )
        # ── 收编写回 schema 门（D1/D2 / 3.1 同校验收敛）──
        # 备份取回条目与合法 planner 产出再次整体过结构校验：坏条目剔除留痕，
        # 合法部分照常落盘，不整批拒绝。
        write_valid: list = []
        write_rejected_ids: list[str] = []
        for idx, item in enumerate(reconciled):
            if not isinstance(item, dict):
                write_rejected.append(f"[{idx}]非对象({type(item).__name__})")
                continue
            item_id = item.get("id") or f"[{idx}]"
            errs = validate_scenario_dicts([item])
            if errs:
                write_rejected.append(f"{item_id}（{'；'.join(errs[:2])}）")
                # 3.10 同口径（code-review 960c813941d7）：第二遍剔除与第一
                # 遍同登记 id/covers 留痕——否则被本遍剔除条目（多为备份取回
                # 的旧 schema 条目）覆盖的可交互候选会被
                # _apply_interaction_contract 误判「设计漏项」退回 replan，
                # 与 3.10 要避免的「重排-剔除」循环同型。仅登记 schema 非法
                # 条目；非对象条目无 id/covers，与第一遍一致不登记。
                write_rejected_ids.append(str(item_id))
                covers = item.get("covers")
                if isinstance(covers, list):
                    write_rejected_covers.update(str(c) for c in covers if c)
                continue
            write_valid.append(item)
        # 与第一遍登记处（3.10）同形状合并：id 追加进 _last_freeze_rejected
        # 列表、covers 并入 _last_freeze_rejected_covers 字符串集合（id 缺失/
        # 为空防御剔除条目无 id 可登记、仅 covers 入集合，条件不能只看
        # write_rejected_ids）。
        if write_rejected_ids or write_rejected_covers:
            pipeline._last_freeze_rejected.extend(write_rejected_ids)
            pipeline._last_freeze_rejected_covers.update(write_rejected_covers)
        if write_rejected:
            pipeline._context.logger.warning(
                "pm_engine",
                f"补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）: "
                f"{'、'.join(write_rejected)}",
            )
            diff.change_lines.append(
                f"- 补齐写回剔除 {len(write_rejected)} 条非法条目（未落盘）："
                f"{'、'.join(write_rejected)}"
            )
        # 空集兜底（3.5/3.8 同款，code-review fc4dcdc2fcf0）：收编写回 schema 门
        # 若把合法集剔空（备份条目全坏等），MUST NOT 把空数组写入
        # test_scenarios.json——0 场景经 engine.run([]) 产出无 env_error 的
        # 全绿报告、会被洗白门 fail-open 放行判 verified。比照第一遍空集
        # abort 语义：不写文件，以结构化信号交调用点退回 plan / 拒绝重入。
        # code-review item 416f69c853dc：与第一遍空集兜底（空集判定先于
        # save_scenario_set、持久化集保持不变，下轮 diff 维持首轮全量口径）
        # 不同，本分支到达时上方 save_scenario_set 已先行执行——此处有意
        # 接受持久化集与执行文件两份场景事实源分叉（持久化集非空、下轮
        # diff 可继续增量口径），不回滚，仅补 WARNING 留痕说明。
        if not write_valid:
            combined_rejected = rejected + write_rejected
            pipeline._context.logger.error(
                "pm_engine",
                f"补齐写回后无合法场景 '{spec_name}'（过滤 pass {len(rejected)} "
                f"条 + 补齐收编剔除 {len(write_rejected)} 条，写回集为空）— "
                f"不写空文件，退回 plan 重排: {'、'.join(combined_rejected)}",
            )
            # 416f69c853dc：分叉留痕（不落 change_lines——abort 返回值不携带
            # diff，此处追加只会被丢弃；日志是本路径唯一有效留痕通道）。
            pipeline._context.logger.warning(
                "pm_engine",
                f"持久化集与执行文件分叉 '{spec_name}'：test_scenarios.json "
                f"保持 planner 原文件未动，"
                + (
                    "scenarios.json 已写入本轮 diff 场景集，下轮 diff 以更新后"
                    "持久化集为基准（增量口径，非首轮全量）"
                    if persisted_updated
                    else "scenarios.json 本轮写回失败未更新（见前述 ERROR），"
                    "下轮 diff 退化首轮全量口径"
                ),
            )
            return {
                "aborted": "no_valid_scenarios",
                "rejected": combined_rejected,
                "total": len(planner_scenarios),
                "path": str(scenarios_path),
            }
        try:
            # frozen-scenario-schema-migration 2.1：补齐写回同样恒定写入
            # schema_version（备份取回条目可能为旧 schema，先迁移再落盘）
            # tmp+replace 原子写（共用 _atomic_write_text 助手）：裸写中途
            # 被 SIGKILL/断电会留下截断 JSON，下一轮 _load_frozen_or_escalate
            # 会误判 corrupt，触发一轮人工裁决停摆。
            _atomic_write_text(
                scenarios_path,
                json.dumps(
                    prepare_scenarios_for_write(write_valid),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except OSError as e:
            # 3.6：写回相关异常须 ERROR 留痕（外层 except 仅记 WARNING）
            pipeline._context.logger.error(
                "pm_engine",
                f"补齐场景写回失败 '{spec_name}'（spec 可能仍以未过滤文件" f"进入阶段2）: {e}",
            )
        final_valid = write_valid
    else:
        # ── 3.2 主路径写回（MUST，否则本修复对本次事故空转）──
        # 事故实证条件（第 1 轮 / persisted 为空 / 无理由缺失 0）永不进入
        # 上方补齐分支（verification.py:1296），而补齐分支是既有唯一写点；
        # 若只把写回挂补齐分支，非法条目仍留在 planner 写的文件、阶段2
        # 仍旧整轮失败。故在主路径写回过滤后合法子集，覆盖首轮/无缺失轮。
        try:
            # tmp+replace 原子写（共用 _atomic_write_text 助手）：裸写中途
            # 被 SIGKILL/断电会留下截断 JSON，下一轮 _load_frozen_or_escalate
            # 会误判 corrupt，触发一轮人工裁决停摆。
            _atomic_write_text(
                scenarios_path,
                json.dumps(
                    prepare_scenarios_for_write(valid_planner),
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        except OSError as e:
            # 3.6：写回成为主路径，异常以 ERROR 留痕（不得只留 WARNING 旁证）
            pipeline._context.logger.error(
                "pm_engine",
                f"场景合法子集主路径写回失败 '{spec_name}'（spec 将仍以 "
                f"planner 原文件进入阶段2，非法条目可能致整批失败）: {e}",
            )
        final_valid = valid_planner

    # ── 3.9 剔除比例合并统计（以写回前最终合法集为基准）──
    # 既有实现只统计第一遍 rejected（过滤 pass）；补齐 pass 的剔除
    # （write_rejected，含从备份取回的既有场景）现仅 WARNING、无比例升级，
    # 会静默缩小回归面。两遍合并后统一按「写回前最终合法集」基准升级。
    if rejected or write_rejected:
        total_rejected = len(rejected) + len(write_rejected)
        base = len(final_valid) or 1  # 写回前最终合法集为基准（3.9 口径）
        ratio = total_rejected / base
        if ratio > 0.2:
            pipeline._context.logger.error(
                "pm_engine",
                f"场景剔除合计超本轮 20%（{total_rejected} 条剔除 / 写回前"
                f"最终合法集 {len(final_valid)} 条，比例 {ratio:.0%}）"
                f"'{spec_name}' — 可见性兜底升级（非退回触发器）",
            )
            diff.change_lines.append(
                f"- 场景剔除合计 {total_rejected} 条（过滤 pass "
                f"{len(rejected)} + 补齐 pass {len(write_rejected)}），"
                f"超写回前最终合法集 20%"
            )

    pipeline._last_scenario_diff = diff  # 供报告渲染（2.3）读取
    return {"diff": diff, "path": str(path)}


def _apply_interaction_contract(pipeline, spec_name: str) -> dict:
    """场景执行前校验交互契约覆盖（design D1/D2）。

    页面类 SPEC 检出可交互候选时，校验场景集对每个候选的覆盖（``covers``
    登记 / 场景文本命中）或纯展示声明（``declared_display`` / SPEC 标注）。
    辅助治理：任何异常不阻断验证主流程。

    Returns:
        {"ok": True} 或 {"ok": False, "result": ContractResult,
        "feedback": <退回 plan 的反馈文本>, "uncovered": [元素标识]}
    """
    # code-review f0309026fbc9：入口先清空实例缓存——本函数任何异常跳过路径
    # （下方 except 直接 return）不得遗留上一 spec/上一轮的 ContractResult。
    pipeline._last_interaction_contract = None
    from core.interaction_contract import (
        validate_interaction_coverage,
        build_replan_feedback,
        load_planner_scenarios,
    )
    from core.verify_scenarios import load_scenario_set
    from core.pm_engine.verification.report_gate import verify_progress_dir

    try:
        scenarios_path = (
            verify_progress_dir(pipeline, spec_name) / "test_scenarios.json"
        )
        planner_scenarios = load_planner_scenarios(scenarios_path)
        if planner_scenarios is None:
            return {"ok": True, "skipped": True}
        persisted = load_scenario_set(pipeline._context.project_root, spec_name)
        result = validate_interaction_coverage(
            pipeline._context.project_root, spec_name, planner_scenarios, persisted
        )
        # evo-planner-scenario-schema-alignment 3.10：被 schema 预校验剔除的
        # 场景覆盖的候选不属「设计漏项」缺口——剔除已在该场景自身暴露结构
        # 问题并单独留痕（3.1 剔除 + 3.4/3.9 比例升级），覆盖校验将其从
        # uncovered 移除，避免「重排-剔除」循环（剔除改变文件 → 覆盖校验
        # 误判缺口 → 退回重排 → planner 再生成同类非法场景）。本去噪仅对
        # 覆盖登记（covers 字段）生效；未登记 covers 的文本命中式覆盖无法
        # 从剔除侧反推，按既有「设计漏项」判定（3.10 至少区分两类缺口）。
        # code-review 3dd5194ce79b：归属戳校验——rejected_covers 缓存仅对当前
        # spec 的冻结轮生效；冻结复用轮不重算冻结，跨 spec 复用残留视为无缓存
        # （不豁免），避免把上轮/其它 spec 剔除清单误套到本 spec 覆盖缺口上。
        if getattr(pipeline, "_last_freeze_owner", None) != spec_name:
            rejected_covers = set()
        else:
            rejected_covers = getattr(pipeline, "_last_freeze_rejected_covers", None) or set()
        if rejected_covers and not result.ok and result.uncovered:
            remaining = [k for k in result.uncovered if k not in rejected_covers]
            removed = [k for k in result.uncovered if k in rejected_covers]
            if removed:
                pipeline._context.logger.warning(
                    "pm_engine",
                    f"交互契约覆盖校验 '{spec_name}'：{len(removed)} 个候选"
                    f"原由被 schema 预校验剔除的场景覆盖"
                    f"（{sorted(removed)}）— 归为「条目非法剔除」缺口，"
                    f"不计入设计漏项，不触发退回",
                )
                result.uncovered = remaining
                result.ok = not remaining
                result.change_lines.append(
                    f"- 元素 {'、'.join(sorted(removed))} 原由被 schema "
                    f"预校验剔除的场景覆盖（剔除已单独留痕），不属设计漏项"
                )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine", f"交互契约校验跳过 '{spec_name}'（不阻断）: {e}"
        )
        return {"ok": True, "skipped": True}

    pipeline._last_interaction_contract = result
    if result.ok:
        pipeline._context.logger.info(
            "pm_engine",
            f"交互契约覆盖校验通过 '{spec_name}'（候选 "
            f"{len(result.candidates)} 个，纯展示声明 {len(result.declared)} 个）",
        )
        return {"ok": True, "result": result}

    pipeline._context.logger.warning(
        "pm_engine",
        f"交互契约覆盖不完整 '{spec_name}': {result.uncovered}",
    )
    return {
        "ok": False,
        "result": result,
        "feedback": build_replan_feedback(result),
        "uncovered": list(result.uncovered),
    }


def _render_scenario_change_section_to_report(pipeline, spec_name: str) -> None:
    """把本轮场景集变更小节追加到 verification-report.md（spec 需求 2.3）。

    报告闸门（add-verify-report-gate）已保证文件存在；此处幂等追加，
    重复调用会因已存在「本轮场景集变更」标题而跳过。diff 来源优先级：
    ``_last_scenario_diff``（本轮冻结计算）> 重新读取 scenarios.json（首轮）。
    """
    # code-review 3dd5194ce79b：diff 归属戳校验——非当前 spec 冻结轮写入的缓存
    # （跨 spec 复用残留）不作为渲染来源，回落重新读取 scenarios.json 分支。
    diff = (
        getattr(pipeline, "_last_scenario_diff", None)
        if getattr(pipeline, "_last_freeze_owner", None) == spec_name
        else None
    )
    from core.verify_scenarios import (
        render_change_section,
        load_scenario_set,
        render_first_write_section,
    )

    if diff is None:
        persisted = load_scenario_set(pipeline._context.project_root, spec_name)
        if persisted is None:
            return
        section = render_first_write_section(persisted)
    else:
        section = render_change_section(diff)
    if not section.strip():
        return
    report_path = (
        Path(pipeline._context.project_root)
        / "spec"
        / "changes"
        / spec_name
        / "verification-report.md"
    )
    if not report_path.exists():
        return
    try:
        content = report_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    # 幂等契约（code-review a750f799c664）：以标题已存在于报告文件为判定——
    # 同轮重复调用跳过；报告文件跨验证轮留存时（Verifier 未重写报告），后续
    # 轮的场景集变更同样不再补写。这是「每份报告至多一段」的有意取舍而非
    # 疏漏：入库提交器（verify-report-scenario-section-commit）按每报告至多
    # 一段设计为额外提交至多一次，逐轮指纹改写标题会变更报告形态、牵动报告
    # 闸门与入库提交，未纳入当前契约。Verifier 按报告闸门每轮重写报告后
    # 标题不复存在，新一轮变更小节照常由本函数补写。
    if "## 本轮场景集变更" in content:
        return
    # add-verify-report-gate 要求不覆盖 mtime 语义仅针对「Agent 已写」文件；
    # 此处为框架追加小节，直接写回（Agent 漏写场景变更时由框架补）。
    # tmp+replace 原子写（共用 _atomic_write_text 助手）：裸写中途崩溃会
    # 留下截断报告，截断残留仍携带本轮轮次指纹，会被报告闸门以 present 放行。
    # inherit_existing_mode=True（item abfbfb073153）：报告文件可能被运维
    # 刻意收紧权限，os.replace 整体替换不得静默改动既有权限口径。
    try:
        _atomic_write_text(
            report_path,
            content.rstrip("\n") + "\n" + section + "\n",
            inherit_existing_mode=True,
        )
    except OSError as e:
        pipeline._context.logger.warning("pm_engine", f"场景集变更小节写回失败 '{spec_name}': {e}")
        return
    # verify-report-scenario-section-commit：小节写盘即入库。采纳路径里报告
    # 闸门的提交先于本函数（pipeline._apply_bug_found / _apply_verified 内：
    # add-verify-report-gate 报告闸门 → transition → 函数末尾渲染）且此后
    # 再无提交点，场景段会长期滞留工作区——复用同一 pathspec
    # 单文件幂等提交器补上该缝（每报告至多一段 → 额外提交至多一次）。失败
    # 降级由提交器内建（git 失败仅 WARNING、非 git 项目静默跳过），此处再兜
    # 意外异常：入库动作绝不影响渲染写盘结论与验证主流程。
    # code-review 14bc75c819c6：跨模块消费改走公开别名 commit_verification_report，
    # 不再依赖 core.verify_report 私有符号（模块边界风格）。
    from core.verify_report import commit_verification_report

    try:
        commit_verification_report(
            pipeline._context.project_root, spec_name, pipeline._context.logger
        )
    except Exception as e:  # pragma: no cover - 防御分支（提交器已内建降级）
        pipeline._context.logger.warning(
            "pm_engine", f"场景集变更小节入库失败 '{spec_name}': {e}"
        )


def _write_verify_contract_missing(
    pipeline, spec_name: str, note: str, evidence: str, recommended_action: str = ""
) -> None:
    """写 verify_contract_missing 信号呼叫 Administrator（契约相关 fail-fast 共用）。

    契约缺失/损坏/入口预检失败/轻量自证失败的统一出口（design D1/D2）：
    spawn 前确定性错误不等待失败计数与升级冷却，直接派发。失败记 warning
    不抛穿调用方（信号通道自身不可影响验证判定）。
    """
    from core.admin_store import AdminStore, SIGNAL

    try:
        # AdminStore 构造纳入 try（code-review 41d7e6713728，对齐 engine.py
        # _signal_push_failed / item 105c8965ec12 同款手法）：构造涉及目录/
        # 文件访问，磁盘满或权限异常时若在 try 外抛出，会从本函数穿透契约
        # fail-fast 出口的调用方（验证判定主链），违背「信号通道自身不可
        # 影响验证判定」的 docstring 承诺。
        # [fenix-ignore:5028cf9445b7] AdminStore 构造已随 item 105c8965ec12（41d7e6713728）移入 try，构造抛错不再上抛，本条目不成立
        store = AdminStore(pipeline._context.project_root, pipeline._context.logger)
        store.append(
            {
                "kind": SIGNAL,
                "signal_type": "verify_contract_missing",
                "spec": spec_name,
                "severity": "major",
                "description": note,
                "evidence": evidence,
                "recommended_action": recommended_action
                or (
                    "Administrator 修正 .fenix/verify.yaml 验证契约："
                    "检查构建命令、serve 段入口/静态目录、端口注入；"
                    "修正后 git 提交 → spec 复位 ready 触发重验证"
                ),
            }
        )
    except Exception as e:
        pipeline._context.logger.error("pm_engine", f"verify_contract_missing 信号写入失败: {e}")


def _emit_static_findings(
    pipeline,
    spec_name: str,
    scan_fn,
    write_fn,
    rule_id_of,
    check_name: str,
    log_label: str,
) -> None:
    """场景静态检查挂点的写盘/分布日志骨架：扫描 → 写盘 → 分布日志（fail-open）。

    仅覆盖场景静态检查挂点（_run_scenario_static_check）；契约挂点
    （_run_contract_static_check）因需在写盘/分布日志之后继续消费 findings
    做 serve 缺失打回、且异常时须向调用方返回 False，有意内联同一套骨架，
    不复用本助手——两份骨架的日志格式/fail-open 语义如需调整须同步修改。

    扫描（含前置产物读取）经 ``scan_fn`` 在 fail-open 保护内执行，返回
    ``(findings, info_head)``；``findings is None`` 表示前置不满足、静默
    跳过（不写盘不记日志）。写盘复用 ``write_fn``，findings 非空时按
    ``rule_id_of`` 统计 rule_id 分布记 INFO（``info_head`` 承载 INFO 文案
    措辞）；任何异常记 WARNING（``check_name``/``log_label`` 承载 WARNING
    文案措辞），不影响验证主流程。
    """
    try:
        findings, info_head = scan_fn()
        if findings is None:
            return
        write_fn(pipeline._context.project_root, spec_name, findings)
        if findings:
            from collections import Counter

            dist = dict(Counter(rule_id_of(f) for f in findings))
            pipeline._context.logger.info(
                "pm_engine",
                f"{info_head}检出 {len(findings)} 条情报: {dist}",
            )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"{check_name}跳过 '{spec_name}'（fail-open，{log_label}）: "
            f"{type(e).__name__}: {e}",
        )


def _run_scenario_static_check(pipeline, spec_name: str) -> None:
    """场景静态缺陷扫描挂点（add-scenario-defect-triage-gate D3）。

    在场景集冻结完成后、阶段2 执行前调用（_run_three_stage_verification
    经门面转调）。findings 覆盖写 ``scenario_static_findings.json`` 供
    judge prompt 情报段注入——**只做情报不拦截执行**，任何异常记 WARNING
    不阻断验证（fail-open）。写盘与分布日志骨架共用 _emit_static_findings。
    """
    from core.verify_engine.scenario_static_check import (
        scan_scenarios,
        write_findings,
    )
    from core.pm_engine.verification.report_gate import verify_progress_dir

    scenarios_path = (
        verify_progress_dir(pipeline, spec_name) / "test_scenarios.json"
    )

    def _scan():
        if not scenarios_path.exists():
            return None, ""
        try:
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # 解析失败就地留专名 WARNING 后跳过（比照契约挂点
            # _run_contract_static_check._scan，两份骨架的同步约定要求解析
            # 容错口径一致，不依赖 _emit_static_findings 的通用 fail-open
            # 归因文案）。load_scenarios 验收与执行期门禁各自有既有处置，
            # 此处不重复拦截。
            pipeline._context.logger.warning(
                "pm_engine",
                f"场景静态扫描跳过 '{spec_name}'（场景文件不可解析）: "
                f"{type(e).__name__}: {e}",
            )
            return None, ""
        if not isinstance(data, list):
            return None, ""
        serving_port = pipeline._serving_port_for_spec(spec_name)
        findings = scan_scenarios(data, serving_port=serving_port)
        info_head = f"场景静态扫描 '{spec_name}'（serving 端口 {serving_port or '未知'}）"
        return findings, info_head

    _emit_static_findings(
        pipeline,
        spec_name,
        scan_fn=_scan,
        write_fn=write_findings,
        rule_id_of=lambda f: f.rule_id,
        check_name="场景静态扫描",
        log_label="不阻断验证",
    )


def _run_contract_static_check(pipeline, spec_name: str) -> bool:
    """契约只读一致性检查 + serve 一致性门（出题产物消费期统一挂点）。

    三个出题产物路径统一经过本挂点（evo-add-scenario-serve-consistency-preflight
    1.2，任一路径产物不得绕过 serve 一致性检查）：

    - 新鲜出题验收路径：planner-plan 产物验收通过后（pipeline.py 出题完成处）；
    - 冻结场景复用路径：``_load_frozen_or_escalate`` 消费前；
    - 并行出题产物消费路径：``_consume_parallel_plan_product`` 消费后、冻结
      加载前（产物在盘即先过检查再消费）。

    检查内容：对验证契约做只读一致性检查（入口存在性/与 start script 一致性/
    端口注入 + serve 缺失×场景 kind 交叉规则），findings 覆盖写
    ``contract_findings.json`` 供 admin 处置 prompt 注入。打回机制对齐
    selfcheck 先例（pipeline.py 契约消费期轻量自证段）：serve 缺失 cross
    finding 走 ``_write_verify_contract_missing`` 通道阻断场景执行、派发
    Administrator 起草，**不触发 planner replan**（重排出题无助于契约缺口）；
    既有三条规则维持留痕不阻断；检查器异常沿用 scan_contract 既有 fail-open
    不阻断验证。

    Returns:
        True = serve 缺失 cross finding 已打回（调用方 MUST return 终止本轮
        验证流水线）；False = 放行（含产物缺失/无 finding/检查器异常 fail-open）。
    """
    from core.verify_engine.scenario_static_check import (
        SERVE_MISSING_RULE_ID,
        scan_contract,
        start_fallback_valid,
        write_contract_findings,
    )
    from core.pm_engine.verification.report_gate import verify_progress_dir

    scenarios_path = (
        verify_progress_dir(pipeline, spec_name) / "test_scenarios.json"
    )

    def _scan():
        if not scenarios_path.exists():
            # 产物未落盘（纯新鲜出题轮的消费前挂点）：零情报零阻断，主路径
            # 挂点在出题验收后兜底。
            return None, ""
        try:
            data = json.loads(scenarios_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            # 解析失败留痕后跳过 kind 相关交叉规则（load_scenarios 验收与
            # 执行期门禁各自有既有处置，此处不重复拦截）。
            pipeline._context.logger.warning(
                "pm_engine",
                f"契约静态检查跳过 kind 统计 '{spec_name}'（场景文件不可解析）: "
                f"{type(e).__name__}: {e}",
            )
            return None, ""
        if not isinstance(data, list):
            return None, ""
        # kind 集按执行 kind 原样统计（口径同 serving.py:960，缺失 kind 缺省 web）
        kinds = {str(sc.get("kind", "web")) for sc in data if isinstance(sc, dict)}
        start_cmd = str(pipeline._context.config_reader("commands.start", "") or "")
        findings = scan_contract(
            pipeline._context.project_root,
            scenario_kinds=kinds,
            start_cmd=start_cmd,
        )
        info_head = (
            f"契约静态检查 '{spec_name}'（kind 集 {','.join(sorted(kinds)) or '空'}，"
            f"start 兜底{'有效' if start_fallback_valid(start_cmd) else '缺失/占位'}）"
        )
        return findings, info_head

    try:
        findings, info_head = _scan()
        if findings is None:
            return False
        # [fenix-ignore:2a856a7801d5] write_contract_findings 内部已全量 try/except（写盘失败仅 WARNING 不外抛），磁盘满/权限异常不会经本处 fail-open 短路、下方 serve 打回段照常可达
        write_contract_findings(pipeline._context.project_root, spec_name, findings)
        if findings:
            from collections import Counter

            dist = dict(Counter(f["rule_id"] for f in findings))
            pipeline._context.logger.info(
                "pm_engine",
                f"{info_head}检出 {len(findings)} 条情报: {dist}",
            )
    except Exception as e:
        pipeline._context.logger.warning(
            "pm_engine",
            f"契约静态检查跳过 '{spec_name}'（fail-open，不阻断验证）: "
            f"{type(e).__name__}: {e}",
        )
        return False
    serve_missing = [f for f in findings if f.get("rule_id") == SERVE_MISSING_RULE_ID]
    if not serve_missing:
        return False
    # ── serve 缺失打回（对齐 selfcheck 先例：信号通道 + env 阻塞升级 + return）──
    # 全部缺口随信号下行（code-review item 34dc470c3cfe）：多 kind 场景各有
    # 缺口时只上报首条，Administrator 修掉第一处后会被同一门再次打回——
    # 逐条汇总进信号描述并注明命中总数，升级清单同步给全量。
    finding = serve_missing[0]
    all_messages = [str(f.get("message") or "") for f in serve_missing]
    pipeline._context.logger.error(
        "pm_engine",
        f"契约 serve 一致性门打回 '{spec_name}' — fail-fast 阻断场景执行"
        f"（不触发 planner replan，重排出题无助于契约缺口；命中 "
        f"{len(serve_missing)} 处）: {'；'.join(all_messages)}",
    )
    _write_verify_contract_missing(
        pipeline,
        spec_name,
        (
            f"{finding.get('message')}（契约静态检查 serve 缺失交叉规则命中，"
            f"出题产物消费期打回，场景执行数为 0；共 {len(serve_missing)} 处缺口）"
            + (
                "\n" + "\n".join(f"- {m}" for m in all_messages)
                if len(serve_missing) > 1
                else ""
            )
        ),
        str(finding.get("evidence") or ""),
        recommended_action=(
            "Administrator 起草 .fenix/verify.yaml 验证契约 serve 段："
            "检查项目构建命令、静态目录、服务启动方式与端口注入；"
            "草稿写临时路径 → bin/fenix_verify_contract.py 自证 → "
            "全通才落位 → git 提交 → spec 复位 ready 触发重验证"
        ),
    )
    pipeline._escalate_env_blocked(
        spec_name,
        all_messages,
        title="验证环境阻塞（契约 serve 缺失）",
    )
    return True
