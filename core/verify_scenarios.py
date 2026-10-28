"""
verify_scenarios.py — 验证场景集持久化与受控增量（add-verify-scenario-freeze）。

把「验证场景集（scenario_id 列表）」跨轮稳定下来：

  - 首轮验证裁决产出场景集时，持久化到
    ``.fenix/verify-progress/<spec>/scenarios.json``；已有该文件时 MUST NOT
    无条件覆盖（design D1：走 diff 流程）。
  - 修复轮验证默认复用持久化集；仅当修复段（tasks.md「## 验证修复」）声明了
    新增交付范围时，planner 才允许为**新增范围**追加场景（spec 需求
    ``verify-scenario-freeze``）。
  - planner 产出与持久化集 diff：只增 scenario_id 时合并写回（记录轮次）；
    删减既有场景 MUST 提供理由，无理由的缺场景按 planner 输出不完整处理——
    以持久化集补齐缺失场景后继续（不中断验证）。

确定性与纯 Python（design D3）：planner 无法通过输出文本绕过——diff 校验读取
planner 输出 JSON + scenarios.json + 修复段文本，写回 scenarios.json 只在校验
通过后发生。

scenarios.json 结构（含来源轮次，便于增量审计）::

    {
      "spec": "<spec>",
      "round": <int>,                       # 当前场景集稳定时的验证轮次
      "display_declarations": ["btn-x"],    # 交互契约纯展示声明（add-interaction-contract）
      "scenarios": [
        {"id": "sc-1", "description": "...", "added_in_round": 1,
         "covers": ["dark-Card--link"]},    # 交互契约：场景覆盖的可交互元素
        ...
      ]
    }
"""

import errno
import fcntl
import json
import logging
import re
import time
from pathlib import Path
from typing import Optional

from core.fs_utils import atomic_write_text

# 可传播到 fenixd 已挂载 handler 的结构化日志器（fix-robustness-edge-cases 3.1：
# 收敛旁路裸 getLogger("pm_engine")，保证 WARNING 落入 fenixd.log）
_logger = logging.getLogger("fenixd.verify_scenarios")

# tasks.md 修复段标题正则（code-review 18825900bb22：此处为唯一权威定义，
# pm_engine._VERIFY_FIX_SECTION_RE 自本模块导入——修复段标题文案调整只改
# 这一处，防两份同源拷贝各自漂移致 is_repair_round 与 pm_engine 侧判定分叉）。
VERIFY_FIX_SECTION_RE = re.compile(r"^## 验证修复\b.*$", re.MULTILINE)

# 持久化集条目 kind 合法值白名单（code-review c2c987e7bf43：本模块加载净化/
# 写端校验/diff 侧 kind 刷新共四处判定收口单一来源）。与 core.verify_engine.
# scenarios 的 VALID_KINDS 同源；不直接导入是因 ``from core.verify_engine.
# scenarios import ...`` 会先执行包 __init__、连带拉起 VerifyEngine——core 内
# 对 verify_engine 一律函数内懒导入，两侧集合调整时须同步。
VALID_KINDS = ("web", "cli", "api")

# 修复段中声明「新增交付范围」的匹配：带「新增」字样且非纯修复的条目。
# 设计 D2：仅当修复段声明了新增交付时，planner 才允许为该范围追加场景。
# 动词-名词衔接窗口限定同条款（不含句读/换行，cec71a4419ae）：放任跨句读
# 会让「上一轮无新增，本次新增 X 场景」中前半句的否定动词配上后半句的
# 名词成一条匹配，否定排除随之吞掉真实声明。
_NEW_DELIVERY_RE = re.compile(
    r"(新增|追加|增加)[^，。；\n]{0,12}?(交付|范围|功能|场景|支持|能力|特性|页面|模块)",
    re.MULTILINE,
)

# 修复语境短语（bcb05f957b2d）：动词后（允许「了」等少量衔接字）出现
# 「对/针对/对于 … 的修复」＝对既有场景的修复而非新增交付声明；限定同
# 条款内（不含句读/换行）防跨句误排除，衔接字窗口收紧到 4 字防把真新增
# 交付条目也误排除。
_REPAIR_PHRASE_RE = re.compile(
    r"[^，。；\n]{0,4}(?:对|针对|对于)[^，。；\n]{0,60}的修复"
)

# 否定语境排除（code-review cec71a4419ae）：命中动词前（同条款内回看，
# 不含句读/换行——「上一轮无新增，本次新增 X 场景」的后半句真实声明不受
# 前半句否定影响）紧邻否定前缀＝否定表述（「未新增场景」「无新增交付
# 范围」「不增加功能」），按非声明处理，不得误开修复轮扩容闸门。多字
# 否定词须排在单字前（正则交替从左到右，否则「不再」会被「不」截断、
# 尾锚 ``$`` 失配漏判）。已知限制（code-review e7c716ff3f6f，设计取舍非
# 缺陷）：``$`` 尾锚要求否定词紧邻动词，被衔接字隔开时不识别（如「没有
# 为 X 新增场景」会被计为新增交付声明）；条款分隔符不含顿号「、」，顿号
# 分句场景下否定窗口会跨子句。维持紧邻语义——开放衔接字窗口须与多字否
# 定词排序约束并存、易把真实声明也误排除，此处仅留痕供后续权衡。
_NEGATED_DELIVERY_RE = re.compile(
    r"(?:没有|不再|暂不|不曾|并未|并不|并非|无需|无须|不需|未|无|不)$"
)


