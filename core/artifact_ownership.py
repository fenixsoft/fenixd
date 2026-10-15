"""验证链产物归属表（add-task-artifact-ownership-gate，D2）。

声明式定义：每个验证链产物由哪个车道产出，作为单一真相源供 lint 与
起草自检共用。

判据规则（design D1，三重合取才判违规，零误拦取向）：
1. 任务行命中已登记的验证链产物引用——路径限定到 ``.fenix/verify-progress/``
   且为核心产物之一（``test_scenarios.json``/``scenarios.json``/
   ``report.json``/``<vp_dir>/.fenix-run-result.json``），**或**为
   ``.fenix/verify-progress/<spec>/`` 目录本身的持久化引用；
2. 该引用处未指向任何代码文件——遮蔽命中产物后，行内无代码扩展名
   （``.py``/``.ts``/``.tsx``/``.js``/``.jsx``/``.sh``/``.yaml``/``.yml``）
   或代码路径特征（``core/``/``agents/``/``tests/``/``bin/``/``skills/``/``docs/``）；
3. 引用前出现产出动词（写/落盘/持久化/保存/落位/序列化/追加；单字
   「写」不含「改写/编写/誊写/抄写/读写」等改写/读取语义），动词与
   引用之间无记录语义上下文词（记录/说明/描述/含义/文档），且
   执行车道 ∉ 该产物归属车道集合。

放行形态（MUST NOT 判违规）：
- 裸 ``test_scenarios.json``/``scenarios.json``/``report.json`` 字面量
  （未路径限定到 ``.fenix/verify-progress/``）——``specs/scenarios.json``
  指 spec 目录下的场景定义件；「旧格式 report.json 兼容解析」为读取语义；
- 裸 ``.fenix-run-result.json``——实现者/fast-track 自己的收工票据；
- 未登记到归属表的侧车产物（``tokens.json``/``fail_history.json``/
  ``warning_streaks.json``/``scenario_reroute_stoploss.json`` 等）；
- 无尾斜杠的目录指称——目录级引用要求尾斜杠（``.fenix/verify-progress/
  <spec>/``），「写 ``.fenix/verify-progress/foo（结果目录）``」这类无尾
  斜杠形态不判目录级、也不命中文件级（无已登记产物名），有意保守放行；
- 「写代码让框架产出该文件」的任务（含代码文件特征）；
- 产出动词与产物引用之间出现记录语义上下文词的行——动词宾语是
  「记录/说明」类文档、产物引用只是其记录对象（如「写 README 记录
  ``.fenix/verify-progress/<spec>/report.json`` 的字段含义」，「写」的
  宾语是 README 而非该产物路径）。

构成本模块为纯函数、零 IO：判定函数不含文件读写，车道由调用侧传入
（缺失按 ``full``），异常不外抛（fail-open）。
"""

from __future__ import annotations

import re
import warnings
from typing import List, Mapping, Set

# ============================================================================
# 归属表常量（声明式单一真相源）
# ============================================================================

# 验证链核心产物 → 归属车道集合
# 注意：验证链产物归属集合 MUST NOT 含 implementer（实现者车道）
VERIFICATION_ARTIFACT_OWNERS: Mapping[str, Set[str]] = {
    # planner-plan 产出的测试场景文件（fast-track 亦为合法产出车道）
    "test_scenarios.json": {"planner-plan", "fast-track"},
    # pm_engine 持久化写侧产出的场景文件（fast-track 亦为合法产出车道）
    "scenarios.json": {"pm_engine", "fast-track"},
    # verify_engine 产出的验证报告
    "report.json": {"verify_engine"},
    # planner-judge 结果文件（位于 .fenix/verify-progress/<spec>/ 下）
    ".fenix-run-result.json": {"planner-judge"},
}

# ``.fenix/verify-progress/<spec>/`` 目录级持久化引用的归属车道
# （该目录由多个车道写入，任何要求把产物写入该目录的实现者任务都判违规）
VERIFY_PROGRESS_DIR_OWNERS: Set[str] = {
    "planner-plan",
    "pm_engine",
    "verify_engine",
    "planner-judge",
    "fast-track",
}

# worktree 根 ``.fenix-run-result.json`` 的归属车道
# （实现者/fast-track 自己的收工票据，合法交付，不触发违规）。
# 仅作声明式文档记录，当前无判定逻辑消费：裸 ``.fenix-run-result.json``
# 的放行由 _VP_ARTIFACT_RE 的路径限定前缀隐式完成，判定函数不读本表。
IMPL_RESULT_FILE_OWNERS: Set[str] = {"implementer", "fast-track"}

# ============================================================================
# 匹配常量
# ============================================================================

