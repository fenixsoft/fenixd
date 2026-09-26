"""core.dashboard.data.spec_docs — SPEC 文档读取（spec_docs 组）。

refactor-dashboard-data-module D3 分组：本模块承载 SPEC 文档/场景职责域。
resolve_spec_dir / 文档白名单 / 场景计数与生成进度。
"""

import json
import re
from pathlib import Path

# kebab-case：小写字母/数字开头，仅含小写字母/数字/连字符（防御路径穿越）
_SPEC_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
# doc 白名单：仅允许读取这些核心设计文档（tasks.md 与 proposal.md 同目录）
_SPEC_DOC_WHITELIST = ("proposal", "design", "tasks", "verification", "scenarios")


# ── SPEC 文档读取（proposal.md / design.md，add-spec-doc-buttons） ──


def resolve_spec_dir(project_root, spec) -> Path | None:
    """解析 SPEC 目录：活跃优先，归档回退（fix-archived-spec-doc-readback D1）。

    1. spec 不匹配 ``_SPEC_NAME_RE`` → 返回 None（kebab-case 白名单天然排除
       ``..``/``/``，此处校验同时强化 parse_tasks 的健壮性）
    2. ``spec/changes/<spec>`` 为目录 → 返回活跃目录（活跃优先，既有行为不变）
    3. 否则遍历 ``spec/archive/``，目录名匹配日期前缀 + 可选冲突数字后缀
       （``^\\d{4}-\\d{2}-\\d{2}-{re.escape(spec)}(-\\d+)*$``；``re.escape``
       防 spec 名含 ``-`` 引发歧义），命中多个时**全等目录名（剥日期前缀
       后与 spec 全等）优先**（对齐 evolution.resolve_accepted_spec_dir：
       合法 spec 名允许数字结尾，可选数字后缀会把独立 spec——如
       ``evo-foo`` 与 ``evo-foo-2`` 并存——的归档目录一并命中，sorted 兜底
       因后缀字典序更大而把后者误归属给前者）；同层内取 ``sorted()[-1]``
       （字典序最大 = 日期最新/后缀最大）
    4. 无命中 → None
    """
    if not isinstance(spec, str) or not _SPEC_NAME_RE.match(spec):
        return None
    active = Path(project_root) / "spec" / "changes" / spec
    if active.is_dir():
        return active
    archive_root = Path(project_root) / "spec" / "archive"
    if not archive_root.is_dir():
        return None
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-" + re.escape(spec) + r"(-\d+)*$")
    exact_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-" + re.escape(spec) + r"$")
    try:
        matches = [d for d in archive_root.iterdir() if d.is_dir() and pattern.match(d.name)]
    except OSError:
        # 遍历失败（IO/权限等）等价无归档命中，与 _read_spec_scenarios 兜底口径一致
        matches = []
    if not matches:
        return None
    # 全等目录名（剥日期前缀后与 spec 全等）优先（对齐
    # evolution.resolve_accepted_spec_dir 口径）：合法 spec 名允许数字结尾，
    # 可选数字后缀 (-\d+)* 会把独立 spec（如 evo-foo 与 evo-foo-2 并存）的
    # 归档目录一并命中，sorted 兜底因后缀字典序更大而误归属到错误 spec；
    # 无全等命中时才回退到含数字后缀的归一化候选层。
    exact = [d for d in matches if exact_pattern.match(d.name)]
    return sorted(exact or matches)[-1]


class InvalidSpecName(ValueError):
    """spec 名称非法（非 kebab-case 或含路径穿越）。"""


class InvalidSpecDoc(ValueError):
    """doc 参数非法（不在 _SPEC_DOC_WHITELIST 白名单——单一来源，防注释漂移）。"""


class InvalidPriority(ValueError):
    """优先级非法（非 1-9 整数）。"""