# ── 数据结构 ────────────────────────────────────────────────────────


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _int_or(value, default: int) -> int:
    """字段级 int 兜底（code-review 062e920431bc）：非数字值（int 抛
    ValueError/TypeError）回退 ``default``，防单条坏数值字段把整个冻结集
    加载降级为 None、被 diff 按「无持久化集」全量替换。"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class ScenarioEntry:
    """持久化集中的单个场景记录。

    ``covers``：交互契约元数据（add-interaction-contract-and-per-assert-triage
    D2）——本场景覆盖的可交互元素标识列表；旧集无此字段（缺省空表，不追溯）。
    ``kind``：场景 kind（web/cli/api，缺省 web）——可选字段，补齐全集用于
    正确 Runner 执行（multi-kind-report-compat：冻结集补齐/合并携带 kind）。
    """

    __slots__ = ("id", "description", "added_in_round", "covers", "kind")

    def __init__(
        self,
        id: str,
        description: str = "",
        added_in_round: int = 1,
        covers: Optional[list] = None,
        kind: str = "web",
    ):
        # id 统一 str 归一（a17eb298933c，与 covers/kind 同款）：scenarios.json
        # 数字 id 原样保留 int 会与 diff 侧 str(s["id"])（_parse_reasons 同款
        # 口径）错位——恒判「无理由缺失」补齐 + planner 同名场景按新增并入，
        # 场景集出现重复条目。显式判空而非 ``or`` 回退（code-review
        # 144ec547f48f）：数字 id 0 / False 属合法 falsy 值，``or`` 会吞成
        # 空串无声改写场景身份；仅 None（缺省）归空串。
        self.id = str(id) if id is not None else ""
        self.description = description
        self.added_in_round = added_in_round
        self.covers = [str(c) for c in (covers or [])]
        self.kind = str(kind or "web")

    def to_dict(self) -> dict:
        d = {"id": self.id, "description": self.description, "added_in_round": self.added_in_round}
        if self.covers:
            d["covers"] = list(self.covers)
        # fix-frozen-scenario-orphan-reservoir D1/D4：kind 恒定写入——写端 schema
        # 门保证每条目均有合法 kind；加载侧对存量缺 kind 条目兜底归类 web
        # 保留在集（b25b28a4ed8a：剔除会把不再整档重写的存量冻结集清成空集）。
        d["kind"] = self.kind
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioEntry":
        covers = d.get("covers")
        return cls(
            # 缺省 None 委托构造器归一（144ec547f48f 同款显式判空：数字 id
            # 0/False 不吞，仅 None→""）。
            id=d.get("id"),
            description=d.get("description", ""),
            added_in_round=_int_or(d.get("added_in_round", 1) or 1, 1),
            covers=covers if isinstance(covers, list) else None,
            kind=d.get("kind", "web"),
        )


class ScenarioSet:
    """验证场景集：spec + 稳定轮次 + 场景列表。

    ``display_declarations``：交互契约纯展示声明登记（元素标识列表，D2 可审计）。
    """

    def __init__(
        self,
        spec: str,
        round_: int = 1,
        scenarios: Optional[list] = None,
        display_declarations: Optional[list] = None,
    ):
        self.spec = spec
        self.round = round_
        self.scenarios: list[ScenarioEntry] = list(scenarios or [])
        self.display_declarations = [str(d) for d in (display_declarations or [])]

    @property
    def ids(self) -> set:
        return {s.id for s in self.scenarios}

    def to_dict(self) -> dict:
        d = {
            "spec": self.spec,
            "round": self.round,
            "updated_at": _now_iso(),
            "scenarios": [s.to_dict() for s in self.scenarios],
        }
        if self.display_declarations:
            d["display_declarations"] = list(self.display_declarations)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ScenarioSet":
        if not isinstance(d, dict):
            return cls(spec="", round=1)
        declared = d.get("display_declarations")
        return cls(
            spec=d.get("spec", ""),
            round_=_int_or(d.get("round", 1) or 1, 1),
            scenarios=[ScenarioEntry.from_dict(s) for s in d.get("scenarios", [])],
            display_declarations=declared if isinstance(declared, list) else None,
        )


# ── 路径与读写 ──────────────────────────────────────────────────────


def _validate_spec_name(spec_name: str) -> str:
    """spec_name 形状防护：为空或含路径分隔符/「..」即抛 ValueError。

    形状防护（code-review cd8041b34ff3）：这类 spec_name 会拼出目标目录之外
    的读写路径，不合法即拒绝、不拼逃逸路径。scenarios_path_for 与
    read_verify_fix_section（code-review 5cb1e4a798f1）共用同一口径。
    """
    if not spec_name or "/" in spec_name or "\\" in spec_name or ".." in spec_name:
        raise ValueError(f"非法 spec 名（为空或含路径分隔符/..）: {spec_name!r}")
    return spec_name


def scenarios_path_for(project_root, spec_name: str) -> Path:
    """返回 ``.fenix/verify-progress/<spec>/scenarios.json`` 绝对路径。

    形状防护（code-review cd8041b34ff3）：spec_name 为空或含路径分隔符/「..」
    时会拼出 verify-progress 目录之外的读写路径（含伴生锁文件），不合法即抛
    ValueError，不拼逃逸路径（校验见 :func:`_validate_spec_name`）。
    """
    _validate_spec_name(spec_name)
    return Path(project_root) / ".fenix" / "verify-progress" / spec_name / "scenarios.json"


# 伴生写锁限时（秒）：diff→save 的读改写互斥用限时抢锁而非无限阻塞——持有方
# 异常悬挂时不让另一活跃 run 的验证管线跟着悬挂，超时降级无锁继续（对齐
# record_verdict_round「锁不可用不阻断」契约，item 2b598a6d5134）。
_SCENARIOS_LOCK_WAIT = 10.0


def _scenarios_lock_path(project_root, spec_name: str) -> Path:
    """scenarios.json 伴生锁文件路径（record_verdict_round 的 ``.{name}.lock`` 范式）。"""
    return scenarios_path_for(project_root, spec_name).parent / ".scenarios.json.lock"


def _acquire_scenarios_lock(lf, timeout: float = _SCENARIOS_LOCK_WAIT) -> Optional[str]:
    """在已打开的锁文件上限时抢排他锁；成功返回 None，失败返回降级原因文案
    （文件系统不支持 flock / 限时未抢到，两因可区分）供调用方留痕（降级无锁，
    不阻断验证流程）。"""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        try:
            fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return None
        except OSError as e:
            if e.errno not in (errno.EACCES, errno.EAGAIN):
                # 特殊文件系统不支持 flock 等：降级无锁（不阻断验证流程）
                return f"文件系统不支持 flock（errno={e.errno}）"
            if time.monotonic() >= deadline:
                return f"限时 {timeout:g}s 内未抢到锁（他方持锁）"
            time.sleep(0.05)


def _release_scenarios_lock(lf) -> None:
    """释放并关闭锁文件；LOCK_UN 失败只保证 close（关闭 fd 即隐式释放 flock）。"""
    try:
        fcntl.flock(lf, fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        lf.close()
    except OSError:
        pass


def _hold_scenarios_write_lock(project_root, spec_name: str):
    """打开并限时抢占 scenarios.json 伴生排他锁；不可得返回 None（降级无锁）。

    锁目录缺失（首轮、``.fenix/verify-progress/<spec>/`` 未建）时不代建目录
    （mkdir 属写副作用，diff 是只读操作）按降级无锁处理——首轮写本就是全量
    覆盖，无可丢失的并发合并基线。降级返回 None 前记 WARNING（spec+原因，
    code-review ae9a5da4bd29）：读改写原子性保障（item 2b598a6d5134）一旦
    降级即静默失效，须可从事后日志对账某轮覆盖是否发生在无锁窗口。
    """
    try:
        lf = open(_scenarios_lock_path(project_root, spec_name), "w")
    except OSError as e:
        _logger.warning(
            "scenarios.json 伴生写锁降级无锁（spec=%s）：锁文件打开失败（%s），"
            "本轮读-合并-整档覆写失去并发互斥保障",
            spec_name,
            e,
        )
        return None
    acquire_fail = _acquire_scenarios_lock(lf)
    if acquire_fail is not None:
        _release_scenarios_lock(lf)
        _logger.warning(
            "scenarios.json 伴生写锁降级无锁（spec=%s）：%s，"
            "本轮读-合并-整档覆写失去并发互斥保障",
            spec_name,
            acquire_fail,
        )
        return None
    return lf


def load_scenario_set(project_root, spec_name: str) -> Optional[ScenarioSet]:
    """读取持久化场景集；文件缺失/损坏返回 None（不抛出）。

    加载净化（fix-frozen-scenario-orphan-reservoir D4，code-review
    b25b28a4ed8a 修正）：非对象条目剔除；缺/非法 ``kind`` 的条目**兜底归类
    web 保留在集中，不再剔除**——剔除会让先于 kind 字段落盘、不再整档重写
    的存量冻结集加载成空集，diff 把 planner 重出场景全按新增处理、修复轮
    被超发拦截后以空集写回（冻结场景集被静默清零）。兜底只影响内存集合，
    不改写 scenarios.json 文件；planner 产出携带合法 kind 时仍由 diff 侧
    刷新为正确值。
    """
    path = scenarios_path_for(project_root, spec_name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw_entries = data.get("scenarios")
    if not isinstance(raw_entries, list):
        # 7ba7327e8ebc：合法 JSON dict 缺 ``scenarios`` 键（或值非 list）与
        # 顶层非 dict 同口径按损坏返回 None——否则 from_dict 以缺省 [] 构造
        # 空集，diff 走「有持久化集」分支把 planner 重出场景全按新增处理、
        # 修复轮被超发拦截后以空集写回，冻结集无法从 planner 产出自愈
        # （b25b28a4ed8a 同故障方向）。
        return None
    kept: list = []
    rejected: list[str] = []
    backfilled: list[str] = []
    for i, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            # 记原始数组下标（非已保留计数），供 admin 按日志定位文件行（f79a6e2da286）。
            rejected.append(f"[{i}]非对象")
            continue
        if item.get("kind") not in VALID_KINDS:
            # b25b28a4ed8a：缺/非法 kind 兜底归类 web 保留在集（不再剔除，
            # 防存量无 kind 冻结集被清成空集后写回）；不写回文件。
            # 显式判空（code-review 5e4596631913）：数字 id 0 属合法 falsy
            # 值，``or`` 会显示成 "?"；仅 None/空串回退占位符。
            raw_bid = item.get("id")
            backfilled.append((str(raw_bid) if raw_bid is not None else "") or "?")
            item = {**item, "kind": "web"}
        kept.append(item)
    if backfilled:
        _logger.warning(
            "持久化集加载净化：%d 条缺/非法 kind 条目兜底归类 web 保留在集"
            "（scenarios.json 文件不改写，diff 侧合法 kind 仍可刷新）: %s",
            len(backfilled),
            "、".join(backfilled),
        )
    if rejected:
        _logger.warning(
            "持久化集加载净化剔除 %d 条非对象孤儿条目"
            "（scenarios.json 文件不改写，仅内存集合净化）: %s",
            len(rejected),
            "、".join(rejected),
        )
    if backfilled or rejected:
        data = {**data, "scenarios": kept}
    try:
        return ScenarioSet.from_dict(data)
    except (ValueError, TypeError, AttributeError):
        # 数值字段已字段级兜底（_int_or，非数字回退 1，不再到此处）；残剩
        # 损坏形态如 scenarios 为非列表标量（对字符调 .get 抛 AttributeError）：
        # 按「损坏返回 None」契约降级，不向调用方上抛中断验证流程
        return None


def _atomic_write(path: Path, data: dict) -> None:
    """原子写 scenarios.json（core.fs_utils.atomic_write_text 单一实现）。

    权限口径（item 8b26fd7980ce 收口两份拷贝，本模块原语义不变）：恒 0644
    （mkstemp 以 0600 建临时文件，rename 前放宽）——否则 scenarios.json 恒
    0600，非 root 辅助进程/人工其它账号读取被拒。与 verify_report 版「替换
    既有文件继承原 mode」的差异由 ``inherit_existing_mode`` 参数显式表达，
    不再各持一份拷贝各自漂移（截断防护/收尾纪律见 core/fs_utils.py）。
    """
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


# ── 持久化集条目结构校验（fix-frozen-scenario-orphan-reservoir D1/D4）────


def validate_scenario_entries(entry_dicts: list) -> list[str]:
    """持久化集条目（'scenarios.json' 的 dict 列表）结构校验。

    scenarios.json 的 ScenarioEntry 与 test_scenarios.json 的 TestScenario
    形态不同（无 steps/assertions），无法直接复用 ``validate_scenario_dicts``；
    这里对 ScenarioEntry 形态做等价的结构校验——**每条 MUST 有非空 id 且
    合法 kind**（无 kind 无法路由到任何 Runner＝孤儿，储库复活根因；空 id
    条目加载侧兜底为 ""、diff 循环恒判「无理由缺失」补齐保留，同属无法
    路由的孤儿形态）。返回错误清单，空列表表示全部合法；本函数不抛异常。
    """
    errors: list[str] = []
    if not isinstance(entry_dicts, list):
        return [f"场景集数据格式错误: 期望数组，实际为 {type(entry_dicts).__name__}"]
    for i, item in enumerate(entry_dicts):
        if not isinstance(item, dict):
            errors.append(f"场景集条目[{i}]解析失败: 期望对象，" f"实际为 {type(item).__name__}")
            continue
        # 显式判空（code-review 5e4596631913）：数字 id 0 属合法 falsy 值，
        # ``or`` 会显示成下标占位；仅 None/空串回退占位符。
        sid = str(item.get("id")) if item.get("id") is not None else ""
        sid = sid or f"[{i}]"
        # 显式判空（f54ff9c4e1f5，与上方 sid/构造器 144ec547f48f 同款）：
        # 数字 id 0 属合法 falsy 值，不得经 ``or`` 兜底误判缺 id。
        raw = item.get("id")
        if raw is None or not str(raw).strip():
            errors.append(f"场景集条目[{i}] 缺少非空 id")
        kind = item.get("kind")
        if kind not in VALID_KINDS:
            errors.append(
                f"场景集条目 '{sid}' 缺少合法 kind（收到 {kind!r}），"
                f"无法路由到 Runner，属孤儿条目"
            )
    return errors


def save_scenario_set(project_root, scenario_set: ScenarioSet) -> Path:
    """持久化场景集（原子写）。返回写入路径。

    写端 schema 门（fix-frozen-scenario-orphan-reservoir D1/D2）：写回前对
    ScenarioEntry 列表做结构校验，非法条目（如缺 kind 的孤儿）剔除并留痕，
    合法部分照常落盘——不整批拒绝（避免单条坏数据放大成整轮验证无法进行）。
    非 ScenarioEntry 条目按校验失败剔除留痕（2eaebbf39624：原 ``dict(e)``
    伪兜底转换出的裸 dict 无 ``to_dict``、写回阶段必崩，契约外类型不转换）。
    剔除只作用于落盘副本，不原地改写入参（code-review b94f527e8bb8）——
    调用方 save 后复用同一 ScenarioSet 拿到的仍是原集合，无隐性剪枝。

    写盘在 scenarios.json 伴生 fcntl 排他锁内完成（item 2b598a6d5134 读-合
    并-写原子）：入参集携带 ``_pending_write_lock``（diff_planner_output 移交）
    时复用该锁、落盘即释放——同进程对同一锁文件二次 flock 会自锁，MUST NOT
    重取；独立调用（测试、非 diff 链路写回）自取同一把锁。锁不可得降级无锁
    落盘（不撕裂仍由 _atomic_write 保证），不阻断持久化。
    """
    clean_entries: list[ScenarioEntry] = []
    rejected: list[str] = []
    for e in scenario_set.scenarios:
        if not isinstance(e, ScenarioEntry):
            eid = e.get("id") if isinstance(e, dict) else getattr(e, "id", None)
            # 显式判空（code-review 5e4596631913）：数字 id 0 显示原值不吞占位。
            eid = str(eid) if eid is not None else ""
            rejected.append(f"{eid or '?'}（期望 ScenarioEntry，实际为 {type(e).__name__}）")
            continue
        d = {
            "id": e.id,
            "kind": e.kind,
            "description": e.description,
            "added_in_round": e.added_in_round,
        }
        errs = validate_scenario_entries([d])
        if errs:
            rejected.append(f"{d.get('id') or '?'}（{'；'.join(errs)}）")
            continue
        clean_entries.append(e)

    if rejected:
        _logger.warning(
            "场景集写端校验剔除 %d 个非法条目（scenarios.json 不落盘）: %s",
            len(rejected),
            "、".join(rejected),
        )
    # 落盘副本（b94f527e8bb8）：__init__ 内部 ``list(scenarios or [])`` 换新
    # 列表，与入参 scenarios 无列表引用共享；display_declarations 亦逐项复制。
    persist_set = ScenarioSet(
        scenario_set.spec,
        scenario_set.round,
        clean_entries,
        display_declarations=scenario_set.display_declarations,
    )
    path = scenarios_path_for(project_root, scenario_set.spec)
    pending_lock = getattr(scenario_set, "_pending_write_lock", None)
    scenario_set._pending_write_lock = None  # 锁一次性消费，防二次 save 复用已关 fd
    if pending_lock is not None:
        try:
            _atomic_write(path, persist_set.to_dict())
        finally:
            _release_scenarios_lock(pending_lock)
        return path
    # 独立写回（非 diff 链路）：自取伴生锁，与其余写方互斥
    lock_file = _hold_scenarios_write_lock(project_root, scenario_set.spec)
    try:
        _atomic_write(path, persist_set.to_dict())
    finally:
        if lock_file is not None:
            _release_scenarios_lock(lock_file)
    return path


# ── 修复段解析（design D2：新增交付范围判定）────────────────────────


def read_verify_fix_section(project_root, spec_name: str) -> Optional[str]:
    """读取 tasks.md 的「## 验证修复」段全文；不存在返回 None。

    spec_name 形状防护与 scenarios_path_for 同口径（code-review 5cb1e4a798f1）：
    为空或含路径分隔符/「..」即抛 ValueError，不拼 changes 目录之外的逃逸
    读取路径（校验见 :func:`_validate_spec_name`）。
    """
    _validate_spec_name(spec_name)
    tasks_path = Path(project_root) / "spec" / "changes" / spec_name / "tasks.md"
    if not tasks_path.exists():
        return None
    try:
        text = tasks_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    m = VERIFY_FIX_SECTION_RE.search(text)
    if not m:
        return None
    after = text[m.end() :]
    nxt = re.search(r"\n## [^\n]", after)
    end = m.end() + nxt.start() if nxt else len(text)
    return text[m.start() : end]


def _note_excerpt(fix_section: str, m: "re.Match", reason_text: str) -> str:
    """排除留痕行：命中处所在行摘录（strip 后截 60 字符）+ 排除原因文案。

    修复语境与否定语境两类排除共用同一摘录口径（code-review 6b2089384b1b，
    仅原因文案不同），防两份拷贝各自漂移。
    """
    line_start = fix_section.rfind("\n", 0, m.start()) + 1
    line_end = fix_section.find("\n", m.end())
    if line_end == -1:
        line_end = len(fix_section)
    excerpt = fix_section[line_start:line_end].strip()[:60]
    return f"- 「{excerpt}」{reason_text}"


def declares_new_delivery(fix_section: Optional[str], notes: Optional[list] = None) -> bool:
    """修复段是否声明了「新增交付范围」。

    仅当修复段存在且含「新增/追加/增加 … 交付/范围/功能/能力…」时才允许追加。
    纯修复（无新增范围）返回 False，planner 不得扩容。动词后（允许「了」等
    少量衔接字）出现「对/针对/对于 … 的修复」短语的命中按修复语境排除、
    不计入新增交付声明（bcb05f957b2d：如「追加对场景 X 的修复」「追加了
    针对场景 X 的修复」）。动词前同条款内紧邻否定前缀（未/无/不…）的命中
    按否定表述排除（code-review cec71a4419ae：如「未新增场景」「无新增
    交付范围」「不增加功能」），同条款限定防跨句误排除——「上一轮无新增，
    本次新增 X 场景」的后半句真实声明仍计为扩容。两类排除均向 ``notes``
    （若提供）追加留痕行供审计。
    """
    if not fix_section:
        return False
    for m in _NEW_DELIVERY_RE.finditer(fix_section):
        if _REPAIR_PHRASE_RE.match(fix_section, m.end(1)):
            if notes is not None:
                notes.append(
                    _note_excerpt(
                        fix_section,
                        m,
                        "命中新增交付词形但属修复语境"
                        "（对…的修复），该处不计入新增交付声明",
                    )
                )
            continue
        # 否定语境排除（cec71a4419ae）：自上一句读/换行到动词前的同条款
        # 片段以否定词收尾 ⇒ 否定表述，按非声明处理并留痕。
        clause_start = max(
            fix_section.rfind(ch, 0, m.start(1)) for ch in "，。；\n"
        ) + 1
        if _NEGATED_DELIVERY_RE.search(fix_section[clause_start : m.start(1)]):
            if notes is not None:
                notes.append(
                    _note_excerpt(
                        fix_section,
                        m,
                        "命中新增交付词形但属否定表述"
                        "（未/无/不…），该处不计入新增交付声明",
                    )
                )
            continue
        return True
    return False


# ── 修复轮判定（design D1）─────────────────────────────────────────

# 缺省哨兵（ce38ede06575）：区分「调用方未提供已读修复段」与「已读且段不
# 存在（None）」——后者不得回源重读盘，否则同一轮 diff 对修复段两次观测。
_UNSET = object()


def is_repair_round(
    project_root, spec_name: str, state: Optional[dict], fix_section=_UNSET
) -> bool:
    """判定是否为修复轮。

    D1 信号（与原地打回机制同源，不引入新状态）：
      - STATE.md ``_verify_fail_rounds > 0``，或
      - tasks.md 含「## 验证修复」段。

    fix_section：调用方已读的修复段文本（``read_verify_fix_section`` 返回
    值，None＝段不存在）。提供时本函数不再重复读盘、直接据其存在性判定，
    与同轮 ``extended`` 闸门共用同一文本快照；缺省哨兵时维持原读盘行为，
    既有三参调用点不受影响。
    """
    entry = state or {}
    try:
        fail_rounds = int(entry.get("_verify_fail_rounds", 0) or 0)
    except (TypeError, ValueError):
        fail_rounds = 0
    if fail_rounds > 0:
        return True
    if fix_section is _UNSET:
        fix_section = read_verify_fix_section(project_root, spec_name)
    return fix_section is not None


# ── 确定性 diff 校验器（design D3：planner 不可绕过）─────────────────


class DiffResult:
    """planner 产出 vs 持久化集的 diff 结论。

    Attributes:
        ok: 校验是否通过（通过＝可写回；不通过＝以持久化集补齐后继续）。
        scenario_set: 校验后应采用的最终场景集（通过时＝合并结果；
            不通过时＝以持久化集补齐缺失场景后的集）。
        added: 本轮新增的 ScenarioEntry 列表（仅新增范围合法追加）。
        removed: 本轮被移除的 (ScenarioEntry, reason) 列表（有理由删减）。
        unreasoned_missing: 无理由缺失的 ScenarioEntry 列表（被补齐）。
        change_lines: 「本轮场景集变更」小节渲染用的行（人类可读）。
        extended: 是否声明了新增交付范围（允许追加）。
    """

    def __init__(self):
        self.ok = True
        self.scenario_set: Optional[ScenarioSet] = None
        self.added: list[ScenarioEntry] = []
        self.removed: list = []  # (ScenarioEntry, reason)
        self.unreasoned_missing: list[ScenarioEntry] = []
        self.change_lines: list[str] = []
        self.extended = False


def _parse_reasons(planner_scenarios: list) -> dict:
    """从 planner 产出中提取每个场景的「移除理由」。

    planner 可在场景对象上用 ``remove_reason`` 字段声明移除理由（设计 D2：
    删减既有场景 MUST 提供理由）。无该字段视为无理由。
    """
    reasons = {}
    for s in planner_scenarios:
        if not isinstance(s, dict):
            continue
        raw_sid = s.get("id")
        # str 归一：与 diff_planner_output 的 sid = str(s["id"]) 口径对齐，
        # 否则 planner 把 id 写成数字等非字符串形态时移除声明查不到（8a8a338f653a）。
        # 显式判空而非 ``or`` 回退（code-review 144ec547f48f）：数字 id 0
        # 不吞成空串，与 diff 侧 str(0)="0" 保持一致。
        sid = str(raw_sid) if raw_sid is not None else ""
        if sid and s.get("remove_reason"):
            reasons[sid] = str(s["remove_reason"])
    return reasons


def _covers_of(scenario: dict) -> list:
    """场景对象的交互契约 ``covers`` 元数据（非列表时缺省空表）。"""
    covers = scenario.get("covers") if isinstance(scenario, dict) else None
    if not isinstance(covers, list):
        return []
    return [str(c) for c in covers if c]


def _kind_of(scenario: dict) -> str:
    """场景对象的 kind（multi-kind-report-compat：冻结条目携带 kind，
    读侧缺失缺省 web，存量冻结文件零迁移）。"""
    kind = scenario.get("kind") if isinstance(scenario, dict) else None
    if kind not in VALID_KINDS:
        return "web"
    return str(kind)


def _legal_kind_of(scenario: dict) -> Optional[str]:
    """场景对象的 kind，仅当为合法值（web/cli/api）时返回；缺失/非法返回
    None（17250417a111：供既有条目保留冻结原值，不缺省改写 web）。"""
    kind = scenario.get("kind") if isinstance(scenario, dict) else None
    if kind not in VALID_KINDS:
        return None
    return str(kind)


def _display_declarations_of(planner_scenarios: list) -> list:
    """planner 产出中登记的纯展示声明（D2：declared-display 登记进元数据）。"""
    from core.interaction_contract import collect_display_declarations

    return collect_display_declarations(planner_scenarios)


def diff_planner_output(
    project_root, spec_name: str, state: Optional[dict], planner_scenarios: list, current_round: int
) -> DiffResult:
    """确定性 diff 校验：planner 产出 vs 持久化集。

    读基线→合并全程持有 scenarios.json 伴生 fcntl 排他锁（record_verdict_round
    的 ``.{name}.lock`` 范式，item 2b598a6d5134）：锁随返回集（scenario_set 的
    私有属性 ``_pending_write_lock``）移交 ``save_scenario_set``、落盘后释放
    ——「读基线→合并→整档覆写」对同 spec 双活跃 run（manual-intervention 与
    blocked_stuck 各一）原子，后写者不再以自身读到的旧基线整档覆盖、丢掉先写
    者新增/补齐的条目。锁不可得（锁文件打开失败/文件系统不支持 flock/限时未
    抢到）降级无锁继续，不阻断验证；本函数异常退出时就地释放。

    调用方契约（code-review 59d8b4603f5d）：返回集 MUST 要么交
    ``save_scenario_set`` 落盘（落盘即释放锁），要么在校验后放弃落盘时显式
    释放（``_release_scenarios_lock(result.scenario_set._pending_write_lock)``,
    可先判 None）；两者都不做时锁 fd 随 ScenarioSet 实例滞留至 GC/进程退出，
    期间同 spec 其他写方每次都按 ``_SCENARIOS_LOCK_WAIT`` 白等限时才降级无锁
    （有界不悬挂，但与异常退出的就地释放不对称）。
    """
    lock_file = _hold_scenarios_write_lock(project_root, spec_name)
    try:
        result = _diff_planner_output_impl(
            project_root, spec_name, state, planner_scenarios, current_round
        )
    except BaseException:
        if lock_file is not None:
            _release_scenarios_lock(lock_file)
        raise
    if result.scenario_set is not None:
        result.scenario_set._pending_write_lock = lock_file  # None＝已降级无锁
    elif lock_file is not None:
        # 无产出集（防御分支）：锁不得留待解释器 GC 兜底释放
        _release_scenarios_lock(lock_file)
    return result


def _diff_planner_output_impl(
    project_root, spec_name: str, state: Optional[dict], planner_scenarios: list, current_round: int
) -> DiffResult:
    """``diff_planner_output`` 的锁内实现。

    Args:
        project_root: 项目根（用于读取修复段 / 持久化集）。
        spec_name: SPEC 名。
        state: STATE.md 中该 spec 的 entry（含 ``_verify_fail_rounds``）。
        planner_scenarios: planner-plan 产出的场景列表（dict 列表，可含
            ``id`` / ``description`` / ``remove_reason``）。
        current_round: 本轮验证轮次（用于记录 added_in_round）。

    Returns:
        DiffResult：含校验结论与应写回的场景集。
    """
    result = DiffResult()
    persisted = load_scenario_set(project_root, spec_name)
    fix_section = read_verify_fix_section(project_root, spec_name)
    result.extended = declares_new_delivery(fix_section, notes=result.change_lines)
    # 复用上一行已读的修复段快照（ce38ede06575）：单轮 diff 对修复段单次
    # 观测，extended 与 repair 两闸门不同文本判定、且多付一次 IO。
    repair = is_repair_round(project_root, spec_name, state, fix_section)

    # ── 首轮 / 无持久化集：直接采用 planner 产出，全量写回 ──
    if persisted is None:
        # 同 id 重复时先按 id 收敛：值取末个（与下方有持久化集分支
        # planner_by_id 的覆盖口径一致）、序取首次出现位（dict 插入序，
        # 确定性）——否则重复 id 原样写进 scenarios.json 成重复条目，
        # ids 集合与文件条目数不一致，下一轮 diff 表现随分支漂移。
        dedup_by_id: dict = {}
        skipped: list[str] = []
        for i, s in enumerate(planner_scenarios):
            # 移除声明条目（remove_reason 非空的不可执行形态）不入集，与
            # 下方有持久化集分支的 sid in reasons 跳过同口径——否则首轮
            # 写进 scenarios.json 成幽灵条目，下一轮被判无理由缺失。
            raw_sid = s.get("id") if isinstance(s, dict) else None
            # 显式判空而非 ``or``/真值回退（code-review 5e4596631913，与
            # _parse_reasons/ScenarioEntry 构造器 144ec547f48f 同款）：数字
            # id 0 属合法 falsy 值，不得当「缺 id」跳过。
            sid = str(raw_sid) if raw_sid is not None else ""
            if isinstance(s, dict) and sid and not s.get("remove_reason"):
                dedup_by_id[sid] = s
            elif not isinstance(s, dict):
                skipped.append(f"[{i}]非对象")
            elif not sid:
                skipped.append(f"[{i}]缺 id")
            else:
                skipped.append(f"[{i}]{sid}（remove_reason 声明移除）")
        if skipped:
            # 剔除留痕（code-review 5a762fcbff17）：本分支没有有持久化集分支
            # 的 missing→补齐路径兜底，静默跳过会让冻结集缩水且无法从日志
            # 还原原因——与加载净化/写端校验的剔除留痕纪律对齐，含原始数组
            # 下标供按日志定位。
            _logger.warning(
                "首轮场景集收敛跳过 %d 条 planner 条目（不入冻结集）: %s",
                len(skipped),
                "、".join(skipped),
            )
        entries = [
            ScenarioEntry(
                id=sid,
                description=str(s.get("description", "")),
                added_in_round=current_round,
                covers=_covers_of(s),
                kind=_kind_of(s),
            )
            for sid, s in dedup_by_id.items()
        ]
        result.scenario_set = ScenarioSet(
            spec_name,
            current_round,
            entries,
            display_declarations=_display_declarations_of(planner_scenarios),
        )
        result.added = list(entries)
        # append 而非整体重赋值：保留 declares_new_delivery 已写入的
        # 修复语境审计留痕行（与有持久化集分支行为一致）。
        result.change_lines.append(f"- 首轮写入 {len(entries)} 个场景")
        # 非法 kind 留痕（code-review 284c5f40f6a9）：kind 字段在场但非法
        # （如误写 gui）与缺失不同——缺失归一 web 是合理缺省，非法值属
        # planner 误写，首轮无声固化进 scenarios.json 会以 web 路由到
        # WebRunner，与有持久化集分支的防误路口径（17250417a111：非法不
        # 刷新、cli/api 保留原值留痕）不对称。首轮无冻结原值可保留，仍归一
        # web 入集，但比照本分支 skipped 剔除留痕纪律记 WARNING 与场景集
        # 变更行供审计、下轮 planner 纠正。
        illegal_kinds: list[str] = []
        for sid, s in dedup_by_id.items():
            raw_kind = s.get("kind")
            if raw_kind is not None and raw_kind not in VALID_KINDS:
                illegal_kinds.append(f"{sid}（kind={raw_kind}）")
        if illegal_kinds:
            _logger.warning(
                "首轮场景集收敛 %d 条条目携带非法 kind（归一 web 入冻结集）: %s",
                len(illegal_kinds),
                "、".join(illegal_kinds),
            )
            result.change_lines.append(
                f"- {len(illegal_kinds)} 个首轮条目 kind 非法（planner 误写），"
                f"归一 web：{'、'.join(illegal_kinds)}"
            )
        return result

    persisted_ids = persisted.ids
    reasons = _parse_reasons(planner_scenarios)

    # planner 产出的「保留/新增」场景（非移除项）
    planner_ids = set()
    planner_by_id = {}
    # 剔除留痕（code-review 10e98d8d1125，对齐首轮分支 5a762fcbff17 纪律）：
    # 非 dict/缺 id 条目静默丢弃会让冻结集表现无法从日志还原，复用首轮分支
    # 同款 skipped 收集记 WARNING；remove_reason 声明移除走下方 sid in reasons
    # 路径、已有「有理由删减留痕」，不在其中。
    skipped: list[str] = []
    for i, s in enumerate(planner_scenarios):
        if not isinstance(s, dict):
            skipped.append(f"[{i}]非对象")
            continue
        raw_sid = s.get("id")
        # 显式判空而非 ``or``/真值回退（code-review 5e4596631913，与
        # _parse_reasons 144ec547f48f 同款）：数字 id 0 属合法 falsy 值，
        # 不得当「缺 id」跳过（否则持久化集对应条目被判「无理由缺失」误报）。
        sid = str(raw_sid) if raw_sid is not None else ""
        if not sid:
            skipped.append(f"[{i}]缺 id")
            continue
        if sid in reasons:
            continue  # 该场景被 planner 显式移除（带理由）
        planner_ids.add(sid)
        planner_by_id[sid] = s
    if skipped:
        # 剔除留痕（code-review 5a762fcbff17）：与首轮分支同口径，含原始
        # 数组下标供按日志定位；本分支对坏条目同样只是丢弃不入集。
        _logger.warning(
            "场景集 diff 跳过 %d 条 planner 条目（非对象/缺 id，不入冻结集）: %s",
            len(skipped),
            "、".join(skipped),
        )

    # 交互契约元数据（D2）：既有条目的 covers 以 planner 本轮产出为准刷新
    # （场景重排后映射可能变化），新增条目直接携带。kind 仅在 planner 产出
    # 携带合法 kind（web/cli/api）时才刷新；缺失/非法保留冻结文件原值
    # （17250417a111：避免 planner 漏给 kind 时 cli/api 冻结条目被无声改写
    # 为 web、下一轮路由到错误 Runner）。仅冻结原值为 cli/api（保留与缺省
    # web 刷新会产生真实分叉、有误路由风险）时记 change_lines 留痕供审计；
    # 原值 web/缺省场景保留即无操作，静默不计变更。
    kept_kind_ids: list[str] = []
    for e in persisted.scenarios:
        s = planner_by_id.get(e.id)
        if s is not None:
            e.covers = _covers_of(s)
            legal = _legal_kind_of(s)
            if legal is not None:
                e.kind = legal
            elif e.kind in ("cli", "api"):
                kept_kind_ids.append(e.id)
    if kept_kind_ids:
        result.change_lines.append(
            f"- {len(kept_kind_ids)} 个既有条目的 kind 保留冻结文件原值"
            f"（planner 产出缺合法 kind）：{'、'.join(kept_kind_ids)}"
        )

    # ── 删减检测：持久化集有、planner 没有 ──
    missing = [e for e in persisted.scenarios if e.id not in planner_ids]
    unreasoned = [e for e in missing if not reasons.get(e.id)]
    reasoned = [(e, reasons[e.id]) for e in missing if reasons.get(e.id)]

    result.removed = reasoned
    result.unreasoned_missing = unreasoned

    # ── 新增检测：planner 有、持久化集没有 ──
    # 默认保留全部既有，但排除有理由移除的场景（scenarios.json 同步移除）。
    removed_ids = {e.id for e, _ in reasoned}
    kept_entries = [e for e in persisted.scenarios if e.id not in removed_ids]
    new_entries = []
    # 按 sid 排序遍历：set 迭代序随 PYTHONHASHSEED 跨进程抖动，违背模块 D3 确定性
    for sid in sorted(planner_ids):
        if sid in persisted_ids:
            continue
        s = planner_by_id[sid]
        new_entries.append(
            ScenarioEntry(
                id=sid,
                description=str(s.get("description", "")),
                added_in_round=current_round,
                covers=_covers_of(s),
                kind=_kind_of(s),
            )
        )

    # ── 受控增量约束（design D2）──
    # 合法追加（design D2：新增范围允许追加；非修复轮重新规划允许新增但走
    # diff 记录）：合并写回，不进下方拦截分支。
    # 拦截超发：修复轮且未声明新增交付时，任何新增均属「超发」，必须拦截
    # （spec：修复轮不扩容），本批新增被丢弃（仅保留既有集）。
    if new_entries and not result.extended and repair:
        overcount = len(new_entries)
        # 剔除留痕（code-review 5ea697aa80e6，对齐首轮 illegal_kinds 分支
        # 「WARNING+变更行」双留痕口径）：只写变更行时，报告丢失或未渲染
        # 该小节则无法从日志对账本轮哪些新增场景被丢弃；含被丢弃的
        # scenario_id 清单供按日志定位。
        dropped_ids = [e.id for e in new_entries]
        _logger.warning(
            "拦截 planner 超发 %d 个未声明新增范围的场景"
            "（修复轮不扩容，按 D2 丢弃）: %s",
            overcount,
            "、".join(dropped_ids),
        )
        new_entries = []
        result.change_lines.append(
            f"- 拦截 planner 超发 {overcount} 个未声明新增范围的场景"
            f"（修复轮不扩容，按 D2 丢弃）：{'、'.join(dropped_ids)}"
        )

    final_entries = kept_entries + new_entries
    result.scenario_set = ScenarioSet(
        spec_name,
        current_round,
        final_entries,
        display_declarations=_display_declarations_of(planner_scenarios),
    )
    result.added = new_entries

    # ── 无理由缺场景 → 校验失败，以持久化集补齐后继续（不中断验证）──
    if unreasoned:
        result.ok = False
        result.change_lines.append(
            f"- 无理由缺失 {len(unreasoned)} 个场景，已以持久化集补齐："
            + "、".join(e.id for e in unreasoned)
        )
        # 补齐：final_entries 已含全部既有（kept_entries），无需额外操作；
        # 但 ok=False 标记「本轮验证以持久化集补齐缺失场景后继续」。
    else:
        result.ok = True

    # ── 有理由删减留痕 ──
    for e, reason in reasoned:
        result.change_lines.append(f"- 移除场景 {e.id}（理由：{reason}）")

    # ── 合法新增记录 ──
    for e in new_entries:
        scope = "新增范围" if result.extended else "重新规划"
        result.change_lines.append(f"- 新增场景 {e.id}（{scope}，第 {current_round} 轮）")

    return result


# ── 报告渲染（spec 需求 2.3：本轮场景集变更小节）────────────────────


def render_change_section(diff: DiffResult) -> str:
    """把 diff 结论渲染为验证报告的「本轮场景集变更」小节（Markdown）。"""
    if diff is None:
        return ""
    lines = ["", "## 本轮场景集变更", ""]
    if not diff.change_lines:
        lines.append("场景集与持久化集一致，无变更。")
        lines.append("")
        return "\n".join(lines)
    if diff.scenario_set is not None:
        lines.append(
            f"当前稳定场景集共 {len(diff.scenario_set.scenarios)} 个"
            f"（第 {diff.scenario_set.round} 轮）。"
        )
    lines.append("")
    for cl in diff.change_lines:
        lines.append(cl)
    if not diff.ok:
        lines.append("")
        lines.append(
            "> ⚠️ 本轮 planner 产出缺少既有场景且无理由，已以持久化集补齐后继续验证"
            "（不中断验证）。"
        )
    lines.append("")
    return "\n".join(lines)


def render_first_write_section(scenario_set: ScenarioSet) -> str:
    """首轮写入的「本轮场景集变更」小节渲染。"""
    diff = DiffResult()
    diff.scenario_set = scenario_set
    diff.change_lines = [f"- 首轮写入 {len(scenario_set.scenarios)} 个场景"]
    return render_change_section(diff)