# 代码文件扩展名（步骤 2 遮蔽后检查）
# 注意：.json 等非代码扩展名有意不列入本清单——incident 产物路径为
# 读取/记录语义，不算代码文件特征；排除由清单缺省隐式完成，本处为
# 单一说明，各判定处不做逐点特判。
_CODE_EXTENSIONS: tuple = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".sh",
    ".yaml",
    ".yml",
)

# 代码路径特征前缀（步骤 2 遮蔽后检查）
_CODE_PATH_PREFIXES: tuple = (
    "core/",
    "agents/",
    "tests/",
    "bin/",
    "skills/",
    "docs/",
)

# 产出动词（步骤 3 判定）
_PRODUCTION_VERBS: tuple = (
    "写",
    "落盘",
    "持久化",
    "保存",
    "落位",
    "序列化",
    "追加",
)

# 单字产出动词的前缀否定字：「改写/编写/誊写/抄写/读写」为改写既有
# 内容或读取语义，非产出动词（零误拦取向，design D1）
_SINGLE_CHAR_VERB_NEGATION_PREFIXES: str = "改编誊抄读"

# 记录语义上下文词（步骤 3 放行）：产出动词与产物引用之间若出现此类词，
# 动词的宾语是「记录/说明」类文档而非产物本身，产物引用只是其记录对象
# ——「写 README 记录 <产物路径> 的字段含义」不判违规（零误拦取向，
# design D1）。判定窗口有意取「引用前最后一个产出动词之后 → 引用之前」
# 的间隙：整行前缀会把长任务行中属于另一宾语的远处动词误归因到引用；
# 固定 N 字符邻接窗口则覆盖不了「生成并落盘 test_scenarios.json 到
# <目录>」这类合法间距（文件名本身即占 19+ 字符，两形态间距重叠、
# 无可分窗口）。
_RECORD_SEMANTIC_WORDS: tuple = (
    "记录",
    "说明",
    "描述",
    "含义",
    "文档",
)

# ============================================================================
# 正则
# ============================================================================

# 任务行匹配（参照 core/deliverables.py 的 _TASKS_ITEM_RE 另行定义，非共享
# 常量：两处形态已各自独立演进——本处需捕获任务 id 且允许连字符后任意
# 单空白，deliverables.py 为连字符后恒为空格、无捕获）
_TASKS_ITEM_RE = re.compile(r"^-\s\[[ x]\]\s+([^\s]+)")

# 已登记核心产物的路径引用：.fenix/verify-progress/<spec>/<核心产物>
# 产物名后补右边界负向预查（code-review b059ebd8ea9b）：仅排除 ASCII
# 标识符续字符与「. + ASCII 字母数字」续段——``report.json.bak``/
# ``test_scenarios.json.tmp`` 等以产物名为前缀的衍生物文件名不再被当作
# 核心产物命中（叠加产出动词即误拦），与 _VP_DIR_REF_RE 的边界预查
# 严谨度对齐。字符类沿用 _CODE_EXT_RE 的 ASCII 负向预查口径（不用
# ``\w``：Unicode 词符下汉字属词字符，``report.json的`` 等中文直接
# 邻接形态须仍判命中）；裸 ``.`` 不进排除类——``report.json.`` 的
# 英文句末标点是合法边界，须保持既有命中。
_VP_ARTIFACT_RE = re.compile(
    r"\.fenix/verify-progress/[^/\s]+/(?:"
    + "|".join(re.escape(k) for k in VERIFICATION_ARTIFACT_OWNERS)
    + r")(?![A-Za-z0-9_])(?!\.[A-Za-z0-9])"
)

# ``.fenix/verify-progress/<spec>/`` 目录级引用：
# 目录后必须紧跟空白 / 中文标点 / 行尾 / 反引号 / 直引号或中文引号或
# 右方括号等引用闭合符（Markdown 代码标记闭合——
# 任务的路径引用常被反引号或引号包裹，如 ``到 `.fenix/verify-progress/<spec>/` ``）。
# 否则是文件级引用——已登记产物走 _VP_ARTIFACT_RE，未登记侧车文件放行，
# 均非目录级。
# 尾斜杠是目录级判定的必要条件（有意保守，零误拦取向）：无尾斜杠的目录
# 指称（「写 ``.fenix/verify-progress/foo（结果目录）``」）不判目录级——
# spec 段尾斜杠是区分「目录本身」与「未登记文件名」（如 ``<spec>.json``）
# 的唯一可靠信号，设为可选会误吞文件级引用作目录级命中。
_VP_DIR_REF_RE = re.compile(
    r"\.fenix/verify-progress/[^/\s]+/(?=[\s，,。、；;）)】`'\"」』\]]|$)"
)