def get_spec_doc(project_root, spec: str, doc: str) -> dict:
    """读取 SPEC 的 proposal.md / design.md / tasks.md 原文。

    Args:
        project_root: 项目根目录
        spec: SPEC 名称（须 kebab-case）
        doc: 文档类型，"proposal" / "design" / "tasks" / "verification"（验证报告）/ "scenarios"（测试场景清单汇总）

    Returns:
        {"found": bool, "content": str}
        - 文件存在：found=True, content=文件原文
        - 文件不存在：found=False, content=""

    Raises:
        InvalidSpecName: spec 非 kebab-case（含可能的路径穿越片段）
        InvalidSpecDoc: doc 不在白名单
    """
    if not isinstance(spec, str) or not _SPEC_NAME_RE.match(spec):
        raise InvalidSpecName(spec)
    if doc not in _SPEC_DOC_WHITELIST:
        raise InvalidSpecDoc(doc)

    spec_dir = resolve_spec_dir(project_root, spec)
    if spec_dir is None:
        # spec 合法但活跃/归档目录均不存在 → 与原有"目录不存在"行为一致
        return {"found": False, "content": ""}
    if doc == "verification":
        # 验证报告：verification-report.md（可能尚未生成 → found=False）
        target = (spec_dir / "verification-report.md").resolve()
    elif doc == "scenarios":
        # 测试场景清单：specs/<capability>/spec.md 的汇总拼接
        return _read_spec_scenarios(spec_dir / "specs")
    else:
        target = (spec_dir / f"{doc}.md").resolve()
    # 防御性校验：解析后必须仍位于该 SPEC 目录内（活跃/归档回退同样生效），
    # 杜绝任何 `..` 拼接越界
    if not target.is_relative_to(spec_dir.resolve()):
        raise InvalidSpecName(spec)
    if not target.is_file():
        return {"found": False, "content": ""}
    try:
        content = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {"found": False, "content": ""}
    return {"found": True, "content": content}


def _read_spec_scenarios(specs_dir: Path) -> dict:
    """汇总 change 的 specs/<capability>/spec.md 为测试场景清单（markdown 拼接）。

    每个 capability 以 `# <capability-name>` 一级标题分隔，场景原文保持不变。
    """
    if not specs_dir.is_dir():
        return {"found": False, "content": ""}
    parts = []
    try:
        for cap_dir in sorted(specs_dir.iterdir()):
            f = cap_dir / "spec.md"
            if cap_dir.is_dir() and f.is_file():
                try:
                    content = f.read_text(encoding="utf-8").strip()
                except (OSError, UnicodeDecodeError):
                    continue
                if content:
                    parts.append(f"# {cap_dir.name}\n\n{content}")
    except OSError:
        pass
    if not parts:
        return {"found": False, "content": ""}
    return {"found": True, "content": "\n\n---\n\n".join(parts)}


def _validated_spec_name(spec) -> str | None:
    """spec 名 kebab-case 白名单校验（与 get_spec_doc/resolve_spec_dir 同口径）。

    合法返回原名；非法（非字符串/含 ``..``、路径分隔符等穿越片段）返回 None，
    供 count 系列 fail-open 以 0 计（纯展示信号，不阻断摘要）。
    """
    if not isinstance(spec, str) or not _SPEC_NAME_RE.match(spec):
        return None
    return spec


def count_scenarios(project_root, spec_name) -> int:
    """统计 SPEC 各 spec.md 中 Scenario 数量。

    目录解析复用 resolve_spec_dir（活跃优先/归档回退），与 get_spec_doc 的
    文档读取口径一致——归档 SPEC 的场景计数不再恒为 0；spec 完全不存在
    （活跃/归档均无命中）或无 specs 子目录时仍以 0 计（fail-open 纯展示）。
    """
    spec_name = _validated_spec_name(spec_name)
    if spec_name is None:
        return 0
    spec_dir = resolve_spec_dir(project_root, spec_name)
    if spec_dir is None:
        return 0
    specs_dir = spec_dir / "specs"
    if not specs_dir.is_dir():
        return 0
    count = 0
    try:
        for sf in specs_dir.rglob("*.md"):
            try:
                content = sf.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                # 单文件不可读/解码失败跳过该文件，不影响其余文件计数
                # （与 _read_spec_scenarios 逐文件容错口径一致）
                continue
            for line in content.split("\n"):
                if re.match(r"^####\s+Scenario:", line):
                    count += 1
    except (OSError, UnicodeDecodeError):
        pass
    return count


