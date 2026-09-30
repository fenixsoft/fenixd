"""
scenarios.py — 测试场景数据结构定义与校验

定义了 TestStep、Assertion、TestScenario 三个核心数据类，
以及场景加载/校验/序列化逻辑。
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import re

# ── schema 版本标记（frozen-scenario-schema-migration D2）──────────
# 当前场景文件 schema 版本号。写入端恒定写入；读侧按版本路由迁移：
# 无版本=旧 schema 走迁移，当前版本直通，未知版本走迁移尝试+字段差异报错。
SCHEMA_VERSION = 1

# ── 契约版本标记（evo-frozen-scenario-contract-versioning D1）──────
# 场景验收契约规则版本（条目级字段，语义：「本冻结集符合哪个版本的场景
# 验收契约规则」）。v2 = 「web 场景 MUST 含 navigate 步骤（绝对 URL）」。
# 字段缺失或非整型 → 视为 1（存量兼容，与 _schema_version_notes /
# migrate_scenario_schema 的条目级字段口径一致）；< CURRENT_CONTRACT_VERSION
# 的冻结集在加载时经 migrate_frozen_contract 机械迁移（见下方迁移函数）。
CURRENT_CONTRACT_VERSION = 2

CONTRACT_VERSION_FIELD = "contract_version"


# ── 旧 schema 字段迁移（frozen-scenario-schema-migration D1/D2）────
# 冻结文件（frozen test_scenarios.json）可能以旧字段形态生成：
#   - cli run 步骤：value → command
#   - output_match 断言：value → expected
# 迁移仅对「目标字段缺失且旧字段存在」生效（新 schema 字段存在时零干扰）；
# 迁移后经既有校验；无法迁移（字段整体缺失）时在校验报错中附具体字段差异清单。


def migrate_scenario_schema(raw: list) -> list:
    """旧 schema 场景 dict 列表迁移（读侧预校验步骤）。

    识别旧字段形态并映射到新字段（仅当目标字段缺失时迁移，新字段存在零干扰）：
      - run 步骤（cli 场景，action == 'run'）：value → command
      - output_match 断言（type == 'output_match'）：value → expected

    返回迁移后的新列表（浅拷贝，原列表与各 dict 不变——读无副作用）。
    """
    migrated = []
    for item in raw:
        if isinstance(item, dict):
            migrated.append(_migrate_scenario_dict(item))
        else:
            migrated.append(item)
    return migrated


def _migrate_scenario_dict(d: dict) -> dict:
    """单条场景 dict 迁移：按需把旧字段映射到新字段（浅拷贝，原 dict 不变）。"""
    out = dict(d)
    steps = out.get("steps")
    if isinstance(steps, list):
        new_steps = []
        for s in steps:
            if isinstance(s, dict) and s.get("action") == "run":
                # cli run 旧字段：value → command（仅当 command 缺失时迁移）
                if "value" in s and "command" not in s:
                    s = {**s, "command": s["value"]}
            new_steps.append(s)
        out["steps"] = new_steps
    assertions = out.get("assertions")
    if isinstance(assertions, list):
        new_asserts = []
        for a in assertions:
            # output_match 断言旧字段：value → expected（仅当 expected 缺失时迁移）
            if (
                isinstance(a, dict)
                and a.get("type") == "output_match"
                and "value" in a
                and "expected" not in a
            ):
                a = {**a, "expected": a["value"]}
            new_asserts.append(a)
        out["assertions"] = new_asserts
    return out


def _schema_version_notes(raw: list) -> list[str]:
    """未知 schema_version 条目的路由说明（D2：未知版本走迁移尝试+差异报错）。

    返回人类可读注释列表（供 load_scenarios 在校验报错时附加版本上下文）。
    """
    notes = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        ver = item.get("schema_version")
        if ver is None:
            continue
        if ver != SCHEMA_VERSION:
            sid = item.get("id") or f"[{i}]"
            notes.append(
                f"场景'{sid}'声明未知 schema_version={ver!r}，已按旧 schema "
                f"迁移尝试，仍失败则以下为字段差异清单"
            )
    return notes


def prepare_scenarios_for_write(raw: list) -> list:
    """写端归一化（frozen-scenario-schema-migration 2.1）。

    场景补齐写回 / ``_scenarios_full.json`` 备份更新等写盘路径共用：
    旧 schema 字段先迁移（与读侧同源，``migrate_scenario_schema``），
    再恒定写入 ``schema_version`` 标记——写盘文件始终为当前 schema
    形态，读侧版本路由直通，不残留「旧字段 + 新版本号」的不一致组合。

    evo-frozen-scenario-contract-versioning D1：额外恒定盖
    ``contract_version = CURRENT_CONTRACT_VERSION`` 戳（与 schema_version
    盖戳同处）——新建/冻结写回的文件天然是当前契约版本，下轮加载零迁移、
    不产生「新产场景被判旧契约」副作用。
    """
    return [
        {
            **d,
            "schema_version": SCHEMA_VERSION,
            CONTRACT_VERSION_FIELD: CURRENT_CONTRACT_VERSION,
        }
        if isinstance(d, dict)
        else d
        for d in migrate_scenario_schema(raw)
    ]


# ── 契约版本迁移（evo-frozen-scenario-contract-versioning D2）──────
# 冻结集按条目级 contract_version 路由到对应版本迁移函数；迁移是纯函数
# （不读写盘），base_url 由调用方（pipeline）注入——本文件属引擎层，
# MUST NOT import pm_engine。


def frozen_contract_version(scenarios: list) -> int:
    """冻结集条目级 ``contract_version`` 的最小值（缺失/非整型视为 1）。

    冻结集按统一生成批次落盘，条目版本不一致本身即异常——取 **min** 保守
    迁移（任一旧条目都走迁移，D1 口径）。空集返回 1（同缺失语义），由
    migrate_frozen_contract 以 ``all_scenarios_stale`` 处置。

    Args:
        scenarios: 场景 dict 列表（根节点 JSON 数组的原始条目）。

    Returns:
        整型版本号（>= 1）。
    """
    versions = []
    for item in scenarios:
        if not isinstance(item, dict):
            versions.append(1)
            continue
        v = item.get(CONTRACT_VERSION_FIELD)
        # type(...) is int（code-review item 380e0508406d）：bool 是 int 子类，
        # isinstance 会把 contract_version:true 当成 1 放行；精确类型拒绝 bool，
        # 与「非整型→1」的文档语义一致。
        versions.append(v if type(v) is int else 1)
    return min(versions) if versions else 1


def migrate_frozen_contract(
    scenarios: list,
    current_version: int = CURRENT_CONTRACT_VERSION,
    base_url: str = "",
) -> dict:
    """迁移冻结场景集到当前契约版本（纯函数，不读写盘）。

    以集内 ``contract_version`` 最小值（缺失/非整型=1，见
    ``frozen_contract_version``）为起点，经 ``_CONTRACT_MIGRATIONS``
    登记表逐段推进（支持跳版本：v1 直迁当前版 = 依次执行各段逻辑，
    前段产物直接喂后段）。未登记版本段 fail-closed——MUST NOT 猜测或
    跳过版本，返回 ``aborted='no_migration_path'`` 交回既有 corrupt →
    env_blocked 人工通道。集内版本号新于目标版本同理 fail-closed（降级
    部署 / 新 fenix 写出的文件）：旧规则集 MUST NOT 静默校验未知更新
    schema，同以 ``aborted='no_migration_path'`` 交人工通道（code-review
    item c542bb97d171）。

    Args:
        scenarios: 冻结场景 dict 列表（原始 JSON 数组，未过 load_scenarios）。
        current_version: 迁移目标版本（默认当前契约版本常量）。
        base_url: 引擎契约供给的被测实例 base_url（web 场景缺 navigate
            时合成 navigate 步骤的候选 URL；空串 = 无可用基址）。

    Returns:
        dict（D2.1）：
          - migrated: 已迁移（含版本戳）的场景 dict 列表（已剔除无法迁移项）
          - pending_replan: 无法机械迁移的场景 id 列表
          - aborted: 'all_scenarios_stale'（迁移后无任何合法场景 / 空集）
            | 'no_migration_path'（未登记版本段 / 集内版本新于目标版本）
            | ''（正常）
    """
    if not scenarios:
        return {"migrated": [], "pending_replan": [], "aborted": "all_scenarios_stale"}
    current = frozen_contract_version(scenarios)
    if current > current_version:
        # fail-closed：无「降级迁移」概念，不猜不静默放行（c542bb97d171）
        return {
            "migrated": [],
            "pending_replan": [],
            "aborted": "no_migration_path",
        }
    # 混合版本集防线（code-review item 74be485d930f）：min 路由只看集内最小
    # 值，集内同时存在旧条目与声明更新契约版本的条目时（新版 fenix 写出后
    # 又被旧版追加 / 冻结文件被部分改写），后者会被逐段迁移一路盖成目标版本
    # 戳、按旧规则静默校验采纳，旁路上方 min 判定的 fail-closed。版本不一致
    # 本身即异常——补 max 校验：任一条目声明新于目标版本即同款交人工通道
    # （「任一存疑即人工」口径），正常单版本路径行为不变。
    max_declared = max(
        item.get(CONTRACT_VERSION_FIELD)
        if isinstance(item, dict) and type(item.get(CONTRACT_VERSION_FIELD)) is int
        else 1
        for item in scenarios
    )
    if max_declared > current_version:
        # fail-closed：声明更新契约版本的条目不降级不静默放行（c542bb97d171）
        return {
            "migrated": [],
            "pending_replan": [],
            "aborted": "no_migration_path",
        }
    migrated = scenarios
    pending_replan: list = []
    while current < current_version:
        step = current + 1
        fn = _CONTRACT_MIGRATIONS.get(step)
        if fn is None:
            # fail-closed：未登记的版本段不猜不跳过，退回既有人工通道。
            # pending_replan 与 migrated 一致清空：迁移中途回滚 = 已迁移段
            # 产物一并丢弃，保留部分清单会与「全部回滚」事实不匹配
            return {
                "migrated": [],
                "pending_replan": [],
                "aborted": "no_migration_path",
            }
        migrated, pending = fn(migrated, base_url=base_url)
        pending_replan.extend(pending)
        current = step
    if not migrated:
        return {
            "migrated": [],
            "pending_replan": pending_replan,
            "aborted": "all_scenarios_stale",
        }
    return {"migrated": migrated, "pending_replan": pending_replan, "aborted": ""}


# ── 绝对 URL 形态判据（code-review item f4bbbcb7f6ab）─────────────
# 契约 v2「web 场景 MUST 含绝对 URL navigate」验收的核心判据，三处共用
# （_find_step_url_candidate 候选判定 / web navigate 验收 / api url 验收），
# 避免同一模式多处内联、后续调整时单处修改漂移。
_ABSOLUTE_URL_RE = r"^https?://\S+$"


def _find_step_url_candidate(steps) -> str:
    """场景内步骤的 ``url`` 字段候选（web 场景 api 形态残留/手写场景）。

    只取步骤顶层 ``url`` 字段、且匹配 ``^https?://\\S+$`` 的首个值——
    MUST NOT 从 steps 文本正则挖 URL：web 场景不含 ``run`` 步骤
    （``CLI_ACTIONS = {"run"}``，web 场景带 run 本身即校验错误），
    navigate 目标 URL 的权威载体是步骤 ``value`` 字段（serving.py:578-579）；
    ``click/type`` 的 ``target``/``value`` 是选择器与输入值，正则命中即为误取。
    """
    if not isinstance(steps, list):
        return ""
    for s in steps:
        if isinstance(s, dict):
            url = s.get("url")
            if isinstance(url, str) and re.match(_ABSOLUTE_URL_RE, url.strip()):
                # 返回 strip 后的值（code-review item 48320e6f6abb）：合成
                # navigate 步骤的 value 不携带首尾空白，避免运行期浏览器以
                # invalid URL 拒绝导航造成场景伪失败。
                return url.strip()
    return ""


def _migrate_contract_to_v2(scenarios: list, base_url: str = ""):
    """契约 1 → 2 迁移段：v2 = 「web 场景 MUST 含 navigate 步骤（绝对 URL）」。

    逐场景处理（migrate_frozen_contract D2.2）：
      1. 非 web 场景（kind ∈ {cli, api}）：无需 navigate 规则 → 原样保留，
         仅盖 contract_version = 2；
      2. web 场景且已有 navigate 步骤：仅盖戳（不重复插入、不改 navigate
         既有字段）；
      3. web 场景缺 navigate：候选 URL 取值顺序——场景内 step 的 ``url``
         字段（``^https?://\\S+$``）> 入参 ``base_url``；命中则合成
         ``{"action": "navigate", "value": <url>, "description": ...}`` 插入
         steps 首位（与「web 场景先打开页面再交互」语义一致）并盖戳；
         两者皆无 → 该场景移入 pending_replan、从迁移结果剔除。
      4. web 场景 ``steps`` 存在但非列表（dict/str/None）：场景文件已损坏
         → 原样透传（不盖版本戳、不合成 navigate），由读端
         ``validate_scenario_dicts`` 以字段级差异报 corrupt → env_blocked
         人工通道（code-review item 73e706677c11：旧实现非空 base_url 下
         静默丢弃原 steps 换成 [nav_step]，把本应报损坏的文件白洗成
         「合法单 navigate 场景」）。

    Returns:
        (migrated, pending)：同一版本段的无副作用迁移结果。
    """
    migrated: list = []
    pending: list = []
    for i, item in enumerate(scenarios):
        if not isinstance(item, dict):
            # 非 dict 条目无字段可操作：原样保留（过不了验收是它自身的
            # 问题，由读端校验在迁移后统一报 corrupt）
            migrated.append(item)
            continue
        sid = item.get("id") or f"[{i}]"
        kind = item.get("kind", "web")
        if kind != "web":
            migrated.append({**item, CONTRACT_VERSION_FIELD: 2})
            continue
        steps = item.get("steps")
        # 损坏 steps 不迁移（见 docstring 4，含缺失/显式 null）：与上方非 dict
        # 条目同款透传，交回读端校验失败通道。
        if not isinstance(steps, list):
            migrated.append(item)
            continue
        has_navigate = any(
            isinstance(s, dict) and s.get("action") == "navigate" for s in steps
        )
        if has_navigate:
            migrated.append({**item, CONTRACT_VERSION_FIELD: 2})
            continue
        url = _find_step_url_candidate(steps)
        if not url:
            url = base_url
        if not url:
            pending.append(sid)
            continue
        nav_step = {
            "action": "navigate",
            "value": url,
            "description": "契约 v2 自动补齐（navigate 绝对 URL）",
        }
        # steps 必为 list（上方 not isinstance(steps, list) 已透传 continue），
        # 无需再防御。
        new_steps = [nav_step] + steps
        migrated.append({**item, "steps": new_steps, CONTRACT_VERSION_FIELD: 2})
    return migrated, pending


# 版本登记表：{目标版本: 迁移函数}。迁移函数签名
# ``fn(scenarios: list, base_url: str) -> (migrated: list, pending: list)``，
# 只负责「N-1 → N」这一步，版本戳由该段自盖。未来新增 v3 只需追加一个
# 函数 + 一个登记项，并递增 CURRENT_CONTRACT_VERSION。
_CONTRACT_MIGRATIONS = {2: _migrate_contract_to_v2}


# ── 常量 ──────────────────────────────────────────────────────────
#
# 多形态验证（add-verify-multi-kind-runner）：场景 kind ∈ web/cli/api，
# 词表按 kind 组织为 per-kind 常量。**本文件是词表唯一权威源**——
# agents/planner-plan.md 只引用摘要并标注本文件为权威源（spec
# multi-kind-planning-guidance：防枚举双源漂移），词表扩展须先改这里。

VALID_KINDS = {"web", "cli", "api"}

# ── web 词表（存量内容，行为不变）────────────────────────────

WEB_ACTIONS = {
    "click",
    "type",
    "clear",
    "select",
    "scroll",
    "hover",
    "wait",
    "navigate",
    "drag",
    "contextmenu",
    "seed",
    "dialog",
    "mock_api",
}

WEB_ASSERTIONS = {
    # 第1层：元素存在性（确定性，0误判）
    "element_visible",
    "element_count",
    "element_not_exist",
    "element_focused",
    "element_enabled",
    # 第2层：交互可用性（确定性，0误判）
    "no_click_interception",
    "no_overlap",
    "in_viewport",
    "z_index_order",
    # 第3层：内容正确性（确定性，0误判）
    "text_match",
    "text_contains",
    "attribute_match",
    "no_console_error",
    "no_network_error",
    "no_auth_error",
    "dom_structure",
    # 第4层：布局完整性（启发式，需阈值）
    "no_overflow",
    "alignment",
}

WEB_ASSERTION_LAYERS = {
    "element_visible": 1,
    "element_count": 1,
    "element_not_exist": 1,
    "element_focused": 1,
    "element_enabled": 1,
    "no_click_interception": 2,
    "no_overlap": 2,
    "in_viewport": 2,
    "z_index_order": 2,
    "text_match": 3,
    "text_contains": 3,
    "attribute_match": 3,
    "no_console_error": 3,
    "no_network_error": 3,
    "no_auth_error": 3,
    "dom_structure": 3,
    "no_overflow": 4,
    "alignment": 4,
}

# ── cli 词表（spec multi-kind-scenario-model：CLI 词表与执行语义）────────
# 仅 run 一种步骤；6 种断言。无第 2 层（交互可用性是 DOM 概念）。

CLI_ACTIONS = {"run"}

CLI_ASSERTIONS = {
    # 第1层：存在性/状态（确定性，0误判）
    "exit_code",
    "file_exists",
    "dir_contains",
    # 第3层：内容正确性（确定性，0误判）
    "output_match",
    "file_content",
    "json_output",
}

CLI_ASSERTION_LAYERS = {
    "exit_code": 1,
    "file_exists": 1,
    "dir_contains": 1,
    "output_match": 3,
    "file_content": 3,
    "json_output": 3,
}

# ── api 词表（spec multi-kind-scenario-model：API 词表与响应捕获）──────
# http_request 通常一致；sse_connect 为流式（复杂度高时 fast-follow）。
# 无第 2 层。

API_ACTIONS = {"http_request", "sse_connect"}

API_ASSERTIONS = {
    # 第1层：存在性/状态（确定性，0误判）
    "status_code",
    "sse_event_count",
    # 第3层：内容正确性（确定性，0误判）
    "json_path",
    "response_header",
    "body_contains",
    "json_schema",
    "sse_event_matches",
    # 第4层：启发式阈值（失败=warning，需上下文判定）
    "latency_under",
}

API_ASSERTION_LAYERS = {
    "status_code": 1,
    "sse_event_count": 1,
    "json_path": 3,
    "response_header": 3,
    "body_contains": 3,
    "json_schema": 3,
    "sse_event_matches": 3,
    "latency_under": 4,
}

# ── 按 kind 词表索引（权威源）──────────────────────────────────

KIND_ACTIONS = {"web": WEB_ACTIONS, "cli": CLI_ACTIONS, "api": API_ACTIONS}
KIND_ASSERTIONS = {"web": WEB_ASSERTIONS, "cli": CLI_ASSERTIONS, "api": API_ASSERTIONS}
KIND_ASSERTION_LAYERS = {
    "web": WEB_ASSERTION_LAYERS,
    "cli": CLI_ASSERTION_LAYERS,
    "api": API_ASSERTION_LAYERS,
}

# ── 向后兼容别名（存量引用不变）────────────────────────────────
# web→VALID_ACTIONS：潜在别名与集合方法共存，避免库外引用断裂。

VALID_ACTIONS = WEB_ACTIONS

VALID_ASSERTIONS = WEB_ASSERTIONS

ASSERTION_LAYERS = {
    **WEB_ASSERTION_LAYERS,
    **CLI_ASSERTION_LAYERS,
    **API_ASSERTION_LAYERS,
}

# 需要选择器的断言类型（web 语义；CLI/API 断言不含 selector 概念）
# dom_structure 不在此列：执行器 _assert_dom_structure 只消费 parent/child
# 字段、从不读 selector，其必填规则由 ASSERTION_REQUIRED_FIELDS 单源表登记
# （code-review item b7b59e47a089）。
ASSERTIONS_REQUIRING_SELECTOR = VALID_ASSERTIONS - {
    "text_contains",
    "no_console_error",
    "no_network_error",
    "no_auth_error",
    "dom_structure",
}

# 需要target选择器的操作（web 语义；mock_api 的 target 为 URL 模式，seed 为 localStorage 键）
# wait 刻意不在此列：无 target 的 wait 是合法变体（browser.py 以 value 作为暂停毫秒数）
ACTIONS_REQUIRING_TARGET = {
    "click",
    "type",
    "clear",
    "select",
    "scroll",
    "drag",
    "hover",
    "contextmenu",
    "seed",
    "mock_api",
}


# ── 断言/操作必填字段单源表（evo-planner-scenario-schema-alignment D1）────
# 各类断言与操作的必填字段规则唯一权威表：写端校验（下方 _validate_cli /
# _validate_api 的必填字段分支）与生成侧 prompt 注入（prompt_builder
# _scenario_schema_section 运行时渲染）共用本表。扩展必填字段先改本表，
# 生成侧与校验侧同时生效——消除 2026-09-13 两批 100% 被写端剔除事故
# （agents/planner-plan.md 手写枚举与代码规则手工脱节）的根因。
#
# 条目结构:
#   key:     字段键。顶层键（如 "expected"），或 extra dict 键（前缀
#            "extra."，如 "extra.step" / "extra.path"）。
#   short:   字段短名（校验错误消息与 prompt 渲染共用）。
#   help:    人类可读补充说明（可选，无说明为空串）。
#   example: 合法 JSON 示例片段（prompt 样例渲染用，须为合法 JSON 值片段）。
#   mode:    判空语义（4.3 锁定既有校验细节，行为零变化）：
#              "post" = 缺失/空串/None 均非法（`not v`）；
#              "include_zero" = 仅缺失/空串/None 非法，0 类零值合法
#                （`v in ("", None)`，如 status_code 的 expected=0 是合法码）。
#
ASSERTION_REQUIRED_FIELDS: dict = {
    # ── cli 断言 ──
    "exit_code": (),
    "file_exists": (
        {
            "key": "extra.path",
            "short": "path",
            "help": "",
            "example": '"data/output.txt"',
            "mode": "post",
        },
    ),
    "dir_contains": (
        {"key": "extra.glob", "short": "glob", "help": "", "example": '"*.report"', "mode": "post"},
    ),
    "output_match": (
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"期望的输出内容"',
            # include_zero：数值 expected（如 0）按 str() 归一参与匹配，非缺参
            # （code-review item 01754605c87c）
            "mode": "include_zero",
        },
    ),
    "file_content": (
        {
            "key": "extra.path",
            "short": "path",
            "help": "",
            "example": '"data/output.txt"',
            "mode": "post",
        },
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"期望的文件内容"',
            # include_zero：数值 expected（如 0）按 str() 归一参与匹配，非缺参
            # （code-review item 01754605c87c）
            "mode": "include_zero",
        },
    ),
    "json_output": (
        {
            "key": "extra.step",
            "short": "step",
            "help": "指定解析哪个命名结果的 stdout",
            "example": '"<run 步骤的 as 命名>"',
            "mode": "post",
        },
        {
            "key": "extra.path",
            "short": "path",
            "help": "",
            "example": '"data.items.0.name"',
            "mode": "post",
        },
        # expected 必填（include_zero：数值 0 是合法 JSON 期望，与 status_code
        # 同款判空）——缺参时运行期 exact 的 None==None 会产出假通过
        # （code-review item baaae8c599ae）
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"期望的 JSON 值"',
            "mode": "include_zero",
        },
    ),
    # ── api 断言 ──
    "status_code": (
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": "200",
            "mode": "include_zero",
        },
    ),
    "sse_event_count": (
        {
            "key": "extra.min",
            "short": "min",
            "help": "下限",
            "example": "1",
            "mode": "include_zero",
        },
    ),
    "json_path": (
        {
            "key": "extra.path",
            "short": "path",
            "help": "",
            "example": '"data.items.0"',
            "mode": "post",
        },
        # expected 必填（code-review item 2cab94c9b2df）：缺 expected 的场景
        # 须在验收期与其他 api 断言同口径打回，而非耗一轮验证执行后靠运行期
        # fail-closed 才暴露。mode 用 include_zero——exact 比对下 0/False 是
        # 合法期望（如 data.code=0），不能按 post 误杀
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"data.items.0 的期望值"',
            "mode": "include_zero",
        },
    ),
    "response_header": (
        {
            "key": "extra.header",
            "short": "header",
            "help": "",
            "example": '"Content-Type"',
            "mode": "post",
        },
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"application/json"',
            "mode": "post",
        },
    ),
    "body_contains": (
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"期望响应体包含的文本"',
            "mode": "post",
        },
    ),
    "json_schema": (
        {
            "key": "extra.schema",
            "short": "schema",
            "help": "",
            "example": '{"type": "object"}',
            "mode": "post",
        },
    ),
    "sse_event_matches": (
        {
            "key": "expected",
            "short": "expected",
            "help": "",
            "example": '"匹配事件内容模式"',
            "mode": "post",
        },
    ),
    "latency_under": (
        {
            "key": "expected",
            "short": "expected",
            "help": "毫秒上限",
            "example": "500",
            "mode": "include_zero",
        },
    ),
    # ── web 断言 ──
    # parent/child 均无兜底：执行器以空选择器拼 locator 会在运行期以笼统的
    # 「断言执行异常」失败，故双必填（mode=post）；relation 有默认值
    # "contains"，不登记。
    "dom_structure": (
        {
            "key": "extra.parent",
            "short": "parent",
            "help": "父元素CSS选择器",
            "example": '"#list"',
            "mode": "post",
        },
        {
            "key": "extra.child",
            "short": "child",
            "help": "子元素CSS选择器",
            "example": '".item"',
            "mode": "post",
        },
    ),
}

# 操作必填字段单源表（键 = (kind, action)）。cli 仅 run；api 有
# http_request / sse_connect。web 操作必填字段（target 等）沿用
# ACTIONS_REQUIRING_TARGET 语义，不在此表重复。
ACTION_REQUIRED_FIELDS: dict = {
    ("cli", "run"): (
        {
            "key": "command",
            "short": "command",
            "help": "字符串=经 shell 执行；列表=argv 直接执行",
            "example": '"python3 script.py --flag"',
            "mode": "post",
        },
    ),
    ("api", "http_request"): (
        {"key": "method", "short": "method", "help": "", "example": '"GET"', "mode": "post"},
        {
            "key": "url",
            "short": "url",
            "help": "绝对 URL，origin 由框架改写",
            "example": '"https://<host>:<port>/api/data"',
            "mode": "post",
        },
    ),
    ("api", "sse_connect"): (
        {
            "key": "url",
            "short": "url",
            "help": "SSE 事件流绝对 URL",
            "example": '"https://<host>:<port>/events"',
            "mode": "post",
        },
    ),
}


def _field_missing(value, mode: str) -> bool:
    """必填字段判空语义（单源表锁定，4.3 等价性回归逐字段对齐）。"""
    if mode == "include_zero":
        return value in ("", None)
    return not value


def _assert_lookup_value(assertion, key: str):
    """断言对象按单源表字段键取值：'expected' → assertion.expected；
    'extra.<k>' → assertion.extra.get(k)。"""
    if key == "expected":
        return assertion.expected
    if key.startswith("extra."):
        return assertion.extra.get(key[len("extra.") :])
    return None


def _step_lookup_value(step, key: str):
    """步骤对象按单源表字段键取值（operation 字段均为顶层键）。"""
    return getattr(step, key, None)


def _append_required_field_errors(
    errors: list, scenario_id: str, prefix: str, specs: tuple, lookup
) -> list[str]:
    """按单源表校验必填字段并追加错误消息（消息文本由 short/help 派生，
    与单源表改前逐字一致——行为零变化，4.3）。"""
    for spec in specs:
        value = lookup(spec["key"])
        if _field_missing(value, spec.get("mode", "post")):
            msg = f"场景'{scenario_id}'{prefix}: {spec['short']}"
            if spec.get("help"):
                msg += f"（{spec['help']}）"
            errors.append(msg)
    return errors


# ── 数据类 ────────────────────────────────────────────────────────


def _str_field(d: dict, key: str) -> str:
    """步骤字符串字段读入归一（code-review item 057b6e7741a5）：场景 JSON
    写出数字等非字符串形态时归一为 str——原样透传会令词表校验期的
    ``(step.value or "").strip()`` / ``step.url.strip()`` 抛 AttributeError，
    被外层包成不含场景 id 的笼统「解析失败」。归一口径与 browser.py 运行层
    的 ``str(step.get("value") or "")``（code-review item 08ef327b2c7e）一致，
    不改变 wait 以毫秒数消费 value 等合法形态的运行语义；非法形态（如
    navigate 收到数字）交词表校验走形态报错的字段级路径，不静默吞。"""
    raw = d.get(key, "")
    return str(raw) if raw else ""


def _num_field(d: dict, key: str) -> Optional[float]:
    """步骤数值字段读入守卫（code-review item a0ba40d463e1）：timeout/duration
    写出 "30s" 等非数值串时 float() 强转抛 ValueError，被外层包成不含场景 id
    的笼统「解析失败」，与 _str_field 的字段级差异报错设计目标漂移。此处先做
    可转性守卫：非数值形态报字段级错误（字段名 + 原值，场景 id 由
    _parse_and_validate_scenario_dicts 的 except 分支补齐）；键缺失/null 返回
    None 作 has-value 标记（code-review item b52d4d781214：显式 0 须与缺省
    可区分才能穿过 to_dict 序列化，null 归一缺省与 depends_on 的 or [] 同款），
    数值 0 / 合法数字串照常 float() 归一，不静默吞。"""
    raw = d.get(key)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"步骤 {key} 须为数值（秒），收到 {raw!r}") from None


@dataclass
class TestStep:
    """单个测试操作步骤。

    Attributes:
        action: 操作类型（web: click/type/clear/select/scroll/wait/navigate/
            dialog…；cli: run；api: http_request/sse_connect）
        target: CSS选择器（优先data-testid，其次语义选择器）
        value: 输入值（type/select/navigate/dialog使用）
        screenshot: 操作后是否截图
        description: 人类可读描述
        dialog: 点击触发的浏览器对话框处理（accept | dismiss）
        status: mock 响应状态码（mock_api 分支）
        prompt_text: prompt 对话框 accept 时提交的文本
        # cli run 字段
        command: 命令（字符串=shell / 列表=argv），见 prepare 解析约定
        cwd: 相对验证树根的工作目录
        env: 环境变量（值支持 {env:VAR} 插值）
        stdin: 注入标准输入
        timeout: 超时秒数（CLI 超时强杀=步骤失败；API 请求超时）
        as_: 命名结果（CLI run 命名输出；api http_request 命名响应，
            sse_connect 命名事件流）
        # api http_request / sse_connect 字段
        method: HTTP 方法（GET/POST/…）
        url: 绝对 URL（origin 由框架改写，路径保留）
        headers: 请求头（值支持 {env:VAR} 插值）
        body: 请求体
        body_type: 请求体类型（json/text）
        duration: sse_connect 收集窗口秒数（最多收集 100 个事件，触顶即截断）
    """

    action: str
    target: str = ""
    value: str = ""
    screenshot: bool = False
    description: str = ""
    dialog: str = ""
    # admin 修 2026-08-29（族谱爆炸根因之一）：mock 响应状态码（409/500 分支
    # 场景必需）与 prompt 对话框提交文本。此前 TestStep 序列化丢弃这两个键，
    # 引擎侧 mock_api/click 拿不到，4xx/5xx 场景全部按 200 成功返回、prompt
    # 场景拿到空串 → 断言系统性伪失败。
    status: int = 0
    prompt_text: str = ""
    # 多形态验证字段（add-verify-multi-kind-runner）
    command: object = None  # str 或 list
    cwd: str = ""
    env: dict = field(default_factory=dict)
    stdin: str = ""
    # 缺省 None 而非 0.0（code-review item b52d4d781214）：0.0 缺省与显式 0
    # 不可区分，to_dict 真值过滤会把显式 0（立即超时）静默丢成键缺失，runner
    # 回退 60s/30s 缺省——「runner 尊重 0、序列化丢 0」的单点矛盾在此消除
    timeout: Optional[float] = None
    as_: str = ""
    method: str = ""
    url: str = ""
    headers: dict = field(default_factory=dict)
    body: str = ""
    body_type: str = ""
    duration: Optional[float] = None  # has-value 标记，口径同上方 timeout

    def to_dict(self) -> dict:
        d: dict = {"action": self.action}
        if self.target:
            d["target"] = self.target
        if self.value:
            d["value"] = self.value
        if self.screenshot:
            d["screenshot"] = True
        if self.description:
            d["description"] = self.description
        if self.dialog:
            d["dialog"] = self.dialog
        if self.status:
            d["status"] = self.status
        if self.prompt_text:
            d["prompt_text"] = self.prompt_text
        if self.command not in (None, ""):
            d["command"] = self.command
        if self.cwd:
            d["cwd"] = self.cwd
        if self.env:
            d["env"] = self.env
        if self.stdin:
            d["stdin"] = self.stdin
        # 非 None 即写（code-review item b52d4d781214）：真值过滤会把显式 0
        # 丢成键缺失，cli/api runner「缺省仅在键缺失时生效」的立即超时语义
        # 被静默改写成 60s/30s 缺省
        if self.timeout is not None:
            d["timeout"] = self.timeout
        if self.as_:
            d["as"] = self.as_
        if self.method:
            d["method"] = self.method
        if self.url:
            d["url"] = self.url
        if self.headers:
            d["headers"] = self.headers
        if self.body:
            d["body"] = self.body
        if self.body_type:
            d["body_type"] = self.body_type
        # 非 None 即写（口径同上方 timeout，code-review item b52d4d781214）
        if self.duration is not None:
            d["duration"] = self.duration
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TestStep":
        return cls(
            action=d["action"],
            # target/value/url 参与词表校验（必填判空、.strip() 形态检查），
            # 非字符串形态经 _str_field 归一，不制造校验期 AttributeError
            target=_str_field(d, "target"),
            value=_str_field(d, "value"),
            screenshot=d.get("screenshot", False),
            description=d.get("description", ""),
            dialog=d.get("dialog", ""),
            # [fenix-ignore:56c49c2fafae] 唯一消费点 browser.py mock_api 已对 status 做 int() 强转+非法值结构化失败（不静默回退 200），数字字符串运行期可正常 mock，所述伪失败不存在；按建议回退 0 反而复活已修复的「4xx mock 静默变 200」缺陷
            status=d.get("status", 0) or 0,
            prompt_text=d.get("prompt_text", "") or "",
            command=d.get("command"),
            cwd=d.get("cwd", ""),
            env=d.get("env") or {},
            stdin=d.get("stdin", ""),
            # timeout/duration 可转性守卫（_num_field）：非数值串报字段级错误
            timeout=_num_field(d, "timeout"),
            as_=d.get("as", ""),
            method=d.get("method", ""),
            url=_str_field(d, "url"),
            headers=d.get("headers") or {},
            body=d.get("body", ""),
            body_type=d.get("body_type", ""),
            duration=_num_field(d, "duration"),
        )


@dataclass
class Assertion:
    """单个断言定义。

    Attributes:
        type: 断言类型（对应 assertions.py 中的方法名）
        selector: 目标元素CSS选择器
        label: 人类可读标签（用于报告）
        expected: 期望值（text_match/attribute_match等使用）
        threshold: 阈值（overlap检测的容差等）
        layer: 断言层级（1-4），自动从 type 推导
        extra: 额外参数（如 compare_selector / operator / axis 等）
    """

    type: str
    selector: str = ""
    label: str = ""
    # expected 的「未设置」哨兵是 None 而非空串：空串是 json_path / text_match
    # 等断言的合法期望值（如「detail 为空串」）。曾以 str = "" 兼作哨兵，to_dict
    # 按 `!= ""` 丢键，合法空串期望经 from_dict→to_dict 往返后被丢、运行时按
    # None 比较——合法断言确定性误判失败，且路径缺失时 None==None 误判通过
    # （add-impl-selfcheck-model-probe 验证修复轮 BUG-01）。
    expected: Any = None
    threshold: float = 0.2
    extra: dict = field(default_factory=dict)

    @property
    def layer(self) -> int:
        return ASSERTION_LAYERS.get(self.type, 0)

    def to_dict(self) -> dict:
        # extra 不得覆盖规范键（code-review item 7743535e64de）：旧实现
        # `d.update(self.extra)` 在写入 type/selector/expected 之后执行，extra 里
        # 含同名键会覆盖基础字段；而 from_dict 侧以 known_keys 剔除同名键，往返
        # 不对称。改为 extra 中与规范键冲突的条目一律忽略（规范字段优先）。
        d: dict = {"type": self.type}
        if self.selector:
            d["selector"] = self.selector
        if self.label:
            d["label"] = self.label
        if self.expected is not None:
            d["expected"] = self.expected
        if self.threshold != 0.2:
            d["threshold"] = self.threshold
        _known = {"type", "selector", "label", "expected", "threshold"}
        for k, v in (self.extra or {}).items():
            if k not in _known:
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Assertion":
        known_keys = {"type", "selector", "label", "expected", "threshold"}
        extra = {k: v for k, v in d.items() if k not in known_keys}
        return cls(
            type=d["type"],
            selector=d.get("selector", ""),
            label=d.get("label", ""),
            expected=d.get("expected"),
            threshold=d.get("threshold", 0.2),
            extra=extra,
        )


@dataclass
class TestScenario:
    """完整的测试场景。

    Attributes:
        id: 唯一标识（kebab-case）
        description: 人类可读中文描述
        steps: 操作步骤列表
        assertions: 断言列表
        visual_baseline: 视觉对比基线名称（可选，用于截图SSIM对比）
        depends_on: 依赖的场景ID列表（这些场景必须先执行完成）
        external_net_errors_ok: 场景是否允许「外部 API 网络类控制台错误」。
            涉及外部 API（如 timeapi.io / open-meteo）真实请求的场景置 True，
            no_console_error 断言将过滤 net::ERR_ 等网络层错误（视为环境因素），
            其余控制台错误（含签名/认证类）仍严格失败。
    """

    id: str
    description: str = ""
    steps: list[TestStep] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    visual_baseline: str = ""
    depends_on: list[str] = field(default_factory=list)
    external_net_errors_ok: bool = False
    # 场景 kind（web/cli/api，缺省 web）。kind 是场景级字段：混合 spec =
    # 场景集混排 + depends_on 跨 kind 编排；单场景内不混排步骤类型。
    kind: str = "web"
    # 场景级视口（admin 修 2026-09-07，fix-mobile-touch-disclosure 验证阻塞根因）。
    # 此前本模型无此字段，场景声明的 {"width":390,"height":844} 被 from_dict
    # 静默丢弃、browser.new_context 硬编码 1280×800 桌面视口——useIsMobile
    # 门控的移动端条件渲染（渐进披露等）在验证中永不出现，断言必然超时的
    # 伪失败被误判为产品缺陷。None = 沿用桌面缺省，存量场景行为不变。
    viewport: Optional[dict] = None

    def validate(self) -> list[str]:
        """验证场景定义的合法性，返回错误列表。

        按场景 kind 校验：web 用 web 词表（navigate 硬要求等存量规则），
        cli/api 用各自词表与必填字段。空列表表示场景定义完全合法。
        词表校验的权威源是本模块 per-kind 常量（KIND_ACTIONS /
        KIND_ASSERTIONS），planner 提示词只做摘要并标注此处为权威源。
        """
        return validate_scenario(self)

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "description": self.description,
            "kind": self.kind,
            # frozen-scenario-schema-migration D2：写入端恒定写 schema 版本标记，
            # 读侧按版本路由迁移（无版本=旧 schema 走迁移，当前版本直通）。
            "schema_version": SCHEMA_VERSION,
            # evo-frozen-scenario-contract-versioning：contract_version 与
            # schema_version 两戳一起盖（同 prepare_scenarios_for_write 口径）。
            # 此前本方法漏盖 contract_version，经 to_dict() 序列化的写路径
            # （save_scenarios 等）产出的文件被 frozen_contract_version 读成
            # v1，下次加载不必要触发契约迁移（code-review item 8e30615ecdd4）。
            CONTRACT_VERSION_FIELD: CURRENT_CONTRACT_VERSION,
            "steps": [s.to_dict() for s in self.steps],
            "assertions": [a.to_dict() for a in self.assertions],
        }
        if self.visual_baseline:
            d["visual_baseline"] = self.visual_baseline
        if self.depends_on:
            d["depends_on"] = self.depends_on
        if self.external_net_errors_ok:
            d["external_net_errors_ok"] = True
        if self.viewport:
            d["viewport"] = self.viewport
        return d

    @staticmethod
    def _parse_viewport(raw) -> Optional[dict]:
        """顶层 viewport 字段解析：仅接受 {width:int, height:int} 正值，
        其余形态一律忽略（回退桌面缺省），不制造新的验收失败模式。"""
        if not isinstance(raw, dict):
            return None
        # 精确 int（code-review item 380e0508406d）：bool 是 int 子类，
        # isinstance + int(...) 强转会让 {'width': true, 'height': true}
        # 静默变成 1×1 viewport 而非回退桌面缺省；type(...) is int 拒绝 bool。
        if type(raw.get("width")) is not int or type(raw.get("height")) is not int:
            return None
        w, h = raw["width"], raw["height"]
        if w <= 0 or h <= 0 or w > 3840 or h > 2160:
            return None
        return {"width": w, "height": h}

    @classmethod
    def from_dict(cls, d: dict) -> "TestScenario":
        # 损坏 steps 归一（code-review item 1bc2dac98c6e）：steps 存在但非列表
        # （dict/str/None）时，推导式对 dict 键/str 字符迭代会让 TestStep.from_dict
        # 直接抛 TypeError，被外层包成不含场景 id 的笼统「解析失败」，与契约
        # 迁移 docstring「由读端以字段级差异报 corrupt」的承诺漂移。置空交
        # 词表校验报字段级错误（web 缺 navigate / cli/api steps 不得为空），
        # 错误带场景 id 定位。
        steps = d.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        # 损坏 assertions 归一（code-review item 26e726d6b099）：口径对齐上方
        # steps——非列表形态（null/dict/标量）原样迭代会让 None 抛 TypeError、
        # dict 迭代出键后喂给 Assertion.from_dict 抛错，均被外层包成笼统
        # 「[i]解析失败」，与 steps/depends_on 的显式归一漂移。置空交词表
        # 校验断言循环逐条走字段级报错路径，错误带场景 id 定位。
        assertions = d.get("assertions", [])
        if not isinstance(assertions, list):
            assertions = []
        return cls(
            id=d["id"],
            description=d.get("description", ""),
            steps=[TestStep.from_dict(s) for s in steps],
            assertions=[Assertion.from_dict(a) for a in assertions],
            visual_baseline=d.get("visual_baseline", ""),
            # 显式 null 归一空列表（与 env/headers 的 or {} 同款，code-review
            # item 301443cb108c）：None 会存活到 engine 编排期迭代才 TypeError。
            depends_on=d.get("depends_on") or [],
            # 严格 bool 归一（口径对齐 _parse_viewport / depends_on 归一）：
            # 真值字符串（"false"/"0" 等非空串）按 d.get 原样放行会意外启用
            # 外部网络错误豁免、漏报真实故障，故仅接受布尔 True
            external_net_errors_ok=(
                d.get("external_net_errors_ok") is True
            ),
            kind=d.get("kind", "web"),
            viewport=cls._parse_viewport(d.get("viewport")),
        )


# ── per-kind 场景验收校验 ─────────────────────────────────────────
# 各 Runner 的 validate 委托本函数（WebRunner/CliRunner/ApiRunner 一致入口，
# 词表权威源唯一）。验收错误消息带「支持: …」词表速查（spec
# multi-kind-planning-guidance 打回路径：plan 侧无需查询源码即可修正）。


def _supported_actions(kind: str) -> str:
    return ", ".join(sorted(KIND_ACTIONS.get(kind, set())))


def _supported_assertions(kind: str) -> str:
    return ", ".join(sorted(KIND_ASSERTIONS.get(kind, set())))


def _validate_web(scenario: TestScenario) -> list[str]:
    """web 词表校验（存量规则，navigate 硬要求 + target/selector 必填）。"""
    errors: list[str] = []

    for i, step in enumerate(scenario.steps):
        if step.action not in WEB_ACTIONS:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 未知操作 '{step.action}'，"
                f"支持: {_supported_actions('web')}"
            )
        if step.action in ACTIONS_REQUIRING_TARGET and not step.target:
            errors.append(f"场景'{scenario.id}'步骤{i}: 操作 '{step.action}' 需要 target 选择器")

    for i, a in enumerate(scenario.assertions):
        if a.type not in WEB_ASSERTIONS:
            errors.append(
                f"场景'{scenario.id}'断言{i}: 未知类型 '{a.type}'，"
                f"支持: {_supported_assertions('web')}"
            )
        if a.type in ASSERTIONS_REQUIRING_SELECTOR and not a.selector:
            errors.append(f"场景'{scenario.id}'断言{i}: 类型 '{a.type}' 需要 selector")
        # web 断言必填字段与 cli/api 同源：查 ASSERTION_REQUIRED_FIELDS 单源表
        # （dom_structure 的 parent/child 必填，code-review item b7b59e47a089）。
        specs = ASSERTION_REQUIRED_FIELDS.get(a.type, ())
        _append_required_field_errors(
            errors,
            scenario.id,
            f"断言{i}: {a.type} 需要",
            specs,
            lambda key, a=a: _assert_lookup_value(a, key),
        )

    # navigate URL 验收（2026-08-28：相对路径导致浏览器白屏、整轮断言全灭）
    nav_steps = [s for s in scenario.steps if s.action == "navigate"]
    if not nav_steps:
        errors.append(
            f"场景'{scenario.id}'缺少 navigate 步骤" f"（web 场景必须以绝对 URL 打开被测页面）"
        )
    for i, step in enumerate(scenario.steps):
        if step.action == "navigate" and not re.match(
            _ABSOLUTE_URL_RE, (step.value or "").strip()
        ):
            errors.append(
                f"场景'{scenario.id}'步骤{i}: navigate URL 必须为绝对地址"
                f"（http://或https://开头，含主机与端口），收到 '{step.value}'"
                f"——相对路径会被验收拒绝并退回 plan 阶段"
            )
    return errors


def _validate_typed(scenario: TestScenario, kind: str) -> list[str]:
    """cli/api 共用的 typed 词表校验（code-review item 2d3c0e0c4387：
    原 _validate_cli/_validate_api 逐行副本合并为按 kind 参数化的单一实现）。

    步骤循环：未知操作报错（附 kind 词表速查），已知操作查单源表
    ACTION_REQUIRED_FIELDS 的 (kind, action) 键补必填字段错误；断言循环
    同构，查 ASSERTION_REQUIRED_FIELDS。
    """
    errors: list[str] = []

    # 空 steps 词表拦截（code-review item fac3eaecdde6 / 890e16b33275）：web
    # 场景有 navigate 硬要求兜住空步骤，cli/api 无对应约束——steps=[] 且
    # assertions=[] 的场景会经 determine_scenario_status([], []) 空转判
    # pass，零证据计入整轮裁决。验收期打回，不留运行期假通过通道。
    if not scenario.steps:
        errors.append(
            f"场景'{scenario.id}'steps 不得为空（{kind} 场景至少需要一个步骤）"
        )

    for i, step in enumerate(scenario.steps):
        if step.action not in KIND_ACTIONS.get(kind, set()):
            errors.append(
                f"场景'{scenario.id}'步骤{i}: 未知操作 '{step.action}'，"
                f"支持: {_supported_actions(kind)}"
            )
            continue
        specs = ACTION_REQUIRED_FIELDS.get((kind, step.action), ())
        _append_required_field_errors(
            errors, scenario.id, f"步骤{i}", specs, lambda key, s=step: _step_lookup_value(s, key)
        )
        # cli run command 形态验收（code-review item 071b40c06e33）：必填检查
        # 仅判空（_field_missing 的 not value），dict/数字等真值非法形态可通过
        # 验收，运行期 cli_runner 以 use_shell = not isinstance(cmd, list) 把
        # 非 list 一律当 shell 字符串消费才失败，场景定义错误拖到运行期、归因
        # 质量差。缺失/空值已由必填检查报告，此处仅拦形态非法（help 惯例：
        # 字符串=经 shell 执行；列表=argv 直接执行）。
        if (
            kind == "cli"
            and step.action == "run"
            and step.command
            and not isinstance(step.command, (str, list))
        ):
            errors.append(
                f"场景'{scenario.id}'步骤{i}: command 须为字符串（经 shell 执行）"
                f"或列表（argv 直接执行），收到 {type(step.command).__name__}"
            )
        # api 步骤 url 绝对地址验收（code-review item cf81feeaec37）：对齐
        # web navigate 同款 ^https?:// 校验——rewrite_origin 对无 scheme/netloc
        # 的 URL 原样透传，相对 URL 会拖到运行期 httpx 请求时才失败。缺失
        # 已由必填检查报告，此处仅拦形态非法。
        if (
            kind == "api"
            and step.action in ("http_request", "sse_connect")
            and step.url
            and not re.match(_ABSOLUTE_URL_RE, step.url.strip())
        ):
            errors.append(
                f"场景'{scenario.id}'步骤{i}: url 必须为绝对地址"
                f"（http://或https://开头，含主机与端口），收到 '{step.url}'"
                f"——相对路径会被验收拒绝并退回 plan 阶段"
            )
        # 负数 timeout 词表拦截（code-review item bf2ffeded38c）：负值能过
        # from_dict 的 float() 归一，放行到执行期会被 wait_for 立即判超时、
        # 把场景定义错误误报成 hang 缺陷，在校验层提前拦下
        if step.timeout and step.timeout < 0:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: timeout 须为正数（秒），收到 {step.timeout}"
            )
        # sse_connect duration 负值同款拦截（code-review item c0d449652c16）：
        # 负窗口 deadline 落在过去、首行即 break，场景以 0 事件失败收场，报错
        # 只剩事件数下限不满足，judge 归因不到「窗口秒数为负」的配置根因。
        # 口径对齐上方 timeout 分支：仅拦严格负值，不拦 0。
        if step.duration and step.duration < 0:
            errors.append(
                f"场景'{scenario.id}'步骤{i}: duration 须为正数（秒），收到 {step.duration}"
            )

    for i, a in enumerate(scenario.assertions):
        if a.type not in KIND_ASSERTIONS.get(kind, set()):
            errors.append(
                f"场景'{scenario.id}'断言{i}: 未知类型 '{a.type}'，"
                f"支持: {_supported_assertions(kind)}"
            )
            continue
        specs = ASSERTION_REQUIRED_FIELDS.get(a.type, ())
        _append_required_field_errors(
            errors,
            scenario.id,
            f"断言{i}: {a.type} 需要",
            specs,
            lambda key, a=a: _assert_lookup_value(a, key),
        )
    return errors


def _validate_cli(scenario: TestScenario) -> list[str]:
    """cli 词表校验：仅 run 步骤 + CLI 断言必填字段。

    run 步骤必填 command（字符串=shell/列表=argv）；cwd 相对验证树根、
    env 值支持 {env:VAR} 插值、stdin/timeout/as 可选。断言必填字段见
    spec multi-kind-scenario-model「CLI 词表与执行语义」；必填字段规则
    单源表 ASSERTION_REQUIRED_FIELDS / ACTION_REQUIRED_FIELDS（1.2 改读
    单源，行为零变化）。
    """
    return _validate_typed(scenario, "cli")


def _validate_api(scenario: TestScenario) -> list[str]:
    """api 词表校验：http_request/sse_connect 步骤 + API 断言必填字段。

    http_request 必填 method/url（绝对 URL，origin 由框架改写）；断言必填
    字段见 spec multi-kind-scenario-model「API 词表与响应捕获」。必填字段
    规则单源表 ASSERTION_REQUIRED_FIELDS / ACTION_REQUIRED_FIELDS
    （1.2 改读单源，行为零变化）。
    """
    return _validate_typed(scenario, "api")


def validate_scenario(scenario: TestScenario) -> list[str]:
    """按场景 kind 分派 per-kind 词表校验（Runner.validate 与
    TestScenario.validate 的公共入口，词表权威源唯一）。"""
    errors: list[str] = []
    if not scenario.id or not scenario.id.strip():
        errors.append("场景ID不能为空")
    # depends_on 列表类型验收（code-review item 301443cb108c）：非列表形态
    # （str/dict）会被逐字符/逐键迭代，原样放行要拖到 engine 编排期才暴露。
    if scenario.depends_on is not None and not isinstance(scenario.depends_on, list):
        errors.append(
            f"场景'{scenario.id}': depends_on 必须为场景ID列表，"
            f"收到 {type(scenario.depends_on).__name__}"
        )
    elif isinstance(scenario.depends_on, list):
        # depends_on 条目形态验收（code-review item 10bc32b28d05）：条目为
        # dict/list 等 unhashable 形态（冻结文件被手工修坏）时，engine 悬空
        # 依赖检查的 dep in seen_ids 对 set 求成员先抛 TypeError，穿出 run()
        # 验收门、不落「场景验收失败」报告，与 kind/steps 的手坏防线口径漂移。
        # 逐条校验并附条目下标，验收期打回。
        for i, dep in enumerate(scenario.depends_on):
            if not isinstance(dep, str):
                errors.append(
                    f"场景'{scenario.id}': depends_on[{i}] 必须为场景ID字符串，"
                    f"收到 {type(dep).__name__}"
                )
    # kind 形态守卫（code-review item c74c42575c7c）：kind 为 dict/list 等不
    # 可哈希形态（冻结文件被手工修坏）时，对 set 求成员先抛 TypeError，被
    # 外层包成不含场景 id 的「解析失败」，拿不到「未知 kind」字段级定位。
    # 非 str 一律走同款「未知 kind」报错（消息保留原值），字符串路径不变。
    if not isinstance(scenario.kind, str) or scenario.kind not in VALID_KINDS:
        errors.append(
            f"场景'{scenario.id}'未知 kind '{scenario.kind}'，"
            f"支持: {', '.join(sorted(VALID_KINDS))}"
        )
        return errors
    if scenario.kind == "web":
        errors.extend(_validate_web(scenario))
    elif scenario.kind == "cli":
        errors.extend(_validate_cli(scenario))
    elif scenario.kind == "api":
        errors.extend(_validate_api(scenario))
    return errors


# ── 场景加载 ──────────────────────────────────────────────────────


def validate_scenario_dicts(raw: list) -> list[str]:
    """结构校验场景 dict 列表（scenario-write-schema-gate 单一来源）。

    读端 ``load_scenarios`` 与全部写端（planner 产物收编、补齐写回、
    ``save_scenario_set``、``_scenarios_full.json`` 备份更新）共用同一
    校验：输入 dict 列表，逐条经 ``TestScenario.from_dict`` +
    ``validate()`` 校验，返回逐条错误清单。空列表表示全部合法；本函数
    不抛异常，拒绝/剔除策略由调用方决定。

    frozen-scenario-schema-migration D1：校验前先做读侧旧 schema 迁移
    （value→command / value→expected，仅目标字段缺失时生效），与
    ``load_scenarios`` 版本路由后的形态一致——迁移零干扰新 schema 路径。

    Args:
        raw: 场景 dict 列表。

    Returns:
        错误清单（人类可读，含场景 id / 下标定位）；全部合法时为空列表。
    """
    if not isinstance(raw, list):
        return [f"场景数据格式错误: 期望数组，实际为 {type(raw).__name__}"]
    # 旧 schema 前置迁移（读侧同样靠本函数做最终校验，迁移须先于校验执行；
    # 迁移为幂等操作，load_scenarios 已迁移时此处零干扰）
    raw = migrate_scenario_schema(raw)
    _, all_errors = _parse_and_validate_scenario_dicts(raw)
    return all_errors


def _parse_and_validate_scenario_dicts(raw: list) -> tuple:
    """逐条 from_dict+validate（validate_scenario_dicts / load_scenarios 共用）。

    返回 (成功且通过校验的场景列表, 错误清单)。同一 JSON 只解析一遍：
    validate_scenario_dicts 只消费错误清单；load_scenarios 在错误为空时
    直接复用场景列表，避免二次 from_dict（code-review 91d7507f957d）。
    """
    scenarios: list = []
    all_errors: list[str] = []
    for i, item in enumerate(raw):
        try:
            scenario = TestScenario.from_dict(item)
            errors = scenario.validate()
            if errors:
                all_errors.extend(errors)
            else:
                scenarios.append(scenario)
        except Exception as e:
            # 场景 id 定位（code-review item a0ba40d463e1）：解析期异常（如
            # _num_field 字段级报错）本不含场景 id，从原始条目补齐，admin 依
            # 差异清单精准修冻结文件。
            sid = item.get("id") if isinstance(item, dict) else ""
            prefix = f"场景'{sid}'" if sid else f"场景[{i}]"
            all_errors.append(f"{prefix}[{i}]解析失败: {e}")
    return scenarios, all_errors


def load_scenarios(filepath) -> list[TestScenario]:
    """从JSON文件加载场景列表，并校验合法性。

    Args:
        filepath: test_scenarios.json 的路径（Path 对象或字符串）

    Returns:
        TestScenario 列表

    Raises:
        ValueError: 场景文件格式错误或场景定义不合法
    """
    import json
    from pathlib import Path

    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"场景文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list):
        raise ValueError(f"场景文件格式错误: 期望JSON数组，实际为 {type(raw).__name__}")

    # ── schema 版本路由迁移（frozen-scenario-schema-migration D2）──
    # 无版本字段 → 旧 schema 走迁移（value→command / value→expected）；
    # 当前版本 → 迁移天然零干扰（目标字段已存在，直通语义）；
    # 未知版本 → 仍走迁移尝试，校验失败时附版本上下文与字段差异清单。
    version_notes = _schema_version_notes(raw)
    raw = migrate_scenario_schema(raw)

    # 读端校验与写端 schema 门同源（fix-frozen-scenario-orphan-reservoir D1）：
    # 校验逻辑提取为 validate_scenario_dicts 独立可调用（行为零变化，
    # 报错格式「场景文件包含 N 个错误」不变）；此处走共用解析 helper，
    # 校验通过后直接复用解析结果，免二次 from_dict。
    parsed, all_errors = _parse_and_validate_scenario_dicts(raw)
    if all_errors:
        # 迁移后仍失败 → 报字段级差异清单（场景 id/下标/缺失字段），不吞为
        # 笼统 corrupt：admin 处置（frozen-scenario-schema-migration 1.2）
        # 可凭差异清单精准修复冻结文件。
        detail = "\n".join(f"  - {e}" for e in all_errors)
        if version_notes:
            detail += "\n" + "\n".join(f"  # {n}" for n in version_notes)
        raise ValueError(f"场景文件包含 {len(all_errors)} 个错误:\n" + detail)

    return parsed


def save_scenarios(scenarios: list[TestScenario], filepath) -> None:
    """将场景列表序列化为JSON文件。

    原子写（对齐 settings_routes._atomic_write_text 惯例）：同目录临时
    文件 + ``os.replace``，进程写入中途被杀不会在目标路径留下截断的
    场景 JSON。

    Args:
        scenarios: TestScenario 列表
        filepath: 目标文件路径
    """
    import json
    import os
    import tempfile
    from pathlib import Path

    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [s.to_dict() for s in scenarios]
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