# 代码扩展名出现（遮蔽后扫描）——由 _CODE_EXTENSIONS 动态拼接（同
# _VP_ARTIFACT_RE 做法），保持扩展名清单单一真相源。
# 尾部不用 ``\b``（code-review 068aaffb4310）：Python 3 str 正则的 \b 按
# Unicode 词符判定、汉字属词字符，扩展名后紧邻中文的形态（``api.ts的``/
# ``api.ts后``）\b 失配 → 步骤 2 代码特征漏检，叠加产出动词即按归属违规
# 误拦合法任务行。改用仅排除 ASCII 标识符续字符的负向预查：扩展名后接
# 中文等非 ASCII 字符仍判命中；``.ts_x`` 这类标识符续字符形态与原 \b
# 行为一致不命中（属更长标识符，非独立扩展名）。
_CODE_EXT_RE = re.compile(
    r"\.(?:" + "|".join(re.escape(ext[1:]) for ext in _CODE_EXTENSIONS) + r")(?![A-Za-z0-9_])"
)

# 产出动词匹配（步骤 3）：单字动词以否定回顾排除改写/读取语义前缀
_PRODUCTION_VERB_RE = re.compile(
    "|".join(
        f"(?<![{_SINGLE_CHAR_VERB_NEGATION_PREFIXES}]){re.escape(verb)}"
        if len(verb) == 1
        else re.escape(verb)
        for verb in _PRODUCTION_VERBS
    )
)


# ============================================================================
# 内部判定
# ============================================================================


def _line_points_to_code(line: str, mask_literal: str = "") -> bool:
    """判定任务行是否指向任何代码文件（步骤 2：无代码文件引用才判违规）。

    把命中的产物字面量遮蔽（mask）后，扫描行内是否出现代码扩展名
    （``.py``/``.ts``/``.tsx``/``.js``/``.jsx``/``.sh``/``.yaml``/``.yml``）
    或代码路径特征（``core/``/``agents/``/``tests/``/``bin/``/``skills/``/
    ``docs/``）。

    Args:
        line: 任务行原文。
        mask_literal: 需遮蔽的产物字面量（如 ``test_scenarios.json``）。

    Returns:
        True 表示行内含代码文件特征（需放行）。
    """
    masked = line.replace(mask_literal, "") if mask_literal else line

    # 代码扩展名（.json 等非代码扩展名不在 _CODE_EXTENSIONS 清单内——
    # incident 产物路径为读取/记录语义，有意不算代码特征，见清单处说明）
    if _CODE_EXT_RE.search(masked):
        return True

    # 代码路径特征
    for prefix in _CODE_PATH_PREFIXES:
        if prefix in masked:
            return True

    return False


def _line_has_production_verb(line: str, ref_end: int) -> bool:
    """判定产物引用之前是否出现产出动词（步骤 3）。

    单字动词「写」要求其前一个字符不在
    ``_SINGLE_CHAR_VERB_NEGATION_PREFIXES`` 中——「改写/编写/誊写/抄写/
    读写」为改写既有内容或读取语义，不计产出动词。

    邻接约束：动词搜索不取整行前缀，而以「引用前最后一个产出动词 →
    引用」的间隙为判定窗口——间隙出现记录语义上下文词
    （``_RECORD_SEMANTIC_WORDS``）即视为动词宾语是「记录/说明」类文档、
    产物引用仅为其记录对象，放行（零误拦取向）。「写 README 记录
    <产物路径> 的字段含义」不再把远处动词「写」误归因到产物引用。

    Args:
        line: 任务行原文。
        ref_end: 产物引用匹配的结束位置（字符索引）。

    Returns:
        True 表示引用之前出现产出动词，且最后一个动词与引用之间的间隙
        不含记录语义上下文词。
    """
    prefix = line[:ref_end]
    verb_matches = list(_PRODUCTION_VERB_RE.finditer(prefix))
    if not verb_matches:
        return False
    # 只看最后一个产出动词：它与引用之间的间隙才反映该引用的真实语义
    # （更早的动词可能属于行内另一宾语，其间隙与本引用无关）
    gap = prefix[verb_matches[-1].end():]
    return not any(word in gap for word in _RECORD_SEMANTIC_WORDS)


# ============================================================================
# 判定入口（单一真相入口，供 lint 与起草自检复用）
# ============================================================================