def _load_planned_scenarios(project_root, spec_name) -> "list | None":
    """装载 planner 出题产物场景列表（两个场景计数函数的共享装载助手）。

    读 `.fenix/verify-progress/<spec>/test_scenarios.json`（planner-plan 出题
    产物，分批整体重写），完成 spec 名校验、路径拼接、exists 检查、json 解析、
    dict 解包 scenarios 与列表类型校验后返回场景 list。缺失/损坏/非列表返回
    None——出题进度是纯展示信号，任何解析异常都不阻断摘要（fail-open，
    与 count_scenarios 同风格）；调用侧各自只保留 sum 谓词，读入口径
    （路径迁移、容错分支）只改本处。
    """
    spec_name = _validated_spec_name(spec_name)
    if spec_name is None:
        return None
    pf = Path(project_root) / ".fenix" / "verify-progress" / spec_name / "test_scenarios.json"
    if not pf.exists():
        return None
    try:
        data = json.loads(pf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None
    if isinstance(data, dict):
        data = data.get("scenarios")
    if not isinstance(data, list):
        return None
    return data


def count_generated_scenarios(project_root, spec_name) -> int:
    """统计 planner 已补全的场景数（verification-phase-progress）。

    读 .fenix/verify-progress/<spec>/test_scenarios.json（装载助手
    _load_planned_scenarios，缺失/损坏/非列表以 0 计）。

    口径=「已补全场景数」（steps/assertions 非空才算）：分批落盘强制骨架
    先行（fix-planner-scenarios-batching-hook）后，骨架含全部 id 但无肉，
    若按条数计则骨架落盘瞬间出题条 0→N/N 一次跳；数带肉场景使出题条
    随每 1/3 重写真实爬升。
    """
    data = _load_planned_scenarios(project_root, spec_name)
    if data is None:
        return 0
    return sum(
        1 for sc in data if isinstance(sc, dict) and (sc.get("steps") or sc.get("assertions"))
    )


def count_planned_scenarios(project_root, spec_name) -> int:
    """统计 planner 本轮规划的场景条目总数（骨架含全部 id）。

    读本轮 planner 出题产物 `.fenix/verify-progress/<spec>/test_scenarios.json`
    （装载助手 _load_planned_scenarios，缺失/损坏/非列表以 0 计）的场景条目
    数——这是**「出题 N/M」分母的权威来源**。分批落盘强制骨架先行
    （fix-planner-scenarios-batching-hook）后，骨架即含全部 id（steps/assertions
    空），故骨架落盘瞬间 total 即达最终值，分子（已补全数）随每 1/3 重写爬升，
    done≤total 恒成立。

    ⚠️ 曾误用 count_scenarios（数 specs/<cap>/spec.md 的 `#### Scenario:` 块）作
    分母——但 planner 会把单个 Scenario 按其交付物形态**拆成多形态条目**
    （web/cli/api，见 agents/planner-plan.md 判定树），二者单位不同、数量无
    绑定关系（实测 243/267 个 spec 出现 done>total，如 20/11）；且非「多形态
    验收」类 spec 的 spec.md 根本不含 `#### Scenario:` 块（分母为 0）。
    """
    data = _load_planned_scenarios(project_root, spec_name)
    if data is None:
        return 0
    return sum(1 for sc in data if isinstance(sc, dict))


def spec_generation_progress(project_root, spec_name, entry, vp=None) -> dict | None:
    """出题进度（verification-phase-progress）：场景生成阶段的 N/M 进度。

    场景生成（planner-plan）是验证链主要耗时而后续执行很快——testing 且执行
    进度未产生（verify_total=0）时返回 {"done": 已补全场景数, "total": 本轮规划
    场景条目总数}；其余状态 / 执行已开始 / 尚无场景落盘均返回 None。

    total 与 done **同源**（同一份 test_scenarios.json 的条目数），只是 done 只
    数 steps/assertions 非空的（带肉）。骨架落盘即 total 达终值，done 随每批
    重写爬升，done≤total 恒成立。done>0 才返回（0 场景无进度可言）。
    """
    if entry.get("status") != "testing":
        return None
    if vp is None:
        # 跨组引用（artifacts 组）经门面延迟解析（D4）
        import core.dashboard.data as _facade

        vp = _facade.parse_verify_progress(project_root, spec_name)
    if vp.get("total", 0):
        return None
    done = count_generated_scenarios(project_root, spec_name)
    if not done:
        return None
    return {"done": done, "total": count_planned_scenarios(project_root, spec_name)}