def ownership_violations_for_task_line(line: str, lane: str) -> List[str]:
    """判定单条任务行是否存在产物归属违规（design D1 三重合取）。

    Args:
        line: tasks.md 任务行原文（如 ``- [ ] 6.2 写 .fenix-run-result.json …``）。
        lane: 执行车道——``"fast-track"`` 或 ``"full"``（full 车道执行者为
            implementer）。缺失/未知值调用侧应先按 ``full`` 归一。

    Returns:
        违规描述清单；空列表 = 无违规。

    Raises:
        不会抛出：自身故障一律 fail-open（返回空清单）。
    """
    violations: List[str] = []
    try:
        task_id = ""
        m = _TASKS_ITEM_RE.match(line)
        if m:
            task_id = m.group(1)

        # ---- 步骤 1a：已登记核心产物的路径限定引用 ----
        # 单行可能重复提及同一产物路径：同字面量只判一次（与步骤 1b 的
        # seen_dirs 去重口径一致，避免输出重复违规消息）
        seen_artifacts: Set[str] = set()
        vp_artifacts = list(_VP_ARTIFACT_RE.finditer(line))
        core_hits: List[str] = []
        for match in vp_artifacts:
            literal = match.group(0)
            if literal in seen_artifacts:
                continue  # 同字面量只报一次
            seen_artifacts.add(literal)
            artifact_key = _match_artifact_key(literal)
            if artifact_key is None:
                continue  # 防御：未登记文件（理论不可达）
            owners = VERIFICATION_ARTIFACT_OWNERS[artifact_key]
            core_hits.append(literal)
            if _line_points_to_code(line, artifact_key):
                continue  # 步骤 2：含代码文件 → 写代码让框架产出 → 放行
            if _line_has_production_verb(line, match.end()) and lane not in owners:
                violations.append(
                    _violation_message(task_id, literal, owners)
                )
        if core_hits:
            # 有意取舍：命中任一核心产物后整行提前返回，连步骤 1b 的目录级
            # 引用（含同一路径之外的其他 spec 目录）一并保守漏报，以维持
            # 本函数「零误拦」取向；并非仅做同路径去重。
            return violations

        # ---- 步骤 1b：``.fenix/verify-progress/<spec>/`` 目录级引用 ----
        # 遍历全部目录级引用（单行可能引用多个 spec 目录），同字面量只判一次
        seen_dirs: Set[str] = set()
        for vp_dir in _VP_DIR_REF_RE.finditer(line):
            literal = vp_dir.group(0)
            if literal in seen_dirs:
                continue  # 同路径只报一次
            seen_dirs.add(literal)
            if _line_points_to_code(line, literal):
                continue  # 步骤 2：含代码文件 → 放行
            if (
                _line_has_production_verb(line, vp_dir.end())
                and lane not in VERIFY_PROGRESS_DIR_OWNERS
            ):
                violations.append(
                    _violation_message(
                        task_id,
                        literal,
                        VERIFY_PROGRESS_DIR_OWNERS,
                        is_dir=True,
                    )
                )

    except Exception as exc:  # pragma: no cover - 防御分支
        try:
            warnings.warn(
                f"ownership_violations_for_task_line 自身故障（fail-open）: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )
        except Exception:
            pass
        return []

    return violations


def _match_artifact_key(literal: str):
    """从路径字面量中识别命中的归属表 key（含 ``.fenix-run-result.json``）。

    按 key 长度降序取最长命中：``scenarios.json`` 是 ``test_scenarios.json``
    的子串，子串匹配不得依赖归属表插入顺序（否则 ``test_scenarios.json``
    引用会被误判成 ``scenarios.json``）。
    """
    for key in sorted(VERIFICATION_ARTIFACT_OWNERS, key=len, reverse=True):
        if key in literal:
            return key
    return None


def _violation_message(task_id: str, literal: str, owners: Set[str], is_dir: bool = False) -> str:
    """构造违规消息：点名任务行 id + 命中产物路径 + 纠正处方。

    处方措辞与 ``skills/fenix-new`` §3.2.1 第 5 类一致：改写为
    「实现 X 让框架产出该文件」或移出任务书。消息尾部附启发式判定
    标注：本判定为三重合取启发式（存在已知精度边界），供上游对读取/
    记录语义形态的残余误报降权。
    """
    if is_dir:
        head = f"任务 {task_id}：要求把产物持久化到 verify-progress 目录 {literal!r}"
    else:
        head = f"任务 {task_id}：要求实现者产出验证链产物 {literal!r}"
    return (
        f"{head}——该文件/目录由验证链车道"
        f"{'、'.join(sorted(owners))} 产出，实现者交付时尚不存在、无法满足；"
        f"请改写为「实现 X 让框架产出该文件」（写出产出该文件所需的代码），"
        f"或将其移出任务书（reference / `.fenix/todo.md` 人工步骤）"
        f"（本条为启发式判定：若该引用实为读取/记录语义则属误报，可忽略）"
    )