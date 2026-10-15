# [fenix-ignore:86cf2dca9179] 拆出 _git_try/_write_*_alert/_map_junit_failures_to_nodeids 等叶子族属跨模块抽取：这些符号在本模块编排链十余处调用、且被 tests 按 core.code_fix 路径直接 import，迁移须同步改写全部引用面并冒导入环风险，拆分风险大于收益（同 5afcd68672ca 对批收尾「三元组」的论证口径），维持单模块。
"""code_fix — 自动修复编排车道（add-code-review-auto-fix design D2-D8）。

把代码审查台账（`.fenix/code-review/items.jsonl`）的 `open` 条目按
`admin.code_review_fix.batch_size`（缺省 20）分批，每批派一次 `code-fix`
agent run 在独立 worktree 内修复并提交；框架在该 worktree 上跑全量回归，
通过才 `merge_back` 主树并把该批条目置 `resolved`（`mark_resolved`），
随后自驱动再投递 `checkpoint()` 处理下一批，直至无 `open` 条目。

两路激活（D4）：审查 run 收尾（`run_code_review` 的 inserted>0 时经
`runner._code_fix_orchestrator`）+ 30 分钟 full scan 兜底
（`event_bus._run_full_scan_body` 末尾经 `code_fix_orchestrator`）。
两路汇入同一入口 `CodeFixOrchestrator.checkpoint()`，幂等守卫链保证
同一时刻至多一个 code-fix run。

调度解耦不变量（decouple-codefix-review-lanes Requirement 1）：批派发与
链推进的判据集合**不含**「周期审查 run 在飞」——checkpoint 守卫链
（enabled/单飞/无 open 条目/WIP 预检/回归契约）没有审查在飞否决或等待
条件（09-24 取证定案，运维口径见
`docs/help/12-faq.md`）；与审查的真实资源冲突点
（回归主机级套件锁）由既有锁自然串行。链自驱动推进语义对所有批收尾路径
成立，含延迟批（defer）合回路径——批收尾 wip_gate_blocked 走
`_defer_merge_back` 返回 `consumed` 照常 `_resubmit`；延迟台账合回成功在
`checkpoint` 内联核销后同一次调用继续选批投递（等价 `success` 收尾推进）。

契约要点（design「契约要点」节，实现者必读）：
- **绝不空集合回**：批内零有效产物行或零有效修复（产物行全 skipped /
  worktree 分支相对建树点无提交）→ MUST NOT 合回、MUST NOT 置 resolved
  （`merge_back` 对「分支已是 HEAD 祖先」返回成功，无守卫会把全 skipped
  的批白洗成 resolved）。
- **resolved 只能由合回成功驱动**；skipped 条目保持 open。
- **批失败自愈（add-code-fix-batch-failure-selfheal）**：批收尾三态
  `success`/`consumed`/`halt`——`success` 与 `consumed`（条目已离开可选池）
  均自驱动推进下一批，仅 `halt`（环境性失败）终止链。确定性失败（首轮及
  targeted_retry_max 轮定向重试均失败/合回冲突）现场即弃：branch/tip_sha 入
  `.fenix/code-review/fix-failed.json` 失败档案（记录带 `fail_count` 自动
  重试预算与 `reg_form` 回归终局形态）后清理 worktree 释放锁；新链启动自动
  释放预算内记录（打标墓碑不删除，fail_count 跨链续增，下轮自动重试），达
  生效预算永久跳过并一次性告警 + todo.md 登记待人工。自动重派预算按
  `reg_form` 分档（evo-add-codefix-anomaly-redispatch-budget）：有真实失败
  面（mapped）保持 `FAIL_RETRY_MAX`，零失败面（anomaly，parse_error、
  failed 无明细或 timeout 无明细）降为 `ANOMALY_FAIL_RETRY_MAX`（1）——
  整批重派无证据价值。
  瞬态失败（agent run 失败/重试 run 失败/零有效修复）只进进度快照
  `chain_skipped`（链内跳过，新链启动重置），不烧跨轮重试预算。
"""

import calendar
import dataclasses
import glob
import json
import math
import os
import re
import shlex
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.code_review import (  # noqa: F401
    _logger,
    _now_iso,
    _read_items_unlocked,
    _with_lock,
    fingerprint,
    items_path,
    mark_ignored,
    mark_resolved,
    read_items,
    severity_deferred_open_ids,
    severity_gate_from_config_segment,
    severity_gate_open,
    severity_gate_release_due,
)
from core.agent_runner.provider_circuit import PROVIDER_SWITCH_COOLDOWN_SECONDS
from core.config import ConfigLoader
from core.git_base_branch import resolve_base_branch
from core.verify_contract import RegressionSpec, load_verify_contract

# 进度快照（单文件覆盖式，与 .fenix/regression/last-run.json 同型，D8）
FIX_PROGRESS_REL = ".fenix/code-review/fix-progress.json"
# 失败批档案（确定性失败：两次回归均失败/合回冲突；带 fail_count 自动重试
# 预算，新链启动自动释放预算内记录——add-code-fix-batch-failure-selfheal D3）
FIX_FAILED_REL = ".fenix/code-review/fix-failed.json"
# 延迟合回台账（fix-codefix-wipgate-defer D2）：wip_gate_blocked 批的现场
# 保留记录。独立文件、独立生命周期——失败档案烧预算期待重跑，defer 队列零
# 预算期待原地合回，混写会让释放逻辑误伤 defer 条目。
DEFERRED_REL = ".fenix/code-review/fix-deferred.json"

# 失败档案自动重试预算上限（selfheal D3）：同条目集 fail_count 递增至本值的
# 那次入档发一次性 warning 告警并登记 todo 待人工项，此后不再自动重试。
# 模块常量、不新增配置键（预算语义无需按项目调节）。
FAIL_RETRY_MAX = 3

# 异常形态失败批重派预算（evo-add-codefix-anomaly-redispatch-budget）：回归
# 终局为零失败面（reg_form=anomaly，parse_error、failed 无明细、timeout
# 无明细——枚举单源 _is_regression_anomaly）的失败
# 记录，定向轮无可注入明细、整批重派只会复现同一异常（2026-10-07 夜间
# 24 轮回归全 parse_error、18 个重试轮零收敛实证），预算降为 1——首次入档
# 即达触顶「登记待人工+跳过条目」路径；有真实失败面（mapped，fail_items
# 非空）保持 FAIL_RETRY_MAX。取值单源 _effective_retry_budget，全部
# fail_count 预算比较点 MUST 经它取值。
ANOMALY_FAIL_RETRY_MAX = 1

# 失败记录 reg_form 合法值（evo-add-codefix-anomaly-redispatch-budget）：
# anomaly=回归零失败面（parse_error、failed 无明细、timeout 无明细）；
# mapped=有真实失败面（回归 fail_items 非空）。历史记录缺键按 mapped
# （向后兼容，无迁移）。
REG_FORM_ANOMALY = "anomaly"
REG_FORM_MAPPED = "mapped"

# 延迟批预算双门（fix-codefix-wipgate-defer D6，先到为准）：first_deferred_at
# 起超过 90 分钟，或链边界重试仍被阻断使 defer_count 递增达 6。时间门兜住
# 「链停摆很久后才恢复」的陈旧 defer；次数门兜住「主树反复变脏」的抖动。
DEFER_BUDGET_SECONDS = 90 * 60
DEFER_RETRY_MAX = 6

# LLM 拒绝出口（2026-09-23）：产物行 skipped 且显式标注这些 skip_reason 的
# 条目置台账终态 ignored（mark_ignored），不再跨链重修。其余 skipped（无标注
# 缺省 / unfixable / needs_human）维持既有语义（open + 链内跳过，跨链可重试）
# ——缺省保守：必须显式声明「误报/不值得修」才走硬出口，防 LLM 轻率清账。
IGNORE_ELIGIBLE_SKIP_REASONS = {"false_positive", "not_worth_fixing"}

# 进度缺省态（读侧缺文件/损坏时返回，MUST NOT 抛异常）
FIX_PROGRESS_DEFAULT = {
    "running": False,
    "phase": "idle",
    "total": 0,
    "done": 0,
    "current": "",
    "batch_no": 0,
    "reason": "",
    "activation_id": "",
    # 手动授权旗标（随链身份持久化）：True 表示本链由手动触发授权，自驱动
    # 再投递（_resubmit → checkpoint 无 override）凭它越过 enabled 总开关。
    # 仅在链 live（running=true）时被消费；终态（idle/blocked/failed）清除。
    "manual_authorized": False,
    # 批上下文（add-code-fix-item-level-progress D2）：本批 worktree 绝对路径
    # /run_id/批条目数。编排器在建树成功后、agent run 启动前写入（run_id 预
    # 生成并经 run_code_fix 既有 run_id 形参传入）；批收尾清除。白名单合并
    # 语义要求新键 MUST 进本缺省集（缺省 null），否则读侧不可见、且会被下
    # 一次合并写剥离（先例：manual_authorized）。
    "worktree": None,
    "run_id": None,
    "batch_total": None,
    # 条级进度合成字段（D1，读侧实时派生）：read_progress 每次读时经
    # read_fix_out 现算，write_progress 会剥离、不落盘（避免陈旧快照被合并
    # 写持久化成误导性数字）。null 三态语义见 _synthesize_item_progress。
    "item_done": None,
    "current_item": None,
    # 启动阶段合成字段（add-code-fix-startup-stage-visibility D1，读侧实时
    # 派生）：批处于 fixing/retrying 且 out 零有效行时，读 run 转录末行事件
    # 类型推断 agent 启动阶段。同一剥离纪律（write_progress 不落盘）——合
    # 成快照经合并写持久化会在批收尾后残留陈旧阶段文案。null 三态语义见
    # _synthesize_startup_stage。
    "startup_stage": None,
    # 链内跳过集（add-code-fix-batch-selfheal）：本链因瞬态失败（agent run
    # 失败/重试 run 失败/零有效修复）被跳过的条目 id。select_batch 排除口径
    # = 失败档案并集 ∪ 本字段；新链启动（activation_id 更替）时重置为空。
    "chain_skipped": [],
    # 链级持久 run 清单（evo-add-codefix-digest-cost-metrics 2.2）：本链全部
    # agent run 的 run_id 逐 run 累积。进度文件既有 run_id 字段批收尾即清除、
    # 台账核销记录（mark_resolved）不带 run_id，均不能充当「链内全部 run」
    # 的事实源；链终局 rollup 以本清单逐 run 读 run 归档（先顶层
    # `.fenix/runs/<run_id>.jsonl`，缺失回退 `archive/` 副本）计数，「覆盖
    # 链中全部 run 不漏样本」机械达成。新链启动重置为空。
    "chain_run_ids": [],
    # 链级核销计数（2.1「条目计数与台账核销一致」）：随链累积 mark_resolved /
    # mark_ignored 的真实命中数（终态过滤后），rollup 时点读出即台账口径。
    "chain_resolved": 0,
    "chain_ignored": 0,
    # 链终局 rollup 快照（2.1「随链状态落盘」）：链末批合回成功或链中途终局
    # 时写入（结构见 _emit_chain_rollup）；新链启动不清除——历史链最后的
    # rollup 保持可读，直至被新链终局写点覆盖。
    "chain_rollup": None,
    # 同链冷却态（evo-add-codefix-conn-error-cooldown 2.1/2.2）：批次死于上游
    # 连接类 api_error 时失败收尾写入，checkpoint 投递入口守卫「下一批派发
    # 时刻不早于该 epoch 秒」。持久化（合并写）跨重启仍生效——观测期 daemon
    # 多次重启，内存态会在残余窗口内漏拦（design D4）。null=无冷却；到期后
    # 首个通过守卫的 checkpoint 补写解除告警并把两键清回 null（design D5）。
    "switch_cooldown_until": None,
    # 冷却起点（触发时刻 epoch 秒）：解除告警 evidence 的「实际推迟时长」度量
    # 基准（=首个通过守卫的 checkpoint 时刻 − 本字段）；随冷却态一并清除。
    "switch_cooldown_from": None,
    # 夜间静默窗窗次标识（evo-codefix-night-quiet-window 1.2）：窗次含日期
    # （形如 "2026-10-06"），同窗次武装/解除各至多一次、跨窗次自动重新武装；
    # 残留标识不拦截投递（checkpoint 守卫惰性清理，沿冷却残留态清理先例）。
    # 持久化（合并写）跨重启仍幂等。null=当前无窗次标识。
    "night_quiet_armed_date": None,
    # 武装时窗区间配置原文快照：解除告警 evidence 引用武装时的区间，配置中途
    # 变更/关闭不使解除记录失真；随窗次标识一并清除。
    "night_quiet_armed_text": None,
}


def _progress_path(project_root) -> Path:
    return Path(project_root) / FIX_PROGRESS_REL


def _failed_path(project_root) -> Path:
    return Path(project_root) / FIX_FAILED_REL


def _atomic_write(path: Path, content: str) -> None:
    """临时文件 + fsync + os.replace 原子写（对齐 core.code_review._atomic_write）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{uuid.uuid4().hex[:8]}")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def read_progress(project_root, synthesize: bool = True) -> dict:
    """读取进度快照；缺失/损坏返回缺省态（不抛异常，spec code-fix-progress）。

    返回 dict 的字段集与 FIX_PROGRESS_DEFAULT 一致（缺字段补齐），调用方
    可安全取键。

    条级进度（add-code-fix-item-level-progress）：``running=true`` 且批上下
    文在场时，经 ``read_fix_out`` 实时合成 ``item_done``/``current_item``
    （见 ``_synthesize_item_progress``）；其余场景两键为 null。

    启动阶段（add-code-fix-startup-stage-visibility）：在条级合成之后、
    复用其已读出的 out 行集合激活域互补合成 ``startup_stage``（out 有行时
    短路 null，不重复 IO）。

    ``synthesize=False``（code-review item f0d590fbfeac）：跳过上述两组实时
    合成（省去整本台账与转录尾读的只弃不用读放大），供 ``write_progress``
    合并基线复用——派生字段从不落盘，写点无需现算；缺省 True 读侧语义不变。
    """
    out = dict(FIX_PROGRESS_DEFAULT)
    # 可变缺省字段显式拷贝（code-review item d8f3e5cef688）：chain_skipped 是
    # list，浅拷贝会让所有缺省态调用方共享同一对象——未来任何一处就地 append
    # 都会污染进程级缺省态，使链内跳过集跨链/跨项目泄漏。每次读返回新列表。
    out["chain_skipped"] = list(FIX_PROGRESS_DEFAULT["chain_skipped"])
    # chain_run_ids 同为 list 缺省（evo-add-codefix-digest-cost-metrics 2.2），
    # 同一防共享纪律。
    out["chain_run_ids"] = list(FIX_PROGRESS_DEFAULT["chain_run_ids"])
    try:
        raw = _progress_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        if synthesize:
            rows = _synthesize_item_progress(project_root, out)
            _synthesize_startup_stage(project_root, out, rows)
        return out
    if isinstance(data, dict):
        for k in FIX_PROGRESS_DEFAULT:
            if k in data:
                out[k] = data[k]
    if synthesize:
        rows = _synthesize_item_progress(project_root, out)
        _synthesize_startup_stage(project_root, out, rows)
    return out


def write_progress(project_root, **fields) -> dict:
    """合并式原子写进度（读-改-写：未传字段保留现值，缺省态兜底）。

    幂等安全：进度文件不存在时从缺省态起改。返回写盘后的完整进度。

    读-改-写全程持 flock（``_with_lock``，对齐台账写；code-review item
    b8f54457a0b1）：否则编排器 checkpoint 的 disabled 提示性写点（其
    ``self._lock`` 不覆盖批 worker 线程的本函数调用）可与批 worker 写点
    并发，各自基于旧快照整份覆写、后落盘者剥掉先落盘者刚写入的字段
    （批上下文 worktree/run_id/batch_total 或 phase）。锁文件派生自进度
    文件名，与台账 items.jsonl 锁互不相干；锁内 MUST NOT 再次加同一把锁。
    """
    path = _progress_path(project_root)

    def _do() -> dict:
        # 合并基线免合成直读（code-review item f0d590fbfeac）：item_done/
        # current_item/startup_stage 本就要在下方剥离、从不落盘，写点无需
        # 为它们在每次进度写点重复整本台账与转录尾读。
        current = read_progress(project_root, synthesize=False)
        # 条级合成字段是读侧实时派生值，MUST NOT 落盘：剥离同时防御盘上
        # 历史残留键被合并写持久化成误导性数字（add-code-fix-item-level-
        # progress D1）。
        current.pop("item_done", None)
        current.pop("current_item", None)
        # 启动阶段同纪律（add-code-fix-startup-stage-visibility D1）：批收尾后
        # 进度文件若残留陈旧阶段文案，前端会在非准备期误渲染。
        current.pop("startup_stage", None)
        current.update(fields)
        _atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2))
        return current

    return _with_lock(path, _do)


def _preset_run_id(runner, exclude=()) -> str:
    """预生成 code-fix run_id（与 run_code_fix 缺省生成同口径，task 2.1）。

    编排器在建树成功后、投递 run 前调用：只有预生成才能在 run 启动**前**
    把 run_id 写进进度文件（run 在飞期间读侧即可据此定位 out 文件）；随后
    经 ``run_code_fix(..., run_id=...)`` 传入，run 内部不再自行生成。
    保持 ``code-fix-`` 前缀并按 ``_unique_code_fix_run_id`` 同口径去重（对
    ``_running_agents`` 在飞集 + 主树 out 残留退避）——``_code_fix_running``
    在途判据依赖该前缀。``exclude`` 为本批已 issued 的 run_id 禁用集（重试
    轮传入首轮 run_id：重试产物落同一 worktree，主树残留判据覆盖不到，同
    秒撞名会复用首轮 out 文件、破坏「重试独立文件并集」口径）。函数级
    import 规避装载环（maintenance_runs 属 agent_runner 侧，不反向依赖本
    模块）。
    """
    from core.agent_runner.maintenance_runs import _unique_code_fix_run_id

    return _unique_code_fix_run_id(runner, exclude=exclude)


def _synthesize_item_progress(project_root, progress: dict) -> list:
    """条级进度实时合成（add-code-fix-item-level-progress D1/D3/D4）。

    D5 实证结论（task 1.1；观察方法：最小夹具批 2 条 item，stub `_run_agent`
    模拟 agent 逐条 append+flush 驱动真实 `run_code_fix`，在 run 期间与收尾
    后分别探测 `<worktree>/.fenix/code-review/fix-out-<run_id>.jsonl` 的存在
    性与行数）：
    - out 目录由 `run_code_fix` 在 run 启动时即创建（maintenance_runs
      `out_path.parent.mkdir`），先于 agent 首条处置；
    - agent 逐条追加的每一行在 run 在飞期间即可被 `read_fix_out` 读到
      （实证 mid-run 探测可见行数 1→2 逐条递增）；
    - run 收尾返回后、worktree cleanup 之前文件完整在场。
    故「run 在飞期间实时合成」的路径假设成立；worktree cleanup 后读不到
    out 属预期（批已收尾、批上下文已清，条级字段让位）。

    容错语义（D4 null 三态）：`running != true`、批上下文缺失、out 缺失/
    零有效行、`read_fix_out` 任何异常 → `item_done`/`current_item` 均置
    null（MUST NOT 500、MUST NOT 回退 0/空对象等可被误读的值）。函数无条
    件先置 null 再尝试计算，保证每次 read_progress 输出都携带两键。

    返回本次读出的有效行集合（可能为空）：``read_progress`` 把它转交
    ``_synthesize_startup_stage`` 复用激活域判定（out 有行时后者短路
    null），不重复 IO。
    """
    progress["item_done"] = None
    progress["current_item"] = None
    if progress.get("running") is not True:
        return []
    worktree = progress.get("worktree")
    run_id = progress.get("run_id")
    if not worktree or not run_id:
        return []
    try:
        rows = read_fix_out(worktree, run_id)
    except Exception:  # noqa: BLE001 — 读产物任何异常都兜底为明细不可得
        return []
    if not rows:
        return []
    # item_done：有效行按 item_id 去重（同条目重复追加只计一次，取末次）
    latest: dict = {}
    for row in rows:
        latest[row.get("item_id")] = row
    progress["item_done"] = len(latest)
    # current_item：最近一条有效结果行（D3：title/line 以台账回查补全——
    # 台账是唯一持久化且字段齐全的清单源；匹配失败或台账读异常降级为仅含
    # out 行自带字段 item_id/status/file）。
    last = rows[-1]
    current: dict = {
        "item_id": last.get("item_id"),
        "status": last.get("status"),
        "file": last.get("file"),
    }
    try:
        rec = read_items(project_root).get(last.get("item_id"))
    except Exception:  # noqa: BLE001 — 台账读异常降级，不影响条级计数
        rec = None
    if isinstance(rec, dict):
        current["title"] = rec.get("title")
        if rec.get("line") is not None:
            current["line"] = rec.get("line")
    progress["current_item"] = current
    return rows


# ── 启动阶段推断（add-code-fix-startup-stage-visibility）──────────────

# 转录尾部截读窗口（字节）：流转录可达 MB 级（实测 p90 行 7KB、max 150KB），
# MUST NOT 全量 read_text；取 64KB 是「末行完整在场」与 IO 有界性的折衷——
# 4KB 窗口会把约 16% 的 assistant 行截断成不可解析片段（fail-open null、
# 准备段空白，恰好违背本特性目的），64KB 下截断率 <0.1%，残余退化接受。
_TRANSCRIPT_TAIL_BYTES = 64 * 1024

# 初始化类 system 子类型（D2 词表，实测校准 2026-09-24：system 子类型不止
# 初始化类，还含子代理/后台任务遥测，按 type 整类归「会话初始化中」会在
# 启动窗口误标，故按 subtype 拆分）。
_STARTUP_INIT_SUBTYPES = {"init", "hook_started", "hook_response"}


def _last_transcript_line(path: Path) -> str:
    """尾部截读转录末行（只读末 ``_TRANSCRIPT_TAIL_BYTES`` 字节）。

    末行超出窗口时只能拿到截断片段——解析失败由调用方按「读不到就 null」
    容错（D3），MUST NOT 为补全末行扩大到全量读。
    """
    size = path.stat().st_size
    if size <= 0:
        return ""
    with path.open("rb") as fh:
        fh.seek(max(0, size - _TRANSCRIPT_TAIL_BYTES), os.SEEK_SET)
        chunk = fh.read(_TRANSCRIPT_TAIL_BYTES).decode("utf-8", errors="replace")
    stripped = chunk.rstrip("\n")
    if not stripped:
        return ""
    idx = stripped.rfind("\n")
    return (stripped[idx + 1:] if idx >= 0 else stripped).strip()


def _map_startup_stage(last_line: str) -> str:
    """末行事件 → 阶段短语（D2 映射表）；不可解析返回空串（调用方置 null）。"""
    try:
        event = json.loads(last_line)
    except ValueError:
        return ""
    if not isinstance(event, dict):
        return ""
    etype = event.get("type")
    if etype == "system":
        if str(event.get("subtype") or "") in _STARTUP_INIT_SUBTYPES:
            return "会话初始化中"
        return "agent 启动处理中"
    if etype == "assistant":
        blocks = (event.get("message") or {}).get("content") or []
        if isinstance(blocks, dict):  # 非 list 形态防御（归一为单元素表）
            blocks = [blocks]
        tool_name = ""
        has_text = False
        for block in blocks:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                # 同事件同时含 text/thinking 与 tool_use 时以动作计（正在做事
                # 比仍在分析对用户更有信息量）
                tool_name = str(block.get("name") or "")
                break
            if btype in ("text", "thinking"):
                has_text = True
        if tool_name:
            return f"正在执行 {tool_name}"
        if has_text:
            return "模型分析分组中"
    # user / stderr / result / 未知形态 → 统一「处理中」（D2 末行兜底行）
    return "agent 启动处理中"


def _transcript_waited_minutes(path: Path):
    """已等待分钟数 = 当前时间 − 转录文件 birth time；取不到 birth 返回 None。

    转录为懒创建（首条流事件经 append_run_line 才建文件），birth = 首事件
    到达时刻、非 spawn 时刻，waited 轻度低估（D2 接受）。部分文件系统 stat
    无 birth（Linux ext4 无 st_birthtime）→ None，前端只显示阶段短语。
    """
    st = os.stat(path)
    birth = getattr(st, "st_birthtime", None)
    if not isinstance(birth, (int, float)) or birth <= 0:
        return None
    return max(0, int((time.time() - birth) // 60))


def _synthesize_startup_stage(project_root, progress: dict, out_rows) -> None:
    """启动阶段实时合成（add-code-fix-startup-stage-visibility D1-D3）。

    激活条件（与 ``_synthesize_item_progress`` 激活域互补）：``running=true``
    且 ``phase ∈ {fixing, retrying}`` 且 ``out_rows`` 零有效行——out 有行即
    首条处置已落盘，条级计数接管，本字段短路 null（spec「处置开始后收敛」）。

    字段形态：``null | {"stage": str, "waited_minutes": int|null}``（恒带
    键）；文件缺失 → 「等待 agent 进程启动」（waited null）；末行不可解析
    → null（MUST NOT 伪造阶段文案）。

    容错硬要求（D3 fail-open）：文件缺失 / 读取异常 / 末行非 JSON / 无
    type 键 → 置 null，任何分支不得抛异常中断 ``read_progress``（读侧
    MUST NOT 500 既有口径）。函数无条件先置 null 再计算。
    """
    progress["startup_stage"] = None
    if progress.get("running") is not True:
        return
    if progress.get("phase") not in ("fixing", "retrying"):
        return
    if out_rows:
        return
    run_id = progress.get("run_id")
    if not run_id:
        return
    try:
        path = Path(project_root) / ".fenix" / "runs" / f"{run_id}.jsonl"
        if not path.is_file():
            progress["startup_stage"] = {
                "stage": "等待 agent 进程启动",
                "waited_minutes": None,
            }
            return
        stage = _map_startup_stage(_last_transcript_line(path))
        if not stage:
            return
        progress["startup_stage"] = {
            "stage": stage,
            "waited_minutes": _transcript_waited_minutes(path),
        }
    except Exception:  # noqa: BLE001 — 启动阶段推断是尽力而为语义，不炸主流程
        progress["startup_stage"] = None


# ── run 归档指标行（evo-add-codefix-digest-cost-metrics 2.2）──────────


def _read_run_metrics(project_root, run_id: str) -> dict:
    """读 run 归档末条 run_metrics 行：先顶层，缺失回退归档副本。

    双路径定位（对齐 ``admin_monitor._admin_run_file`` 仓内先例）：先顶层
    ``.fenix/runs/<run_id>.jsonl``，缺失回退 ``.fenix/runs/archive/<run_id>.jsonl``
    ——daemon 每 300 秒 runs retention 清理把终态 run 移入 ``archive/``，
    code-fix 链横跨数小时，链终局时除末批外的 run 顶层必然早已移档，单路径
    读取曾致链级 rollup 的 turns 恒零（fix-codefix-rollup-archive-read）。
    取末条——同 run 多次落 metrics 行（resume/重跑追加）时以后写者为准。

    归零语义收窄为「顶层与归档两处皆缺」；文件不可读/损坏行/无 metrics 行
    （旧转录或 run 未跑到收尾）同样空 dict：rollup 按零贡献计，MUST NOT 炸
    链终局（fail-open 保留）。
    """
    runs_dir = Path(project_root) / ".fenix" / "runs"
    for path in (runs_dir / f"{run_id}.jsonl",
                 runs_dir / "archive" / f"{run_id}.jsonl"):
        last: dict = {}
        try:
            # 二进制读 + 逐行 decode(errors="replace")（code-review item
            # ba3af64dc703，对齐 read_fix_out 同款解码容错）：坏字节 run 归档
            # 只废坏行（json 解析失败按既有 continue 跳过），MUST NOT 让
            # UnicodeDecodeError 沿 _chain_recent_duration_mean → 夜静默窗判定
            # 的 checkpoint 主链路上抛中断本轮投递。
            with path.open("rb") as fh:
                for raw in fh:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(rec, dict) and rec.get("type") == "run_metrics":
                        last = rec
        except OSError:
            continue
        if last:
            return last
    return {}


# ── 失败批保留集合（5.7 / D6）──────────────────────────────────────────


def load_failed_batches(project_root) -> list:
    """读取失败批保留集合；文件不存在/损坏视为空集（不阻塞车道）。"""
    try:
        raw = _failed_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [rec for rec in data if isinstance(rec, dict)]
    return []


def _record_item_ids(rec, logger=None, where="") -> list:
    """失败档案/延迟台账记录 ``item_ids`` 字段形态守卫（code-review item
    c669b83acf2c）。

    外部直改坏档（``item_ids`` 被写成非列表标量，如 int）直接迭代会抛
    TypeError——``_failed_item_ids`` 在 select_batch 的调用点、
    ``_deferred_item_ids`` 在 checkpoint 的调用点均无兜底，异常上穿会中断
    本轮投递（车道停摆直至档案修复）；被写成非空字符串则被逐字符拆成假
    item_id 并入排除集。比照同文件 chain_skipped/chain_run_ids 守卫
    （item 3f883a9ac93c / 959c61f66ce3）同款「先判 isinstance(list) 再拷贝」
    纪律：非列表回退空列表，truthy 垃圾值经 ``logger``（AdminStore 风格
    ``logger.warning(channel, msg)``，可 None）留痕后丢弃——无 logger 的
    读侧调用形态静默回退（与 load_failed_batches 损坏按空列表同哲学）。
    """
    raw = rec.get("item_ids")
    if isinstance(raw, list):
        return list(raw)
    if raw and logger is not None:
        try:
            logger.warning(
                "code-fix",
                f"code-fix {where}item_ids 字段形态异常（非列表："
                f"{type(raw).__name__}），按空列表容错",
            )
        except Exception:  # noqa: BLE001 — 留痕失败不影响容错主流程
            pass
    return []


def _failed_item_ids(project_root) -> set:
    """失败保留集合中**在档**记录的全部 item_id 并集（select_batch 排除源）。

    已释放的墓碑记录（``released=true``，见 ``release_retryable_failed_batches``）
    不参与排除——释放即条目重回可选池（下轮自动重试）；``fail_count`` 预算由
    墓碑保留，供同条目集跨链再次失败时递增（达上限永久跳过的判据）。
    """
    ids: set = set()
    for rec in load_failed_batches(project_root):
        if rec.get("released"):
            continue
        for iid in _record_item_ids(rec):
            if isinstance(iid, str):
                ids.add(iid)
    return ids


def _fail_count_int(value) -> int:
    """失败档案 ``fail_count`` 类型容错解析（code-review item 4ac4bea334b2）。

    仅 None/空值/解析失败按缺省 1 兜底，可解析数值（含 0）原样返回——
    数值 0 与字符串 "0" 两种落盘形态同归 0，不再因 truthy 分叉（code-review
    item 003716278b45）。非数值字符串按缺省 1 处理，MUST NOT 让 ValueError
    穿透炸掉 checkpoint 的「选批为空」收敛出口。
    """
    if value is None or value == "":
        return 1
    try:
        return int(value)
    except (TypeError, ValueError):
        return 1


def _record_reg_form(rec) -> str:
    """失败记录回归终局形态归一化（evo-add-codefix-anomaly-redispatch-budget）。

    合法值 ``anomaly``（零失败面）/ ``mapped``（有真实失败面）；缺键（本
    spec 上线前的历史记录）或外部直改的非法值一律按 ``mapped``——旧档案
    沿用既有 FAIL_RETRY_MAX 预算，不因缺键报错、不分档（design：读取兼容）。
    """
    form = str(rec.get("reg_form") or "")
    return form if form in (REG_FORM_ANOMALY, REG_FORM_MAPPED) else REG_FORM_MAPPED


def _effective_retry_budget(rec) -> int:
    """失败记录按回归终局形态取生效自动重派预算（分档单源）。

    anomaly → ``ANOMALY_FAIL_RETRY_MAX``（1）；mapped（含缺键兼容）→
    ``FAIL_RETRY_MAX``。全部 fail_count 预算比较点（record_failed_batch
    触顶、release 释放、链收敛 maxed 判定）MUST 经本函数取值：release 侧
    缺分档会把预算已耗尽的 anomaly 记录当预算内释放回池（分档被旁路）；
    触顶侧缺分档会让 anomaly 记录悬为「墓碑保留但永不重派」且无人工项。
    """
    return (
        ANOMALY_FAIL_RETRY_MAX
        if _record_reg_form(rec) == REG_FORM_ANOMALY
        else FAIL_RETRY_MAX
    )


def _open_ids_for_archive(root, item_ids) -> list:
    """失败档案入档前的未终态条目过滤（code-review item be772fa66cb7，收口
    c94a1770a477 在各失败收尾路径的同口径要求）：只收 ``status=="open"``
    条目——选批到失败收尾之间被人工置终态（resolved/in_spec/ignored）的
    条目不随批入档、不进一次性告警名录，``fail_count`` 预算与真实失败条目
    一致；台账读失败按空集（不入档）。``record_failed_batch`` 的
    reason/detail_ref 等差异留在各调用点。
    """
    try:
        ledger = read_items(root)
    except Exception:  # noqa: BLE001 — 台账读失败按空集（不入档）
        ledger = {}
    return [
        i for i in item_ids
        if (ledger.get(i) or {}).get("status") == "open"
    ]


def record_failed_batch(
    project_root, item_ids, worktree, reason="", branch="", tip_sha="",
    detail_ref="", logger=None, reg_form="", reg_detail=None,
) -> None:
    """把确定性失败批落盘到 fix-failed.json（原子写；同条目集复用记录）。

    自动重试预算语义（add-code-fix-batch-failure-selfheal D3/D4）：记录带
    ``fail_count``——首记 1；同条目集（item_id 集合相同）再次入档时复用既有
    记录递增并刷新 ``reason``/``branch``/``tip_sha``/``failed_at``（不追加
    重复记录）。新链启动经 ``release_retryable_failed_batches`` 自动释放
    预算内记录（打标墓碑、预算保留，下轮自动重试）；同条目集此后再次失败
    即复燃墓碑并续增——``fail_count`` 递增至生效预算的那次入档发一条一次性
    warning 告警并在 todo.md 登记待人工项，此后永久跳过、不再重试/告警。
    预算按 ``reg_form`` 分档（evo-add-codefix-anomaly-redispatch-budget）：
    anomaly 取 ``ANOMALY_FAIL_RETRY_MAX``、mapped 取 ``FAIL_RETRY_MAX``，
    取值单源 ``_effective_retry_budget``。

    ``reg_form``（可选）：回归终局形态（``anomaly``=parse_error、failed
    无明细或 timeout 无明细、零失败面；``mapped``=回归 fail_items 非空）。
    调用方提供合法值
    即刷新——同条目集复燃合档以最近一次失败为准（修复质量好转后自动回到
    mapped 预算）；未提供（如 ``merge_back_conflict`` 收口，非回归终局）
    不写键，读取侧按 mapped 兼容（历史记录缺键同口径，不分档不报错）。
    ``reg_detail``（可选）：入档时刻的重试收敛事实快照（anomaly_streak、
    实际执行定向轮数、是否熔断触发），随最近一次失败整体刷新。

    ``reason``/``branch``/``tip_sha`` 为可选关键字参数（缺省空串，兼容既有
    调用点）；``branch``/``tip_sha`` 是现场即弃后修复提交的 git 追溯线索。
    ``detail_ref``（add-codefix-targeted-retry 4.4，可选）：最后一轮回归
    失败用例明细文件引用（``.fenix/code-review/`` 相对路径，供事后审计；
    add-regression-auto-fix 复发重开亦以明细为对账源）。
    ``worktree`` 形参仅为兼容既有调用点保留，MUST NOT 落盘（现场即弃后该
    路径写入几秒即失效且无读者，追溯以 branch/tip_sha 为准，code-review
    item a0e268c1f1c1），记录中恒为 null。

    读-改-写全程持 flock（``_with_lock``，code-review item fd1dc2a59820，
    对齐 ``write_progress``/``reopen_regression_items`` 同文件先例）：与
    链边界自动操作（新链启动释放）及人工 ``release_failed_batch`` 的并发
    交叠会丢更新。``logger``（可选）供达上限一次性告警拒写时留痕。
    """
    path = _failed_path(project_root)
    hit_max = False
    budget = FAIL_RETRY_MAX
    fire_budget_alert = False

    def _do() -> None:
        nonlocal hit_max, budget, fire_budget_alert
        records = load_failed_batches(project_root)
        key = {str(i) for i in item_ids}
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        target = None
        for rec in records:
            if {str(i) for i in _record_item_ids(rec, logger=logger, where="失败档案记录 ")} == key:
                target = rec
                break
        if target is not None:
            # fail_count 容错解析收敛 _fail_count_int 单源（外部直改非数值/
            # 缺失按缺省 1 递增，MUST NOT 让 ValueError 穿透炸掉批收尾入档）。
            target["fail_count"] = _fail_count_int(target.get("fail_count")) + 1
            # 墓碑复燃（code-review item 931df4af59cc）：预算内释放只打标不删除，
            # 同条目集再次入档即清标回到在档排除态、fail_count 跨链续增——否则
            # 墓碑留存会让本递增分支不可达，每链都重新以 fail_count=1 建档，
            # 达上限告警/todo/永久跳过永不发生（确定性失败批无限重试）。
            target.pop("released", None)
            target.pop("released_at", None)
            # 复燃同时清核销记账（add-codefix-failure-registration-closeout
            # 1.1）：记录重新活跃即回到未核销——否则已核销标记与再次失败
            # 事实矛盾，且对账因 consumed_at 在场跳过该记录（open_remaining
            # 永不再同步）。
            target.pop("consumed_at", None)
            target.pop("consumed_note", None)
            target.pop("open_remaining", None)
        else:
            target = {"item_ids": list(item_ids), "fail_count": 1}
            records.append(target)
        # 回归终局形态入档（分档预算依据，evo-add-codefix-anomaly-redispatch-
        # budget）：仅合法值刷新（未提供不写键），合档以最近一次失败为准。
        if reg_form in (REG_FORM_ANOMALY, REG_FORM_MAPPED):
            target["reg_form"] = reg_form
        if reg_detail:
            target["reg_detail"] = dict(reg_detail)
        target["worktree"] = None
        target["reason"] = reason
        target["branch"] = branch
        target["tip_sha"] = tip_sha
        target["detail_ref"] = detail_ref
        target["failed_at"] = now
        # 触顶判定按生效预算分档（evo-add-codefix-anomaly-redispatch-budget
        # 1.2）：anomaly 记录预算 1——首记 fail_count=1 即触顶（登记待人工 +
        # 此后不再自动重派），否则记录悬为「墓碑保留但永不重派」的无告警
        # 悬挂态。分档切换（历史 mapped 计数被合档保留、最近一次失败转
        # anomaly，fail_count 已越顶）时 == 判定不可达 → 超调兜底：未发过
        # 触顶告警（budget_alerted 一次性标记）即补触发一次，防同款悬挂。
        budget = _effective_retry_budget(target)
        already_alerted = bool(target.get("budget_alerted"))
        hit_max = (
            target["fail_count"] == budget
            or (target["fail_count"] > budget and not already_alerted)
        )
        if hit_max and not already_alerted:
            # 触顶告警一次性标记（判重在本记录上）：既有告警通道与
            # AdminStore 去重白名单均无对相关 signal_type 的指纹去重，
            # 超调兜底 MUST 依赖记录标记防重复触发。锁内置位、随本写入
            # 原子落盘，告警本体在锁外发送（AdminStore/todo 异锁）。
            target["budget_alerted"] = True
            if _record_reg_form(target) == REG_FORM_ANOMALY:
                # anomaly 形态降档/停派一次性告警（1.3）在锁外补发。
                fire_budget_alert = True
        _atomic_write(
            path,
            json.dumps(records, ensure_ascii=False, indent=2),
        )

    # 锁内只有本文件读-改-写（MUST NOT 重入同一把锁）；告警/todo 写走
    # AdminStore/todo 通道（异锁），保持锁外。
    _with_lock(path, _do)
    if hit_max:
        # 递增至生效预算的「那次入档」才告警 + 登记 todo（一次性，D4）；
        # 预算内入档可自动重试，不产生人工项。文案按生效预算动态呈现
        # （anomaly 分档为 1，不误导为 FAIL_RETRY_MAX 轮）。
        _write_retry_exhausted_alert(
            project_root, item_ids, reason, branch, tip_sha,
            budget=budget, logger=logger
        )
        _append_todo_entry(
            project_root, item_ids, reason, branch, tip_sha, budget=budget
        )
    if fire_budget_alert:
        # 异常形态降档/停派一次性告警（evo-add-codefix-anomaly-redispatch-
        # budget 1.3）：复用 write_regression_failed_alert 通道，一次性由
        # 上方锁内置位的 budget_alerted 记录标记判重；与既有每次失败的
        # 常规收口告警（批收尾按次发送）并存。
        _write_anomaly_budget_alert(
            project_root, item_ids, reason, branch, tip_sha, logger=logger
        )


# ── 回归失败明细结构化落盘（add-codefix-targeted-retry 1.1/1.2）──────────


FIX_REG_FAILURES_DIR = ".fenix/code-review"
# targeted_retry_max 缺省（design D4 / tasks 2.4）：与
# ConfigLoader.get_code_review_fix_config 的回退值同源。
TARGETED_RETRY_MAX_DEFAULT = 3
TARGETED_RETRY_MAX_MIN = 1
TARGETED_RETRY_MAX_MAX = 5


def fix_reg_failures_relpath(run_id: str) -> str:
    """失败明细文件相对主树路径（每轮回归一份、文件名含该轮回归 run_id）。"""
    return f"{FIX_REG_FAILURES_DIR}/fix-reg-failures-{run_id}.json"


# 明细保留份数（code-review item 36bd1d38eaa6）：每轮回归非 passed 各落一份
# 且全链路只写不清（runs retention 只覆盖 .fenix/runs），长期运行文件数无上
# 界累积成孤儿；写点顺带按 mtime 淘汰最旧、保留最近 N 份。明细是审计辅助件
# 非门禁（失败档案 detail_ref 只引用最后一轮），淘汰历史轮不影响链路正确性。
FIX_REG_FAILURES_KEEP = 20


def _prune_fix_reg_failures(project_root) -> None:
    """明细 retention：按 mtime 只保留最近 ``FIX_REG_FAILURES_KEEP`` 份。

    容错口径：glob/stat/unlink 任一 OSError 只放弃本轮清理，MUST NOT 上抛
    炸写点主流程（明细落盘本已成功，retention 是附属维护动作）。
    """
    try:
        files = sorted(
            (Path(project_root) / FIX_REG_FAILURES_DIR).glob(
                "fix-reg-failures-*.json"
            ),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in files[FIX_REG_FAILURES_KEEP:]:
            stale.unlink()
    except OSError:
        return


def write_fix_reg_failures(project_root, run_id: str, items, fallback_full: bool,
                           long_tests=None, progress_log_tail=None) -> str:
    """回归失败用例明细落盘（返回相对路径引用，1.1/1.2）。

    写入点 = 每轮回归非 passed 时（首轮全量与每个定向轮子集回归各落一份，
    文件名含该轮回归 run_id），供重试注入、失败档案引用（最后一轮明细）与
    轮次演进审计。结构 ``{items, source_run_id, created_at, fallback_full}``；
    映射失败时 ``fallback_full=True``（items 尽力保留原始摘要、无 nodeid 映射
    结果即空列表），重试侧据此回退全量（fail-closed）。落盘失败只记日志不炸
    批（审计辅助件，非门禁）。

    进度证据可选键（evo-codefix-zero-face-regression-hardening 1.3，向后
    兼容——仅在证据在场时写入，既有消费方 items/fallback_full 不受影响）：
    ``long_tests``（超阈值用例名+耗时，来自回归快照）与
    ``progress_log_tail``（junit.xml.log 尾段，long_tests 缺失时的次选）。
    timeout/total=0 形态的明细档借此保留毒化源定位线索，worktree 清理后
    证据仍可回收。
    """
    payload = {
        "items": list(items or []),
        "source_run_id": str(run_id),
        "created_at": _now_iso(),
        "fallback_full": bool(fallback_full),
    }
    if long_tests:
        payload["long_tests"] = list(long_tests)
    if progress_log_tail:
        payload["progress_log_tail"] = str(progress_log_tail)
    rel = fix_reg_failures_relpath(run_id)
    path = Path(project_root) / rel
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write(
            path, json.dumps(payload, ensure_ascii=False, indent=2),
        )
    except OSError:
        return ""
    _prune_fix_reg_failures(project_root)
    return rel


def _map_junit_failures_to_nodeids(failures, exec_root=None):
    """junit 失败用例 → 结构化明细 ``([{nodeid, summary}], ok)``（1.1/1.2，D1）。

    nodeid 以 junit ``classname`` **主导**重构（pytest junitxml 的 testcase
    不产 ``file`` 属性属预期形态，MUST NOT 因此判映射失败）：

    - classname 点分段序列按「最长模块前缀」拆分——前缀转文件路径
      （``tests.test_x`` → ``tests/test_x.py``），余下段作 ``::`` 类链，
      末接 ``::name``：``tests.test_x.TestFoo`` + ``test_bar`` →
      ``tests/test_x.py::TestFoo::test_bar``。
    - 模块边界判定：``exec_root`` 提供时以 ``<modpath>.py`` 文件存在性为准
      （回归刚在该根跑过、测试文件必然在盘）；唯一边界命中才可映射，多个
      前缀同时命中（如 ``a.py`` 与 ``a/b.py`` 并存）视为歧义。``exec_root``
      缺省 None 时退化启发式（首个大写开头段起为类链，无则整段为模块；
      首段即大写视为无模块段、判映射失败）。
    - ``file`` 属性存在（非空）时参与一致性校验：与重构文件路径不一致 →
      该用例映射失败。
    - classname 缺失/空、非 Python 模块形态、歧义、任一用例映射失败 →
      整体判失败（``ok=False``）——子集 MUST 覆盖全部失败用例，漏一个即
      漏修一个；调用方据此回退全量重试（fail-closed）。
    """
    items = []
    exec_root_path = Path(exec_root) if exec_root else None
    for f in failures or []:
        if not isinstance(f, dict):
            return [], False
        classname = str(f.get("classname") or "").strip()
        name = str(f.get("name") or "").strip()
        if not classname or not name:
            return [], False
        segs = classname.split(".")
        if any(not s or not s.isidentifier() for s in segs):
            # 非 Python 标识符形态（如 Java 形态 junit 或宿主路径）
            return [], False

        def _mod_file(mod_segs):
            return "/".join(mod_segs) + ".py"

        boundary = None
        if exec_root_path is not None:
            for k in range(len(segs), 0, -1):
                cand = exec_root_path / _mod_file(segs[:k])
                if cand.is_file():
                    if boundary is not None:
                        # 多个前缀同时对应在盘文件：重构结果歧义
                        return [], False
                    boundary = k
            if boundary is None:
                return [], False
        else:
            boundary = len(segs)
            for i, s in enumerate(segs):
                if s[:1].isupper():
                    boundary = i
                    break
            if boundary == 0:
                # 首段即大写（classname 无模块段，如 "TestFoo"）：模块文件
                # 段为空会把 nodeid 拼成 ".py::TestFoo::..." 畸形形态，进
                # subset_nodeids 会使子集回归收集失败——与「非 Python 模块
                # 形态」分支同口径判映射失败，调用方回退全量（fail-closed）。
                # （code-review item 05c09cc68333）
                return [], False

        rel_file = _mod_file(segs[:boundary])
        cls_chain = segs[boundary:]
        nodeid = rel_file + "".join(f"::{s}" for s in cls_chain) + f"::{name}"

        file_attr = str(f.get("file") or "").strip()
        if file_attr:
            # file 属性存在才参与校验（pytest 不产该属性属预期形态）
            norm_attr = file_attr.replace("\\", "/").lstrip("./")
            if norm_attr != rel_file:
                return [], False

        summary = str(f.get("message") or f.get("kind") or "")[:200]
        items.append({"nodeid": nodeid, "summary": summary})
    return items, True


def _snapshot_failures_for_mapping(failures):
    """回归快照 failures 的映射输入归一（喂侧剥离 ``file`` 键）。

    快照 ``file`` 是 ``parse_junit_xml``/``_resolve_file`` 的点分 classname
    兜底（pytest junitxml 不产 file 属性属预期形态），原样喂
    ``_map_junit_failures_to_nodeids`` 会被其 file 一致性校验判不一致、
    映射恒失败（点分 ≠ 路径 → 整体 ``ok=False`` → fallback_full）——对齐
    ``map_snapshot_issues_to_nodeids`` 已验证的规避方式：喂映射前剥离
    ``file`` 键（属性缺失即免检，零信息损失；真 file 属性形态本就不存在
    于本项目回归快照，非 Python 标识符 classname 仍走既有 fail-closed）。

    - 逐条浅拷贝返回**新列表**，MUST NOT 原地修改传入列表及其条目
      （快照同源供展示/落盘）。
    - 非 dict 条目原样透传，交由映射函数既有 fail-closed 判。
    """
    entries = []
    for e in failures or []:
        if not isinstance(e, dict):
            entries.append(e)
            continue
        entries.append({k: v for k, v in e.items() if k != "file"})
    return entries


def map_snapshot_issues_to_nodeids(snapshot, exec_root=None):
    """回归快照异常用例 → 定向子集 nodeids（add-regression-issues-rerun 1.3）。

    公开薄封装，供 daemon 消费端（fenixd._check_regression_requests 的
    ``scope=="issues"`` 分支）复用 targeted-retry 的 nodeid 重构：快照
    ``failures``（失败+错误）+ ``long_tests``（长耗时）构造映射条目，交给
    ``_map_junit_failures_to_nodeids`` 做 classname 主导重构。

    - 映射条目 **剥离 ``file`` 键**：本项目 pytest junitxml 不产 file 属性、
      快照 file 是 ``_resolve_file`` 的点分 classname 兜底（如
      ``tests.test_knowledge_audit``），带入会被 file 一致性校验判不一致、
      映射恒失败；file 属性缺失本就是预期形态，剥离零信息损失（非 Python
      标识符形态 classname 本就判失败回全量）。
    - long_tests 条目补 ``kind: "long"``（摘要回退取 kind）。
    - 按 nodeid 去重（failures 与 long_tests 可能同一用例），保持稳定顺序
      （failures 在前、long_tests 次之，同源遍历序）。
    - 整体 fail-closed：任一条目不可映射（缺 classname / 非 dict 条目 /
      非 Python 形态 / 在盘探测歧义或缺失）→ ``(空或部分?, ok=False)``
      ——子集 MUST 覆盖全部异常用例，漏一例即漏跑一例，调用方据此回退
      全量。映射成功但异常用例为零 → ``([], True)``（结果空由调用方按
      回退全量处置）。

    返回 ``(nodeids, ok)``：nodeids 为去重后的有序 nodeid 列表（ok=True 时
    才可采信）；snapshot 非 dict / 快照键非列表时同样 fail-closed。
    """
    if not isinstance(snapshot, dict):
        return [], False
    failures = snapshot.get("failures")
    long_tests = snapshot.get("long_tests")
    if failures is not None and not isinstance(failures, list):
        return [], False
    if long_tests is not None and not isinstance(long_tests, list):
        return [], False

    entries = []
    for src, default_kind in ((failures, None), (long_tests, "long")):
        for e in src or []:
            if not isinstance(e, dict):
                # 非 dict 条目交由 _map_junit_failures_to_nodeids 判整体失败
                entries.append(e)
                continue
            entry = {k: v for k, v in e.items() if k != "file"}
            if default_kind is not None:
                entry.setdefault("kind", default_kind)
            entries.append(entry)

    items, ok = _map_junit_failures_to_nodeids(entries, exec_root=exec_root)
    if not ok:
        return [], False
    deduped: dict = {}
    for item in items:
        deduped.setdefault(item["nodeid"], item)
    return list(deduped), True


def _merge_failure_items(cumulative, items):
    """轮间累计明细合并（2.3）：按 nodeid 去重，后轮摘要覆盖前轮。"""
    merged = {i["nodeid"]: i for i in cumulative}
    for i in items:
        merged[i["nodeid"]] = i
    return list(merged.values())


# junit.xml.log 尾段留存上限（evo-codefix-zero-face-regression-hardening
# 1.3）：逐用例进度日志只取尾部窗口——毒化源信息集中在收尾段（最后进度
# 标记/中止点），防超长日志撑爆明细档。
REG_PROGRESS_LOG_TAIL_BYTES = 8192


def _collect_reg_progress_evidence(reg, exec_root):
    """回归进度证据提取（evo-codefix-zero-face-regression-hardening 1.3）。

    timeout/total=0 形态的明细档本无 items 可看，毒化源定位全靠根治提交
    事后自述——把 regression 侧已采集的进度证据并入明细档，使其在
    worktree 清理（``_safe_cleanup`` 物理销毁快照与日志）后仍可回收：

    - 首选快照 ``long_tests``（regression.extract_long_tests 已在
      timeout/failed 路径采集：超阈值用例名+耗时，含通过的），规整为
      ``{name, time}`` 列表（字段缺失容错：非 dict/缺 name 的条目跳过）；
    - 缺失或为空时次选 junit.xml.log 尾段（逐用例进度日志，路径由快照
      ``output`` 相对 ``exec_root`` 推导、XML 同名 + ``.log``）。

    返回 ``(long_tests, log_tail)``：两者皆缺 → ``(None, None)``——明细档
    保持现形态（不新增空键，向后兼容）；全程 MUST NOT 抛异常（审计辅助
    件，非门禁）。
    """
    snapshot = getattr(reg, "snapshot", None) or {}
    raw = snapshot.get("long_tests")
    if isinstance(raw, list) and raw:
        long_tests = []
        for t in raw:
            if not isinstance(t, dict):
                continue
            name = str(t.get("name") or "").strip()
            if not name:
                continue
            long_tests.append({"name": name, "time": t.get("time")})
        if long_tests:
            return long_tests, None
    output_rel = str(snapshot.get("output") or "")
    if output_rel and exec_root:
        log_path = Path(exec_root) / (output_rel + ".log")
        try:
            with log_path.open("rb") as fh:
                fh.seek(0, 2)
                size = fh.tell()
                fh.seek(max(0, size - REG_PROGRESS_LOG_TAIL_BYTES))
                tail = fh.read().decode("utf-8", errors="replace")
        except OSError:
            tail = ""
        if tail:
            return None, tail
    return None, None


def _ingest_failure_round(root, reg, cumulative, exec_root):
    """单轮回归失败明细的提取 → 累计合并 → 落盘（1.1/1.2/2.3）。

    写入点 = 每轮回归非 passed 时（首轮全量与每个定向轮子集回归各一份）。
    返回 ``(fail_items, mapped, detail_rel, cumulative)``：``mapped=False``
    表示映射失败/无明细（fallback_full，重试侧回退全量）；``detail_rel``
    为落盘文件相对路径（落盘失败为空串）。落盘同时并入回归进度证据
    （long_tests，缺失时次选 junit.xml.log 尾段）——必须在 worktree 清理
    前完成，清理后证据物理销毁。
    """
    snapshot = getattr(reg, "snapshot", None) or {}
    raw_failures = snapshot.get("failures") or []
    # 喂映射前经归一入口剥离点分 file 兜底（fix-codefix-mapping-dotted-
    # file-poison 1.2）：原样喂会被 file 一致性校验恒判失败 → fallback_full。
    fail_items, mapped = _map_junit_failures_to_nodeids(
        _snapshot_failures_for_mapping(raw_failures), exec_root=exec_root)
    if mapped and fail_items:
        cumulative = _merge_failure_items(cumulative, fail_items)
    else:
        # 映射失败，或无结构化明细（timeout/parse_error/零 failure 记录）：
        # 子集无从谈起，按 fallback_full 走全量 + 旧式摘要注入。
        mapped = False
    long_tests, log_tail = _collect_reg_progress_evidence(reg, exec_root)
    detail_rel = write_fix_reg_failures(
        root, getattr(reg, "run_id", "") or "unknown",
        fail_items if mapped else [], fallback_full=not mapped,
        long_tests=long_tests, progress_log_tail=log_tail,
    )
    return fail_items, mapped, detail_rel, cumulative


# 回归异常熔断阈值（add-codefix-parse-error-breaker D2）：同批内回归异常类
# 失败（parse_error、failed 且无可用明细，及 evo-codefix-zero-face-regression-
# hardening 1.1 起的 timeout 无明细）连续达到该次数即提前终止定向
# 重试循环。熔断是防烧钱的保守兜底而非调优旋钮，按项目约定不进受管配置
# （新增配置键须连带 Dashboard 界面）；与 targeted_retry_max 轮数上限正交
# ——未触发时既有轮数上限行为逐位不变。阈值按形态取值（1.2）：timeout
# 经 _anomaly_breaker_threshold 取 1，parse_error/failed 维持本值。
REGRESSION_ANOMALY_BREAKER_THRESHOLD = 2

# timeout 零失败面熔断阈值（evo-codefix-zero-face-regression-hardening 1.2）：
# 该形态单轮固定烧满回归墙钟（本项目 1800s，2026-10-08 三批 10 轮每轮恰好
# 相差 1800s 实证）且产不出任何证据，盲跑重试期望损失为负——首记即收口
# （阈值 1）；parse_error/failed 保留阈值 2（形态在批内第二轮才定位，保守
# 兜底语义不变）。取值单源 _anomaly_breaker_threshold，两个计数点（首轮
# 全量回归与定向轮回归）MUST 经它取阈值。
ANOMALY_BREAKER_TIMEOUT_THRESHOLD = 1


def _anomaly_breaker_threshold(status: str) -> int:
    """按回归形态取熔断阈值（1.2）：timeout 首记即收口，其余维持既有阈值。"""
    return (
        ANOMALY_BREAKER_TIMEOUT_THRESHOLD
        if status == "timeout" else REGRESSION_ANOMALY_BREAKER_THRESHOLD
    )


def _is_regression_anomaly(reg, fail_items) -> bool:
    """回归异常判据（add-codefix-parse-error-breaker D1）：回归未产出可用明细。

    ``parse_error``（junit 缺失/不可解析，``fail_items`` 恒空）、``failed``
    且明细为空（junit 可解析但零失败记录，同样不可注入）、或 ``timeout``
    且无可用明细（evo-codefix-zero-face-regression-hardening 1.1：硬超时
    中止，整批重派只会复现同一异常且无证据价值）→ True；真实测试失败
    （``failed``/``timeout`` 且明细非空）→ False——MUST NOT 进熔断计数
    （调用方同时清零计数）。
    """
    status = getattr(reg, "status", "")
    if status == "parse_error":
        return True
    return status in ("failed", "timeout") and not fail_items


def _anomaly_round_form(reg, mapped, fail_items) -> str:
    """熔断日志用单轮明细形态标签（tasks 2.1：WARNING 含各轮触发判据）。"""
    form = (
        f"明细 {len(fail_items)} 例"
        if mapped and fail_items else "无可用明细（fallback_full）"
    )
    return f"status={getattr(reg, 'status', '')}，{form}"


def _render_targeted_retry_brief(items) -> str:
    """定向轮注入文本（2.2/2.3）：累计失败明细 + 只修失败相关的硬指令。"""
    lines = [
        f"定向重试：回归失败 {len(items)} 例（累计明细，含此前修过但再次失败的用例）。",
        "本轮为定向修复：只修复与下列失败用例相关的问题（失败可能是产品缺陷，"
        "也可能是测试本身缺陷——断言过时、替身失真、超时替身自旋类，自行判定；"
        "修测试时产物行标 fix_scope=test），MUST NOT 扩面重做全批。",
    ]
    for i in items[:50]:
        lines.append(f"- {i['nodeid']}: {i.get('summary', '')}")
    return "\n".join(lines)


def release_retryable_failed_batches(project_root) -> int:
    """释放生效预算内（``fail_count < 生效预算``）的失败档案记录（selfheal D3）。

    新链启动时调用（等效原人工 ``release_failed_batch`` 的预算内自动化）：
    预算内条目回到可选池实现下轮自动重试；``fail_count >= 生效预算`` 的
    记录保持跳过（达上限永久跳过）。预算按 ``reg_form`` 分档
    （evo-add-codefix-anomaly-redispatch-budget）：anomaly 记录取
    ``ANOMALY_FAIL_RETRY_MAX``（1）、mapped（含缺键兼容）取 ``FAIL_RETRY_MAX``。
    返回释放的记录条数（供日志/进度文案）。

    释放是**打标墓碑**而非删除（code-review item 931df4af59cc）：置
    ``released=true`` + ``released_at``，``fail_count`` 原样保留。删除式释放
    会让预算永不累积——同链内 select_batch 排除在档条目、递增分支无从触发；
    链末释放又把记录整体删掉，下次失败重新以 1 建档，``fail_count`` 恒为 1，
    达上限的一次性告警/todo 登记/永久跳过全部不可达（确定性失败批每链无限
    重试，每轮烧一次 agent run + 两次全量回归）。墓碑不参与选批排除
    （``_failed_item_ids`` 跳过 released 记录）；同条目集再次入档时
    ``record_failed_batch`` 清标复燃并递增。幂等：已释放记录跳过不重刷时间戳。

    读-改-写全程持 flock（``_with_lock``，code-review item fd1dc2a59820，
    对齐同文件 ``write_progress`` 先例）：与批收尾 ``record_failed_batch``
    的并发交叠会丢更新（丢一条失败档案）。

    结构化留痕（codefix-release-consume-todo-block 1.2）：释放经
    _append_release_trace 写 fix-failed-release.jsonl（released_by=
    auto-budget 区分人工/自动）——解除回池动作此前零审计痕迹。**不接
    todo 核销动作**：本路径自 0eb2745a 起是打标墓碑而非删记录，记录
    保留在册、既有 consume 闭环对账范围天然覆盖（docstring 明言含墓碑），
    且预算内记录 fail_count < 生效预算、从未达登记阈值本无登记块。
    """
    path = _failed_path(project_root)

    def _do() -> tuple:
        records = load_failed_batches(project_root)
        released = 0
        released_ids: list = []
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        for rec in records:
            # fail_count 容错解析（_fail_count_int 单源，非数值按缺省 1）；
            # 预算按 reg_form 分档（evo-add-codefix-anomaly-redispatch-budget
            # 1.2）——不改则新链启动会把预算已耗尽的 anomaly 记录当预算内
            # 释放回池，分档被旁路。
            if rec.get("released") or _fail_count_int(
                rec.get("fail_count")
            ) >= _effective_retry_budget(rec):
                continue
            rec["released"] = True
            rec["released_at"] = now
            released += 1
            # 坏档形态守卫（_record_item_ids 单源）：非列表 item_ids 静默
            # 回退空列表，不留痕垃圾值（无 logger 的读侧调用形态）。
            released_ids.extend(str(i) for i in _record_item_ids(rec))
        if released:
            _atomic_write(
                path,
                json.dumps(records, ensure_ascii=False, indent=2),
            )
        return released, released_ids

    released, released_ids = _with_lock(path, _do)
    # 留痕锁外写（异文件，不占 fix-failed 锁；released_records>0 才有
    # 释放动作，但留痕无条件与人工路径同口径——幂等空轮同样留一行痕，
    # 审计「新链启动跑过释放」）。todo_result 恒 not_found：不接 todo
    # 核销（见 docstring），非异常。
    _append_release_trace(
        project_root, released, released_ids,
        released_by="auto-budget", todo_result="not_found",
    )
    return released


def release_failed_batch(project_root, item_ids, logger=None) -> int:
    """人工清理后解除失败保留（从 fix-failed.json 移除命中的 item_id）。

    返回解除的记录条数（供人工/审计确认；未命中返回 0）。
    无命中且无部分解除时不写盘——不凭空创建空档案、不重写未变化记录
    （对齐同模块 _patch_deferred_entry/_remove_deferred_batch/
    release_retryable_failed_batches 的无变化守卫惯例）。

    读-改-写全程持 flock（``_with_lock``，code-review item fd1dc2a59820，
    对齐同文件 ``write_progress`` 先例）：人工 release 与链边界自动操作
    （新链启动释放/批收尾入档）并发交叠会把人工解除结果整份覆盖回去
    （条目卡在跳过）。

    整批解除同步核销登记块（codefix-release-consume-todo-block 1.1）：
    整批删除注册表记录成功后的**同一调用序列内** best-effort 核销
    todo.md 对应登记块（复用 _rewrite_todo_entry_consumed 重写式核销，
    注记写明解除时刻与 fix-failed-release.jsonl 留痕行）——记录已删即
    永远够不着既有 consume 闭环（``consume_resolved_failed_batches`` 的
    pending 过滤按在册记录驱动），
    不核销则登记块成孤儿（proposal 实证 2026-10-08：带外解除删记录后
    登记块无人核销、正文损毁成裸标题壳）。核销 needle 整行精确匹配，
    防同批子集与「清单为其前缀扩展」的他批登记块误命中。仅整批删除
    触发核销；部分解除（收缩）剩余条目仍在册仍跳过、登记块不同步核销，
    但 ids 行同步收缩为记录当前清单（_rewrite_todo_entry_ids）——否则剩余
    条目全部终态时既有 consume 的整行锚对触顶时写入的全集行永不命中，
    登记块滞留成孤儿（code-review item f60e3189e664）。fix-failed 锁与
    todo 锁是两把锁、不嵌套（核销/收缩同步在 _with_lock 返回、fix-failed
    锁已释放后执行）；核销 best-effort、
    OSError 容错同 _append_todo_entry 口径（失败不阻断解除主流程），
    后果由留痕行 todo_result 字段审计。登记块已损毁成裸标题壳时由
    _rewrite_todo_entry_consumed 既有兜底移除（不新造、不波及他批块）。

    结构化留痕（add-codefix-failure-registration-closeout 1.3）：调用
    **无条件**追加一行到 ``.fenix/code-review/fix-failed-release.jsonl``
    （释放时刻+释放记录数+item_ids 摘要+todo 块处理结果）——带外
    ``python3 -c`` 直调（todo 登记正文列为官方解除指引）不经 daemon
    logger、此前零留痕（proposal 实证 2026-10-07 释放 13 条仅会话考古
    可见），留痕文件是唯一权威追溯载体；``logger``（可选）传入时另写
    一行 daemon 日志（补充通道，留痕失败不阻断解除本身）。
    """
    requested = [str(i) for i in (item_ids or [])]
    released = 0
    released_batches: list = []
    todo_consumed = False
    released_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    if set(requested):
        target = set(requested)
        path = _failed_path(project_root)

        def _do() -> tuple:
            records = load_failed_batches(project_root)
            kept = []
            released = 0
            changed = 0
            batches: list = []
            shrunk: list = []
            for rec in records:
                # item_ids 形态守卫（code-review item 3bf751ec88d9，对齐
                # _record_item_ids 先判后拷纪律）：坏档非列表标量直接迭代
                # 会抛 TypeError 中断人工解除；按空列表容错、记录原样保留
                # （不误整批解除、不改写坏档）。
                raw = rec.get("item_ids")
                rec_ids = raw if isinstance(raw, list) else []
                ids = [i for i in rec_ids if i not in target]
                if len(ids) == len(rec_ids):
                    kept.append(rec)  # 无交集，原样保留
                elif ids:
                    rec["item_ids"] = ids
                    kept.append(rec)  # 部分解除，保留余量
                    changed += 1
                    # 收缩对（原全集 → 收缩后清单）：登记块 ids 行据此同步
                    # 收缩，保住既有 consume 的整行核销锚可达（f60e3189e664）。
                    shrunk.append(([str(i) for i in rec_ids], ids))
                else:
                    released += 1  # 整批解除
                    # 记录整批删除 → 收集其实际条目清单（非请求超集）：
                    # 核销 needle 按它整行精确匹配登记块 ids 行。
                    batches.append([str(i) for i in rec_ids])
            # [fenix-ignore:513aabee5028] 无变化不写盘守卫已在先前 code-fix 批次落地（changed/released 计数条件写盘，docstring 同步声明），条目所指「无命中仍无条件重写、凭空创建空档案」已不存在。
            if changed or released:  # 无变化不写盘（对齐同模块守卫惯例）
                _atomic_write(
                    path,
                    json.dumps(kept, ensure_ascii=False, indent=2),
                )
            return released, batches, shrunk

        released, released_batches, shrunk_batches = _with_lock(path, _do)
        # 整批删除成功 → 同一调用序列内 best-effort 核销 todo 登记块
        # （1.1）。此刻 fix-failed 锁已随 _with_lock 返回释放，todo 锁
        # （.fenix/.todo.md.lock）独立持有，两把锁不嵌套、无锁序风险；
        # OSError 已由 _rewrite_todo_entry_consumed 内部容错（返回 False
        # 不上穿）。多批同轮整批删除时逐块核销，任一块未核销成功即按
        # not_found 审计（不静默吞掉部分失败）。
        todo_consumed = bool(released_batches)
        for rec_ids in released_batches:
            if not _rewrite_todo_entry_consumed(
                project_root,
                rec_ids,
                note="",
                consumed_at=released_at,
                replacement=(
                    f"- [x] [code-fix] 失败批登记已于 {released_at} 人工解除核销"
                    f"（整批出册，解除留痕见 {RELEASE_TRACE_REL}）\n"
                ),
            ):
                todo_consumed = False
        # 部分解除收缩同步（code-review item f60e3189e664）：登记块 ids 行
        # 原位收缩为记录当前清单——剩余条目全部终态时既有 consume 凭收缩后
        # 行整行命中闭环（触顶时写入的全集行对收缩后记录永不命中）。todo 锁
        # 独立、此刻 fix-failed 锁已释放（同上方整批核销）；best-effort，
        # OSError 由重写器内部容错（返回 False 不上穿），不阻断解除主流程。
        for old_rec_ids, new_ids in shrunk_batches:
            _rewrite_todo_entry_ids(project_root, old_rec_ids, new_ids)
    # 留痕锁外写（异文件，不占 fix-failed 锁；无条件含零命中调用），
    # todo_result 携核销结果（1.3）：consumed=整批解除且登记块已核销 /
    # not_found=未核销（含零命中、部分解除不触发核销、块缺失、todo 写
    # 失败）——「解除未核销」可从留痕审计。
    _append_release_trace(
        project_root,
        released,
        requested,
        logger=logger,
        released_at=released_at,
        todo_result="consumed" if todo_consumed else "not_found",
    )
    return released


# ── 失败登记闭环核销（add-codefix-failure-registration-closeout 1.1-1.3）──
# 达自动重试上限的失败批登记（fix-failed.json 记录 + 一次性告警 + todo 待
# 人工项）此前是一次性写入、永不更新：被跳过条目后续被他批修复而全部终态
# 后，登记与告警仍挂着「待人工排查」（proposal 实证：两条告警挂了一天以上
# handled=false）。本段补消费侧闭环：周期对账（批收尾/合回核销点 + 新链
# 启动簿记块）发现被跳过条目全部终态即核销并收口告警/todo 登记。


# release_failed_batch 结构化留痕文件（1.3）：带外 python3 -c 直调不经
# daemon logger，此文件是唯一权威追溯载体。
RELEASE_TRACE_REL = ".fenix/code-review/fix-failed-release.jsonl"

# todo.md 登记块定位锚（与 _append_todo_entry 写入格式逐字对齐）。
_TODO_ENTRY_TITLE = "## [code-fix] 失败批已达自动重试上限，待人工排查"
_TODO_ENTRY_IDS_LINE = "- 被跳过的条目集合（保持 open）："


def _append_release_trace(
    project_root, released_records, item_ids, logger=None,
    released_at=None, todo_result="not_found", released_by="manual",
) -> None:
    """解除写点的结构化留痕追加（closeout 1.3；release-consume 1.2/1.3）。

    追加一行 JSON（释放时刻+释放记录数+item_ids 摘要+来源+todo 块处理
    结果）到 ``RELEASE_TRACE_REL``；OSError 容错与 _append_todo_entry 同
    口径（留痕失败不阻断解除本身）。``logger``（可选）传入时另写一行
    daemon 日志（补充通道；日志失败无副作用）。

    ``released_by``：manual=人工 release_failed_batch（缺省）/
    auto-budget=新链启动预算内自动释放（release-consume 1.2，此前该写点
    零审计痕迹）。``todo_result``：consumed=本次解除已同步核销 todo 登记
    块 / not_found=未核销（含部分解除不触发核销、预算内释放本无登记块、
    块缺失、todo 写失败）——「解除未核销」审计口径：released_records>0
    且 todo_result=not_found 的行按 released_by 判读（manual 整批解除
    not_found 即登记块成孤儿，须人工核查 todo.md 残留）。
    ``released_at``（可选）外部传入解除时刻（release 路径与 todo 核销注记
    同一时刻值，注记-留痕可互相对账）；缺省取当前时刻。
    """
    entry = {
        "released_at": released_at or time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
        ),
        "released_records": int(released_records),
        "item_ids": [str(i) for i in (item_ids or [])],
        "released_by": released_by,
        "todo_result": todo_result,
    }
    try:
        trace_path = Path(project_root) / RELEASE_TRACE_REL
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        with trace_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return
    if logger is not None:
        try:
            logger.info(
                "code-fix",
                f"code-fix 失败批解除留痕：释放 {released_records} 条记录，"
                f"item_ids={entry['item_ids']}（{RELEASE_TRACE_REL}）",
            )
        except Exception:  # noqa: BLE001 — 日志失败不影响解除
            pass


def _evidence_item_ids(evidence) -> set:
    """从告警 evidence 串解析 ``item_ids=<清单>;`` 字段为 id 集合（无字段空集）。

    字段形态由 _write_retry_exhausted_alert 写入（分号分隔字段、item_ids=
    恰出现一次）；解析口径对齐 core.admin_store.evidence_project 先例。
    """
    for seg in str(evidence or "").split(";"):
        seg = seg.strip()
        if seg.startswith("item_ids="):
            return {
                p.strip()
                for p in seg[len("item_ids="):].split(",")
                if p.strip()
            }
    return set()


def _close_retry_exhausted_alerts(project_root, item_ids, note, logger=None) -> int:
    """核销时收口对应 code_fix_retry_budget_exhausted 告警（1.2）。

    告警记录无结构化 item_ids/branch/tip_sha 字段（_write_retry_exhausted_alert
    仅 evidence 文本含 ``item_ids=<清单>``），经 read_all 过滤 signal_type 后按
    evidence 内 ``item_ids=<清单>;`` 精确子串匹配——带分号后缀避免条目集
    前缀的批间误命中（``item_ids=a, b`` 是 ``item_ids=a, b, c`` evidence 的
    前缀子串）。部分解除收缩记录清单后（code-review item f60e3189e664）
    精确锚对触顶时写入的全集名录永不命中、告警成孤儿，追加收缩兜底：
    evidence 名录**包含**记录当前清单（真超集）且多出条目不属于任何其他
    未核销记录（收口不得连带剥掉他批登记的唯一人工关注信号）时同样放行；
    名录多出条目全部已出册（被解除/已随他批终态），不再有在册归属。卸下
    精确锚的既有批间语义不变。action_taken 附终态分布注记；已 handled 告警
    跳过（重复核销幂等）。告警收口失败不回滚核销记账（核销为只增记账动
    作），仅 logger（可选）留痕。返回收口条数。
    """
    from core.admin_store import AdminStore, SIGNAL

    ids_set = {str(i) for i in item_ids}
    needle = f"item_ids={', '.join(str(i) for i in item_ids)};"
    # 收缩兜底的误收口守卫判据：其他未核销记录的条目清单（本记录此刻已置
    # consumed_at，天然不在其中；load_failed_batches 对坏档 fail-open）。
    other_pending: list = []
    for rec in load_failed_batches(project_root):
        if not rec.get("consumed_at"):
            raw = rec.get("item_ids")
            other_pending.append(
                {str(i) for i in raw} if isinstance(raw, list) else set()
            )
    closed = 0
    try:
        store = AdminStore(project_root, logger=None)
        for rec in store.read_all():
            if rec.get("kind") != SIGNAL:
                continue
            if rec.get("signal_type") != "code_fix_retry_budget_exhausted":
                continue
            if rec.get("handled"):
                continue
            evidence_txt = str(rec.get("evidence") or "")
            if needle not in evidence_txt:
                ev_ids = _evidence_item_ids(evidence_txt)
                if not (
                    ids_set
                    and ids_set < ev_ids
                    and not any(
                        p & (ev_ids - ids_set) for p in other_pending
                    )
                ):
                    continue
            if store.mark_signal_handled(
                rec.get("id"),
                action_taken=(
                    "失败登记已自动核销（被跳过条目全部终态：" f"{note}）"
                ),
            ):
                closed += 1
    except Exception as e:  # noqa: BLE001 — 收口失败不阻断核销主流程
        if logger is not None:
            try:
                logger.warning(
                    "code-fix", f"code-fix 失败登记核销的告警收口失败: {e}"
                )
            except Exception:  # noqa: BLE001 — 留痕失败不影响
                pass
    return closed


def _rewrite_todo_entry_consumed(
    project_root, item_ids, note, consumed_at, replacement=None
) -> bool:
    """核销时把 todo.md 对应登记块重写为单行核销注记（1.3，消费侧弱化）。

    定位口径：登记标题（_append_todo_entry）不含 item_ids，按块体「被跳过
    的条目集合（保持 open）：<清单>」行**整行精确匹配**定位**本记录对应
    块**、只重写该块（多个失败批的登记块可共存，MUST NOT 波及他批登记
    块）。整行锚（行尾等值比对，codefix-release-consume-todo-block 1.1）
    防前缀子串误命中：本批清单行是他批「清单为其前缀扩展」行的前缀子串
    （needle「：a, b」⊂「：a, b, c」），对齐 _close_retry_exhausted_alerts
    分号后缀锚的既有先例。块体已损毁成裸标题（proposal 所述残骸，无
    item_ids 行可定位）时按标题行兜底移除。
    持 ``.fenix/.todo.md.lock`` 同锁（与 _append_todo_entry / evolution 写者
    同锁契约，code-review item 28c473f92809）经 _atomic_write 整文件重写，
    不依赖原位追加注记；OSError 容错与 _append_todo_entry 同口径（todo 消费
    失败不阻断核销主流程）。块不存在（已消费/未登记）返回 False。
    ``replacement``（可选）定制核销注记整行（release 路径写明解除时刻与
    fix-failed-release.jsonl 留痕行指引；缺省为消费侧「全部终态+告警已收口」
    文案，既有 consume 路径调用契约不变）。
    """
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    ids_txt = ", ".join(str(i) for i in item_ids)
    ids_needle = f"{_TODO_ENTRY_IDS_LINE}{ids_txt}"
    if replacement is None:
        replacement = (
            f"- [x] [code-fix] 失败批登记已于 {consumed_at} 核销"
            f"（被跳过条目全部终态：{note}），对应告警已收口\n"
        )

    def _rewrite_locked() -> bool:
        try:
            text = todo_path.read_text(encoding="utf-8")
        except OSError:
            return False
        lines = text.splitlines(keepends=True)
        out: list = []
        changed = False
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            if _TODO_ENTRY_TITLE not in line:
                out.append(line)
                i += 1
                continue
            # 登记块 = 标题行起至下一个 "## " 标题行前（不含）。
            j = i + 1
            while j < n and not lines[j].lstrip().startswith("## "):
                j += 1
            block = lines[i:j]
            body = block[1:]
            # 整行精确匹配（行尾锚）：子串包含会把同批子集请求、以及「清单
            # 为本批前缀扩展」的他批登记块一并误命中重写。
            if any(b.rstrip("\r\n") == ids_needle for b in body):
                out.append(replacement)  # 本记录登记块 → 重写式核销
                changed = True
            elif body and any(b.strip() for b in body):
                out.extend(block)  # 他批完整登记块（ids 不匹配），原样保留
            else:
                changed = True  # 裸标题空壳残骸：兜底移除
            i = j
        if changed:
            _atomic_write(todo_path, "".join(out))
        return changed

    try:
        return _with_lock(todo_path, _rewrite_locked)
    except OSError:
        return False


def _rewrite_todo_entry_ids(project_root, old_ids, new_ids) -> bool:
    """部分解除时把登记块的 ids 行同步收缩为记录当前清单（收缩口径）。

    定位锚与核销重写器同款（ids 行**整行精确匹配**，防前缀子串误命中他批
    登记块），仅把命中行原位替换为收缩后清单行——块保持待核销态。不收缩
    则剩余条目全部终态时，既有 consume 的整行锚对触顶时写入的全集行永不
    命中，登记块滞留成孤儿（code-review item f60e3189e664）。持
    ``.fenix/.todo.md.lock`` 同锁，OSError 容错与 _rewrite_todo_entry_consumed
    同口径（同步失败不阻断解除主流程）。行不存在（块已核销/未登记/已手工
    改动）返回 False。
    """
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    old_line = f"{_TODO_ENTRY_IDS_LINE}{', '.join(str(i) for i in old_ids)}"
    new_line = f"{_TODO_ENTRY_IDS_LINE}{', '.join(str(i) for i in new_ids)}\n"

    def _rewrite_locked() -> bool:
        try:
            text = todo_path.read_text(encoding="utf-8")
        except OSError:
            return False
        lines = text.splitlines(keepends=True)
        changed = False
        for idx, line in enumerate(lines):
            if line.rstrip("\r\n") == old_line:
                lines[idx] = new_line
                changed = True
        if changed:
            _atomic_write(todo_path, "".join(lines))
        return changed

    try:
        return _with_lock(todo_path, _rewrite_locked)
    except OSError:
        return False


def consume_resolved_failed_batches(project_root, logger=None) -> int:
    """失败登记闭环核销：被跳过条目全部终态即核销并收口（1.1/1.2）。

    对 fix-failed.json 中未核销记录（缺 ``consumed_at`` 视为未核销，向后
    兼容）的被跳过条目做台账逐 id 对账：

    - 全部终态（resolved/in_spec/ignored）→ 锁内置 ``consumed_at``/``consumed_note``
      （终态分布注记）/``open_remaining=0``，锁外收口对应
      code_fix_retry_budget_exhausted 告警（mark_signal_handled，action_taken
      附终态分布）并重写 todo.md 登记块；
    - 部分终态 → 只更新 ``open_remaining``（值不变不写盘），不核销、
      不收口；台账中查不到的条目视为非终态（无法证明终态，保守不核销）；
    - 台账读取失败（OSError 降级，degraded_out 出参检出）按空集 fail-open
      **跳过本轮核销**，不阻断批收尾/链启动主流程。降级检测不可省：
      read_items 口径把读失败吞成空集，而核销语义与核销写点相反（空集=
      全部条目非 open=全终态），误当空集会把全部未核销记录误判核销。

    读-改-写全程持 flock（``_with_lock``，锁内不重入）；告警/todo 写走
    异锁通道、保持锁外。幂等：已核销记录（有 consumed_at）跳过不重写，
    已 handled 告警不再收口。返回本轮核销的记录数。

    对账范围含预算内记录与墓碑：其条目被他批修复而终态时同样闭环（核销为
    只增记账动作，不改变 ``_failed_item_ids`` 的选批排除语义）。
    """
    path = _failed_path(project_root)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    degraded: list = []

    def _do() -> list:
        records = load_failed_batches(project_root)
        pending = [rec for rec in records if not rec.get("consumed_at")]
        if not pending:
            return []
        ledger = None
        try:
            ledger = _read_items_unlocked(
                items_path(project_root), degraded_out=degraded
            )
        except Exception:  # noqa: BLE001 — 台账读失败按空集（跳过本轮核销）
            degraded.append(True)
        if degraded or ledger is None:
            return []
        changed = False
        consumed: list = []
        for rec in pending:
            ids = [
                str(i)
                for i in _record_item_ids(
                    rec, logger=logger, where="失败档案记录 "
                )
            ]
            if not ids:
                continue
            statuses = [
                str((ledger.get(i) or {}).get("status") or "") for i in ids
            ]
            # 终态判定含 in_spec（code-review item b65586790d7f，与
            # _open_ids_for_archive docstring「人工置终态」三态口径一致）：
            # 被跳过条目经 generate-spec 链 _mark_in_spec 置 in_spec 后同样
            # 离开 open 池，不计入则 terminal_n 恒小于 len(ids)，该失败登记
            # 永不收口——告警与 todo 登记块永久滞留 pending。
            terminal_n = sum(
                1 for s in statuses if s in ("resolved", "in_spec", "ignored")
            )
            if terminal_n != len(ids):
                # 部分终态：只同步剩余 open 数，不收口告警、不标记核销。
                remaining = len(ids) - terminal_n
                if rec.get("open_remaining") != remaining:
                    rec["open_remaining"] = remaining
                    changed = True
                continue
            note = (
                f"{statuses.count('resolved')} resolved / "
                f"{statuses.count('ignored')} ignored"
            )
            in_spec_n = statuses.count("in_spec")
            if in_spec_n:
                note = f"{note} / {in_spec_n} in_spec"
            rec["consumed_at"] = now
            rec["consumed_note"] = note
            rec["open_remaining"] = 0
            changed = True
            consumed.append((ids, note))
        if changed:
            _atomic_write(
                path,
                json.dumps(records, ensure_ascii=False, indent=2),
            )
        return consumed

    consumed = _with_lock(path, _do)
    # 告警收口与 todo 消费走异锁通道，保持锁外（对齐 record_failed_batch
    # 锁外写告警/todo 的惯例）；核销记账已落盘，收口失败只留痕不回滚。
    for ids, note in consumed:
        _close_retry_exhausted_alerts(project_root, ids, note, logger=logger)
        _rewrite_todo_entry_consumed(project_root, ids, note, consumed_at=now)
    return len(consumed)


# ── 延迟合回台账（fix-codefix-wipgate-defer 1.2/D2）──────────────────
# 与失败档案对齐的惯例：同目录、_atomic_write 原子写、同条目集幂等复用、
# 读侧对缺失/损坏 fail-open；读-改-写各写入口全程持 flock（``_with_lock``，
# 对齐失败档案 fd1dc2a59820 先例——锁文件由 _with_lock 派生自台账文件名；
# 读点 ``load_deferred_batches`` 保持无锁，锁内复用勿重入）。


def _deferred_path(project_root) -> Path:
    return Path(project_root) / DEFERRED_REL


def load_deferred_batches(project_root) -> list:
    """读取延迟合回台账；文件不存在/损坏视为空集（不阻塞车道）。"""
    try:
        raw = _deferred_path(project_root).read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return []
    if isinstance(data, list):
        return [rec for rec in data if isinstance(rec, dict)]
    return []


def _save_deferred_batches(project_root, entries: list) -> None:
    _atomic_write(
        _deferred_path(project_root),
        json.dumps(entries, ensure_ascii=False, indent=2),
    )


def record_deferred_batch(
    project_root, item_ids, fixed_ids, worktree,
    branch="", tip_sha="", last_overlap=None,
) -> dict:
    """把被主树 WIP 挡住合回的批记入 fix-deferred.json（原子写；幂等复用）。

    零预算语义（D2）：不入失败档案、不烧 ``fail_count``。条目八字段：
    ``worktree``/``branch``/``tip_sha``/``item_ids``/``fixed_ids``/
    ``defer_count``/``first_deferred_at``（UTC ISO8601）/``last_overlap``。
    ``fixed_ids`` 是批产物行 ``status=="fixed"`` 的核销集合——缺它则重试方
    无从区分 fixed 与 skipped，全批核销会把 skipped 白洗成 resolved。

    首记 ``defer_count=1``（批收尾那次被阻断的 merge_back 即一次实际尝试）；
    链边界重试仍被阻断时由重试方递增（2.3：仅实际尝试才 +1）。同条目集
    幂等复用条目：刷新现场字段、保留 ``first_deferred_at``/``defer_count``
    （预算时间门不因复写漂移）。返回写盘后的条目。

    读-改-写全程持 flock（``_with_lock``，code-review item 35fea063bcff，
    对齐失败档案 fd1dc2a59820 先例）：批收尾 defer 登记与链边界重试/再认领
    分属批 worker 与 checkpoint 线程，无锁交叠会整份丢更新。
    """
    path = _deferred_path(project_root)

    def _do() -> dict:
        entries = load_deferred_batches(project_root)
        key = {str(i) for i in item_ids}
        target = None
        for rec in entries:
            raw = rec.get("item_ids")
            # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档非列表
            # 标量判不命中（幂等复用退化为新记一条，不炸 defer 登记）。
            if isinstance(raw, list) and {str(i) for i in raw} == key:
                target = rec
                break
        if target is None:
            target = {
                "item_ids": [str(i) for i in item_ids],
                "defer_count": 1,
                "first_deferred_at": time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime()
                ),
            }
            entries.append(target)
        target["worktree"] = str(worktree)
        target["branch"] = branch
        target["tip_sha"] = tip_sha
        target["fixed_ids"] = [str(i) for i in fixed_ids]
        target["last_overlap"] = [str(f) for f in (last_overlap or [])]
        _save_deferred_batches(project_root, entries)
        return target

    return _with_lock(path, _do)


def _patch_deferred_entry(project_root, item_ids, **fields) -> None:
    """按条目集定位并原位更新台账字段（defer_count 递增等），原子写。

    读-改-写全程持 flock（``_with_lock``，code-review item 35fea063bcff，
    同 ``record_deferred_batch`` 口径）。
    """
    path = _deferred_path(project_root)

    def _do() -> None:
        entries = load_deferred_batches(project_root)
        key = {str(i) for i in item_ids}
        hit = False
        for rec in entries:
            raw = rec.get("item_ids")
            # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档非列表
            # 标量判不命中、跳过 patch（不炸 defer_count 递增路径）。
            if isinstance(raw, list) and {str(i) for i in raw} == key:
                rec.update(fields)
                hit = True
        if hit:
            _save_deferred_batches(project_root, entries)

    _with_lock(path, _do)


def _remove_deferred_batch(project_root, item_ids) -> None:
    """从台账移除命中的条目（按 item_ids 集合整条匹配；无命中静默返回）。

    读-改-写全程持 flock（``_with_lock``，code-review item 35fea063bcff，
    同 ``record_deferred_batch`` 口径）。
    """
    path = _deferred_path(project_root)

    def _do() -> None:
        entries = load_deferred_batches(project_root)
        key = {str(i) for i in item_ids}
        # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档非列表标量
        # 判不命中、原样保留（MUST NOT 让 TypeError 上穿炸掉移除路径）。
        kept = [
            rec
            for rec in entries
            if not (
                isinstance(rec.get("item_ids"), list)
                and {str(i) for i in rec["item_ids"]} == key
            )
        ]
        if len(kept) != len(entries):
            _save_deferred_batches(project_root, kept)

    _with_lock(path, _do)


def _deferred_item_ids(project_root) -> set:
    """台账全部 item_id 并集（select_batch 排除源之一，D4 配套约束）。

    defer 条目在合回成功前始终是 open 状态且不在失败档案——不并入排除集则
    下一边界 earliest-first 立即重选同批、重跑 agent，defer 核心收益归零。
    """
    ids: set = set()
    for rec in load_deferred_batches(project_root):
        for iid in _record_item_ids(rec):
            if isinstance(iid, str):
                ids.add(iid)
    return ids


def _deferred_entry_alive(entry) -> bool:
    """台账条目的磁盘真相（D5 再认领判据）：worktree 目录在且记录的 tip_sha
    仍可经该 worktree HEAD 解析（分支被删/目录被清/漂移均判死）。

    空 tip_sha（登记时 ``_worktree_head`` 瞬时失败所致）不直接判死：现场
    补解析 HEAD，能解析即视为存活（merge_back 不依赖记账的 tip_sha），
    否则带修复提交的存活 worktree 会被误判死移出台账且无人清理。
    """
    wt = Path(str(entry.get("worktree") or ""))
    tip_sha = str(entry.get("tip_sha") or "")
    if not wt.name or not wt.exists():
        return False
    if not tip_sha:
        return bool(_worktree_head(wt))
    return _worktree_head(wt) == tip_sha


def reclaim_deferred_batches(project_root) -> int:
    """新链启动再认领（D5/4.1）：台账核对磁盘，死条目移出，返回移除条数。

    存活（worktree 目录在且 tip_sha 可解析）→ 原样保留（``defer_count``/
    ``first_deferred_at`` 不重置，链边界重试照常覆盖）；丢失 → 清出台账 +
    由调用方记 warning（条目未核销，天然仍在 open 池，无需回写）。

    读-改-写全程持 flock（``_with_lock``，code-review item 35fea063bcff，
    同 ``record_deferred_batch`` 口径）。
    """
    path = _deferred_path(project_root)

    def _do() -> int:
        entries = load_deferred_batches(project_root)
        kept = [rec for rec in entries if _deferred_entry_alive(rec)]
        dropped = len(entries) - len(kept)
        if dropped:
            _save_deferred_batches(project_root, kept)
        return dropped

    return _with_lock(path, _do)


def _defer_time_budget_exhausted(entry) -> bool:
    """时间门：first_deferred_at 距今超 DEFER_BUDGET_SECONDS（解析失败按未超时）。

    超时判定只看 ``first_deferred_at``，不受重试影响（2.3）。
    """
    ts = str(entry.get("first_deferred_at") or "")
    if not ts:
        return False
    try:
        start = calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))
    except (ValueError, TypeError):
        return False
    return (time.time() - start) > DEFER_BUDGET_SECONDS


def _has_expired_archive(project_root, item_ids) -> bool:
    """失败档案是否已有同条目集的 wip_gate_blocked_expired 记录（3.2 告警去重指纹）。

    MUST 在 ``record_failed_batch`` 之前调用——入档后同集合记录即在场，
    先查后记才能区分「首次降级」与「同指纹二次降级」。
    """
    key = {str(i) for i in item_ids}
    for rec in load_failed_batches(project_root):
        raw = rec.get("item_ids")
        if (
            rec.get("reason") == "wip_gate_blocked_expired"
            # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档非列表
            # 标量判不命中（去重指纹退化为可能重复告警，不炸降级路径）。
            and isinstance(raw, list)
            and {str(i) for i in raw} == key
        ):
            return True
    return False


def _fmt_overlap(overlap) -> str:
    """交集文件清单 → 人类可读片段（进度文案/告警正文复用，超长截断）。"""
    files = [str(f) for f in (overlap or []) if str(f)]
    if not files:
        return "（交集清单缺失）"
    shown = ", ".join(files[:8])
    if len(files) > 8:
        shown += f" 等 {len(files)} 个文件"
    return shown


def _append_todo_entry(
    project_root, item_ids, reason="", branch="", tip_sha="",
    budget: int = FAIL_RETRY_MAX,
) -> None:
    """达重试上限的失败批在 .fenix/todo.md 追加待人工排查项（一次性，D4）。

    现场即弃语义下 worktree 已清理，指引按 ``branch``/``tip_sha`` 追溯
    （丢弃的修复提交可经 git reflog 找回）；MUST NOT 再引用 worktree 路径。
    ``budget``：生效自动重派预算（调用方按记录分档传入），文案如实呈现。
    """
    todo_path = Path(project_root) / ".fenix" / "todo.md"
    ids_txt = ", ".join(str(i) for i in item_ids)
    entry = (
        "\n## [code-fix] 失败批已达自动重试上限，待人工排查"
        "（add-code-fix-batch-failure-selfheal）\n\n"
        f"- 记录时间：{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n"
        f"- 失败原因：{reason or 'unknown'}（自动重试 {budget} 轮均失败，"
        "已停止自动重派）\n"
        f"- 追溯线索：branch=`{branch}`、tip_sha=`{tip_sha}`（worktree 已清理，"
        "丢弃的修复提交可经 git reflog 按 tip_sha 找回）\n"
        f"- 被跳过的条目集合（保持 open）：{ids_txt}\n"
        "- 解除跳过（人工确认处置后）：\n"
        "  `python3 -c \"from core.code_fix import release_failed_batch; "
        "release_failed_batch('<project_root>', ['<item_id>', ...])\"`\n"
    )
    try:
        todo_path.parent.mkdir(parents=True, exist_ok=True)

        def _append_locked() -> None:
            with todo_path.open("a", encoding="utf-8") as fh:
                fh.write(entry)

        # evolution 侧对 todo.md 的读-改-写（write_todo_marker / clear_todo）
        # 持同一把伴生 flock 后经 _atomic_write（os.replace 整文件替换）写回；
        # 本追加 MUST 持同一把锁，否则落在对方「读后写前」窗口内的行会被整
        # 文件替换吞掉。锁派生与 evolution 侧一致：两侧 _with_lock 同式派生
        # ``.<name>.lock``（code_review.py:307 ``path.parent / f".{path.name}.lock"``
        # ≡ evolution.py:137），对本文件均解析到 ``.fenix/.todo.md.lock``，
        # 且两侧路径均按 ``<proj>/.fenix/todo.md`` 解析到同一文件
        # （evolution.write_todo_marker evolution.py:871）。
        # （code-review item 28c473f92809）
        _with_lock(todo_path, _append_locked)
    except OSError:
        # todo 登记失败不阻断失败批落盘（fix-failed.json 才是跳过判据）
        pass


# ── 选批（5.2；add-codefix-affinity-batching 1.1 亲和性聚类）──────────


def _select_batch_order_key(rec) -> tuple:
    """既有稳定序口径：first_seen_at 升序（缺失回退 item_id）。"""
    return (
        str(rec.get("first_seen_at") or ""),
        str(rec.get("item_id") or ""),
    )


def _file_parent_dir(file_path: str):
    """条目 file 的直接父目录（POSIX 相对路径口径）。

    顶层文件（无父目录）返回 None——互不为「同目录」（design D1：目录簇取
    直接父目录全等比较，顶层文件不构成簇）。
    """
    rel = str(file_path or "").replace("\\", "/")
    parent = rel.rsplit("/", 1)[0] if "/" in rel else ""
    return parent or None


def _group_open_items_by_file(open_items: list) -> list:
    """按 file 字段归并文件组（add-codefix-affinity-batching 1.1）。

    ``open_items`` 须已按既有稳定序排好——组内条目保持该序；dict 插入序即
    组间序（组的键 = 组内最早条目的稳定序键，天然满足「组间按组内最早
    first_seen_at 升序（缺失回退组内最小 item_id）」）。文件组是最小不可拆
    单元：同一文件的全部 open 条目必入同批。
    """
    groups: dict = {}
    for rec in open_items:
        groups.setdefault(str(rec.get("file") or ""), []).append(rec)
    return list(groups.values())


def _pack_first_batch(groups: list, target: int) -> list:
    """贪心装箱返回首批（design D1 四规则，确定性：同输入必同输出）。

    - 目标规模 T=``target``（batch_size，语义为「目标规模」而非精确条数）；
      硬上限 H=2T。
    - 从最早文件组开启当前批；吸收候选优先级：与批内已有文件同目录的最早
      文件组优先（加入后 ≤ H 即吸收，允许浮动超 T）；无可用同目录候选时取
      最早「加入后 ≤ H」的异目录组尝试吸收（仅批 < T 时；吸收后 ≥ T 即封批）。
    - 批条数达 H 封批；单文件组自身 > H 独立成批不拆（整批可超 H）。
    """
    hard_cap = 2 * target
    if not groups:
        return []
    first = list(groups[0])
    batch = list(first)
    if len(batch) > hard_cap:
        # 规则 6：单文件组超硬上限独立成批、不拆分（拆分重蹈「同文件问题
        # 分批重复取证」覆辙；批内并行由波次上限自适应消化）
        return batch
    batch_dirs: set = set()
    for rec in first:
        d = _file_parent_dir(rec.get("file"))
        if d is not None:
            batch_dirs.add(d)
    remaining = [list(g) for g in groups[1:]]
    while remaining and len(batch) < hard_cap:
        # 候选扫描（全局最早序）：①最早一个「加入后 ≤ H」的同目录组优先；
        # ②顺带记录最早一个「加入后 ≤ H」的异目录组（超额者跳过续扫更小候选，
        # 与同目录分支同一容量口径，MUST NOT 把批推过硬上限 H）
        same_idx = -1
        cross_idx = -1
        for i, grp in enumerate(remaining):
            d = _file_parent_dir(grp[0].get("file"))
            if d is not None and d in batch_dirs:
                if len(batch) + len(grp) <= hard_cap:
                    same_idx = i
                    break
                # 该同目录组不满足吸收条件 → 继续扫更小的同目录候选
                continue
            if cross_idx < 0 and len(batch) + len(grp) <= hard_cap:
                cross_idx = i
        if same_idx >= 0:
            pick, cross_absorbed = same_idx, False
        elif cross_idx >= 0 and len(batch) < target:
            pick, cross_absorbed = cross_idx, True
        else:
            break  # 无任何候选满足吸收条件 → 封批（余组进下一装箱批）
        grp = remaining.pop(pick)
        batch.extend(grp)
        for rec in grp:
            d = _file_parent_dir(rec.get("file"))
            if d is not None:
                batch_dirs.add(d)
        if len(batch) >= hard_cap:
            break  # 规则 5：达硬上限封批
        if cross_absorbed and len(batch) >= target:
            break  # 规则 4：异目录吸收后 ≥ 目标规模即封批
    return batch


def select_batch(project_root, batch_size: int, exclude_ids=None, severity_gate=None) -> list:
    """从台账选下一批：文件亲和性聚类装箱（add-codefix-affinity-batching 1.1）。

    open 条目按 ``file`` 字段归并为文件组（组不可拆），组间按组内最早
    first_seen_at 升序（缺失回退组内最小 item_id，与既有稳定序口径一致），
    经贪心装箱返回首批——``batch_size`` 为目标规模 T（同目录组允许浮动超 T、
    硬上限 H=2T 封批），不再是精确条数。链推进每轮重调本函数，每次调用返回
    装箱后的首批即可（既有调用点只消费首批，语义零改动）。

    排除口径不变 = 失败档案条目并集 ∪ ``exclude_ids``（add-code-fix-batch-
    selfheal：链内跳过集 chain_skipped，瞬态失败条目本链不再选批；缺省
    None 向后兼容，既有调用点零改动）。台账读失败返回空列表（fail-closed）。

    severity 分级门限（evo-add-codefix-severity-batch-gate 2.1）：``severity_gate``
    非空时低于门限且未到周批窗口的 code-review 来源条目不入批（regression-
    前缀豁免；谓词经 ``severity_gate_open`` 单一函数，与 generate_fix_spec
    候选层同门）。挂起条目仍为 open（挂起计，不计 skipped/lost）；周批窗口
    到期后由本谓词放行整组。None 向后兼容（无门限过滤）。

    返回条目 record 列表（含 item_id/file/line/severity/category/title/
    description/suggestion 等 prompt 注入字段）。
    """
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001 — 台账读失败按无条目处理（fail-closed）
        return []
    excluded = _failed_item_ids(project_root) | set(exclude_ids or ())
    pool = [
        rec
        for rec in items.values()
        if isinstance(rec, dict)
        and rec.get("status") == "open"
        and rec.get("item_id") not in excluded
    ]
    if not pool:
        return []
    if severity_gate is not None:
        # 组放行窗口（evo-add-codefix-severity-batch-gate）：挂起集中最早锚
        # 距今达 cadence 天 → 低于门限条目整组放行（非逐条到期逐条放行）
        release = severity_gate_release_due(pool, severity_gate)
        pool = [
            rec
            for rec in pool
            if severity_gate_open(rec, severity_gate, release_due=release)
        ]
    if not pool:
        return []
    target = int(batch_size) if isinstance(batch_size, int) and batch_size > 0 else 20
    pool.sort(key=_select_batch_order_key)
    return _pack_first_batch(_group_open_items_by_file(pool), target)


def count_open_items(project_root) -> int:
    """台账当前 open 条目总数（进度 total 的快照源，含被失败集合排除者）。"""
    try:
        items = read_items(project_root)
    except Exception:  # noqa: BLE001
        return 0
    return sum(
        1
        for rec in items.values()
        if isinstance(rec, dict) and rec.get("status") == "open"
    )


def is_chain_last_batch(
    project_root, batch_item_ids, chain_skipped=None, severity_gate=None
) -> bool:
    """链末批判定（add-codefix-affinity-batching 3.1，供批收尾回归分流）。

    与链收敛出口同判据：以链选批同口径排除（失败档案 ∪ ``chain_skipped`` ∪
    延迟台账 ∪ severity 挂起集）后、再排除本批 ``batch_item_ids``，
    ``select_batch`` 返回空 → 本批为末批。MUST 在核销**前**调用（核销会
    改变 open 集）；本批条目集合从既有批上下文取得（ctx["item_ids"]）。

    severity 挂起集（evo-add-codefix-severity-batch-gate 2.1）：排除口径
    经 ``severity_gate`` 并入——select_batch 以同一门限过滤挂起条目（与
    checkpoint 选批门限同口径），挂起条目不阻链末批判定、不计 skipped/lost。

    MUST NOT 用裸 ``count_open_items`` 排除本批判定：其计数含失败档案/
    跳过/延迟等被排除 open 条目（``count_open_items`` docstring），链最后
    一批收尾时这些条目常在档，裸计数 >0 会把实际末批判成非末批 → 定向回归
    → 链随即正常收敛，全量兜底防线整链落空（design D3）。
    """
    exclude = (
        set(chain_skipped or ())
        | set(batch_item_ids or ())
        | _deferred_item_ids(project_root)
    )
    # batch_size=1：装箱目标不影响空/非空判据（任一可选 open 条目都返回非空）
    return not select_batch(
        project_root, 1, exclude_ids=exclude, severity_gate=severity_gate
    )


# ── 批内波次上限自适应（add-codefix-affinity-batching 2.1）────────────

# 波次上限硬上限（防网关限流放大）：任何批规模 MUST NOT 超过
CODE_FIX_WAVE_CAP_MAX = 8


def wave_cap_for_groups(group_count) -> int:
    """批内子代理并发波次上限分档（纯函数，单测直测）。

    G = 批内文件组数（并行真实粒度）：G ≤ 4 → 4；5 ≤ G ≤ 8 → 6；
    G ≥ 9 → 8。8 为硬上限（``CODE_FIX_WAVE_CAP_MAX``）；下限 4（单文件组
    大批不因批变大改变并行判定，spec「单文件大组批仍为下限 4」）。
    """
    try:
        g = int(group_count)
    except (TypeError, ValueError):
        g = 0
    if g >= 9:
        return CODE_FIX_WAVE_CAP_MAX
    if g >= 5:
        return 6
    return 4


# ── 批收尾回归两段式（add-codefix-affinity-batching 3.2/3.3）──────────
#
# 链内非末批批收尾回归按批触碰面定向（verify.yaml regression.cmd 声明
# ``{test_targets}`` 占位符方参与定向化；无占位符/映射空集/配置关回退全量，
# fail-open 防漏检），链末批恒全量兜底。定向回归只缩小测试集——构造替换后
# 的 RegressionSpec 副本传入既有 run_regression（主机级锁/JUnit 解析/硬超时
# 全继承），不新增执行通道。

# regression.cmd 中的测试路径列表占位符（对齐 {port} 占位符先例）
CODE_FIX_TEST_TARGETS_PLACEHOLDER = "{test_targets}"

# 同值导出的环境变量名（cmd 可二选一引用占位符或环境变量）
CODE_FIX_TEST_TARGETS_ENV = "FENIX_TEST_TARGETS"

# 回退路径占位符消毒缺省目标（add-codefix-test-targets-fallback-sanitization）：
# 回退全量出口把占位符替换为 tests/ 而非剥离参数——剥离对 str 形态留双空格、
# 对 list 内嵌形态产生 ``dir=`` 畸变，且 pytest「无收集目标」走 rootdir 收集
# 语义不可控；tests/ 与 _is_test_path 前缀识别、verify.yaml 安全形态缺省
# （${FENIX_TEST_TARGETS:-tests/}）、pytest 中心助手链一致。
CODE_FIX_TEST_TARGETS_FALLBACK = "tests/"


def _is_test_path(rel_path: str) -> bool:
    """测试路径判别（spec 3.2 规则 a）：``tests/`` 下或 ``test_`` 前缀/
    ``_test`` 后缀（后缀按去扩展名后的 stem 判别——``foo_test.py`` 的
    stem ``foo_test`` 以 ``_test`` 结尾）。"""
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel:
        return False
    if rel == "tests" or rel.startswith("tests/"):
        return True
    name = rel.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    # name 支恒被 stem 支覆盖（name 含扩展名时其 ``test_`` 前缀必然蕴含
    # stem 的；无扩展名时两者相同），保留即死条件（code-review item
    # c8dc3902df49）。
    return stem.startswith("test_") or stem.endswith("_test")


def _module_names_for_file(rel_path: str) -> list:
    """产品文件的候选 import 模块名（``core/foo.py`` → ``["core.foo", "foo"]``）。

    带上裸 stem（去目录形态）：测试文件从仓库根与包内目录两个 sys.path 形态
    import 均常见；多召回方向是「多跑测试」（fail-open 侧，design 风险节）。
    """
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    if not rel or rel.endswith("/"):
        return []
    name = rel.rsplit("/", 1)[-1]
    stem = name.rsplit(".", 1)[0] if "." in name else name
    if not stem:
        return []
    names = [stem]
    prefix = rel[: -len(name)].replace("/", ".")
    dotted = prefix + stem
    if dotted != stem:
        names.append(dotted)
    return names


def _map_fix_files_to_tests(fixed_files, exec_root) -> list:
    """触碰面映射（add-codefix-affinity-batching 3.2）：fixed 行 file 集合
    → 测试路径列表。

    规则：(a) 测试文件（``tests/`` 下或 ``test_`` 前缀/``_test`` 后缀）直接
    入选；(b) 产品文件按「同目录 ``tests/`` 的 ``test_<stem>.py`` 命名匹配」
    ∪「``tests/`` 树内 grep import/from 反查」取并集——grep 以 subprocess
    单次 ``grep -rl`` 完成，MUST NOT 逐文件 Python 遍历（tests/ 树可达千
    文件）。

    ``exec_root`` 为回归执行根（code-fix 批=worktree），路径相对其解析；
    返回排序去重后的测试路径列表（相对 exec_root，POSIX 形态）。映射不出
    任何测试路径返回空列表（调用方 fail-open 回退全量并记日志）。探测失败
    （tests/ 缺失、grep 异常）只缩小定向面，MUST NOT 抛异常。
    """
    from pathlib import PurePosixPath

    root = Path(exec_root) if exec_root is not None else Path.cwd()
    direct: set = set()
    product: list = []
    seen: set = set()
    for raw in fixed_files or ():
        rel = str(raw or "").replace("\\", "/").strip()
        while rel.startswith("./"):
            rel = rel[2:]
        rel = rel.strip("/")
        if not rel or rel in seen:
            continue
        seen.add(rel)
        if _is_test_path(rel):
            direct.add(rel)
        else:
            product.append(rel)
    if product:
        # (b1) 同目录 tests/ 的 test_<stem>.py 命名匹配
        for rel in product:
            p = PurePosixPath(rel)
            name = p.name
            stem = name.rsplit(".", 1)[0] if "." in name else name
            parent = str(p.parent)
            cand_dir = parent + "/tests" if parent not in ("", ".") else "tests"
            cand_root = root / cand_dir
            if not cand_root.is_dir():
                continue
            try:
                # stem 拼入 glob 模式前转义（code-review item 209be1ea0334）：
                # 文件名含 [ ] * ? 等元字符时按字面匹配，防字符类/通配语义
                # 误配测试路径。
                for hit in sorted(cand_root.glob(glob.escape(f"test_{stem}.py"))):
                    if hit.is_file():
                        direct.add(hit.relative_to(root).as_posix())
            except OSError:
                continue  # fail-open：glob 失败只缩小定向面
        # (b2) tests/ 树内 import/from 反查（单次 subprocess）
        modules = sorted({m for rel in product for m in _module_names_for_file(rel)})
        tests_dir = root / "tests"
        if modules and tests_dir.is_dir():
            alt = "|".join(re.escape(m) for m in modules)
            pattern = rf"(from|import)\s+({alt})\b"
            try:
                proc = subprocess.run(
                    ["grep", "-rlE", pattern, "tests"],
                    cwd=str(root),
                    capture_output=True,
                    text=True,
                    errors="replace",
                    timeout=60,
                )
                # grep 退出码 0=有匹配 / 1=无匹配（均非错误）；>1 才是故障
                if proc.returncode == 0:
                    for line in proc.stdout.splitlines():
                        rel = line.strip().lstrip("./").strip("/")
                        if rel:
                            direct.add(rel)
            except (OSError, subprocess.SubprocessError, ValueError):
                pass  # fail-open：反查失败只缩小定向面
    return sorted(direct)


def _cmd_has_test_targets(spec) -> bool:
    """regression.cmd 是否声明 ``{test_targets}`` 占位符（str/list 两态）。"""
    if spec is None:
        return False
    cmd = getattr(spec, "cmd", None)
    if isinstance(cmd, str):
        return CODE_FIX_TEST_TARGETS_PLACEHOLDER in cmd
    if isinstance(cmd, (list, tuple)):
        return any(CODE_FIX_TEST_TARGETS_PLACEHOLDER in str(el) for el in cmd)
    return False


def _apply_test_targets(spec, test_targets: list):
    """构造替换 ``{test_targets}`` 后的 RegressionSpec 副本（3.3）。

    str 形态（经 shell 执行）：替换为空格连接、逐路径 ``shlex.quote`` 引用
    的测试路径列表；list 形态（argv 不经 shell）：元素级替换——占位元素恰
    等占位符时展开为路径列表（路径原样不做 shell 引用），元素内嵌占位符时
    以空格连接原样替换进单元素（argv 不经 shell 拆分，该 cmd 形态仅支持
    单目标：目标数 >1 时该元素成含空格的单参数、下游按一条畸形路径收集，
    故多目标时 warning 留痕消除静默畸形，code-review item 69eb2055cc2c）。

    同值导出 ``FENIX_TEST_TARGETS`` 环境变量（对齐 ``{port}`` 占位符先例，
    cmd 可二选一引用）：执行侧经 ``_with_test_targets_env`` 在回归窗口内
    设置。

    返回 ``dataclasses.replace`` 副本（不原地改写既有契约对象）；替换后与
    原 cmd 相同则原样返回（零副本）。
    """
    targets = [str(t) for t in (test_targets or []) if str(t or "").strip()]
    if not targets or not _cmd_has_test_targets(spec):
        return spec
    quoted = " ".join(shlex.quote(t) for t in targets)
    raw = " ".join(targets)
    cmd = spec.cmd
    if isinstance(cmd, str):
        new_cmd: object = cmd.replace(CODE_FIX_TEST_TARGETS_PLACEHOLDER, quoted)
    else:
        new_list: list = []
        for el in cmd:
            s = str(el)
            if s == CODE_FIX_TEST_TARGETS_PLACEHOLDER:
                new_list.extend(targets)  # 元素级展开：占位元素 → 路径列表
            elif CODE_FIX_TEST_TARGETS_PLACEHOLDER in s:
                # 多目标整串替换留痕（code-review item 69eb2055cc2c）：argv
                # 不经 shell 拆分，内嵌占位符的元素按整串替换只支持单目标——
                # 目标数 ≥2 时该元素成含空格的单参数，下游按一条畸形路径收集。
                # 整串替换契约由冻结单测钉住（兼容既有 cmd 写法），此处
                # warning 显式点名限制，消除静默畸形 argv。
                if len(targets) > 1:
                    _logger.warning(
                        "code-fix regression.cmd list 形态元素内嵌 "
                        f"{CODE_FIX_TEST_TARGETS_PLACEHOLDER} 占位符（元素 "
                        f"{s!r}）仅支持单目标，本批目标数 {len(targets)} 将"
                        "整串替换为含空格的单参数（独立占位元素可多目标展开）"
                    )
                new_list.append(s.replace(CODE_FIX_TEST_TARGETS_PLACEHOLDER, raw))
            else:
                new_list.append(el)
        new_cmd = new_list
    if new_cmd == cmd:
        return spec
    return dataclasses.replace(spec, cmd=new_cmd)


class _with_test_targets_env:
    """回归执行窗口内导出 ``FENIX_TEST_TARGETS``（同值双轨，{port} 先例）。

    导出落在进程级 ``os.environ``，窗口覆盖整个 ``run_regression`` 调用——
    含主机级锁的等待期（最长 600s）。等待窗内同进程其他车道（verify /
    dashboard 手动 / admin 定时回归）可正常起跑自身回归，其 regression.cmd
    若声明引用该变量（二选一契约同样适用于它们），会继承本批收窄后的目标
    集——「并发子进程 inert」的论断仅对未声明引用该变量的命令成立，不覆盖
    上述同进程声明引用的车道（收窄到锁后 spawn 点须改 core/regression.py，
    见 item 27971a0d9dd3）。``targets`` 为空时不触碰进程环境。
    """

    def __init__(self, test_targets):
        self._value = " ".join(str(t) for t in (test_targets or []) if str(t or "").strip())
        self._prev = None

    def __enter__(self):
        if self._value:
            self._prev = os.environ.get(CODE_FIX_TEST_TARGETS_ENV)
            # [fenix-ignore:27971a0d9dd3] 进程级导出窗口含回归锁等待期，同进程并发车道 cmd 声明引用该变量会继承本批目标集；收窄到锁后 spawn 点须改 core/regression.py（跨组），暂维持现状
            os.environ[CODE_FIX_TEST_TARGETS_ENV] = self._value
        return self

    def __exit__(self, *exc):
        if self._value:
            if self._prev is None:
                os.environ.pop(CODE_FIX_TEST_TARGETS_ENV, None)
            else:
                os.environ[CODE_FIX_TEST_TARGETS_ENV] = self._prev
        return False


def _sanitize_test_targets(spec):
    """回退路径占位符消毒薄包装（add-codefix-test-targets-fallback-sanitization）。

    回退全量出口（链末批恒全量/映射空集/配置关/定向重试轮两态）把含
    ``{test_targets}`` 占位符的 cmd 原样交给执行层会字面透传（pytest 收集
    字面占位符必挂 → 回归失败 → 整批弃），故回退出口统一把占位符替换为
    缺省 ``tests/``：复用 ``_apply_test_targets`` 的替换语义（str/list
    两态），对无占位符 spec 原样返回（零副本零迁移），可无条件调用。
    """
    return _apply_test_targets(spec, [CODE_FIX_TEST_TARGETS_FALLBACK])


def _fixed_files_from_rows(rows: list) -> list:
    """产物行中 status=fixed 行的 file 集合（保序去重，3.4 映射输入）。"""
    files = [
        str(r.get("file"))
        for r in rows or ()
        if isinstance(r, dict) and r.get("status") == "fixed" and r.get("file")
    ]
    return list(dict.fromkeys(files))


# ── 回归快照→台账 findings 转换与复发重开（add-regression-auto-fix 1.1/1.2）──
#
# 消费端（fenixd._check_regression_fix_requests）把最近一次回归快照
# （core/regression.py 单快照 .fenix/regression/last-run.json）的问题列表
# 转换为 code-fix 台账条目（upsert_findings，category 以 ``regression-`` 为
# 前缀隔离标识）。纯函数化便于单测，不触碰既有批派/验证/合并路径。

# 回归来源条目的 category 前缀（重开语义的唯一作用域标识）
REGRESSION_CATEGORY_PREFIX = "regression-"

# 整体超时条目的 file 锚点（design D4）：upsert_findings 跳过无 file 的发现，
# 而整体超时无逐用例定位；超时处置的真实入口恰是回归硬超时的声明落点
# verify.yaml（先查套件性能，确属超时配置不合理才调声明），以真实存在文件
# 为锚点而非伪造用例路径。
REGRESSION_TIMEOUT_FILE = ".fenix/verify.yaml"

# description 内动态文本（失败 message / 超时 reason / 输出摘要）截断上限
_REGRESSION_EXCERPT_LIMIT = 500


def _regression_excerpt(value, limit: int = _REGRESSION_EXCERPT_LIMIT) -> str:
    """动态文本截断（None 安全）：超限截断加省略号，保持纯函数可单测。"""
    text = value if isinstance(value, str) else ("" if value is None else str(value))
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def _regression_time_text(value) -> str:
    """耗时展示文本：整数耗时不带小数（42.0 → "42s"，42.3 → "42.3s"）。"""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return "未知"
    if num.is_integer():
        return f"{int(num)}s"
    return f"{round(num, 2)}s"


# suggestion 按类目固化文案（单源，spec「长耗时修复语义固化」Requirement）：
# long 类 MUST 含「不改变测试通过结果」前提与优化手段建议——文案随批派
# 注入修复 Agent，是该约束的唯一落点。
REGRESSION_SUGGESTIONS = {
    "regression-failure": (
        "定位该用例失败原因并修复：优先修被测实现，确属测试代码缺陷（断言过期、"
        "夹具失效等）可修测试本身；MUST NOT 以删除/跳过用例的方式掩盖失败。"
    ),
    "regression-error": (
        "定位该用例报错原因并修复：优先修被测实现，确属测试代码缺陷（导入错误、"
        "夹具失效等）可修测试本身；MUST NOT 以删除/跳过用例的方式掩盖错误。"
    ),
    "regression-long-test": (
        "以不改变测试通过结果为前提优化该用例耗时：允许优化被测实现或测试代码"
        "本身（去冗余 sleep、修慢 fixture、并发化等）；MUST NOT 使原测试由通过"
        "变为失败（批验证回归重跑会复核）。"
    ),
}

# 整体超时条目 suggestion（design D4 风险对冲：防修复 Agent 误读为「改配置
# 了事」——先查套件性能，确属超时配置不合理才调声明）
_REGRESSION_TIMEOUT_SUGGESTION = (
    "整体超时处置指引：先排查套件性能问题（慢用例/慢 fixture/可并发化/串行"
    "浪费），按 failure/long-test 思路修复慢的根源；确属回归硬超时声明不合理"
    "（套件本就长于 timeout_seconds 且无性能问题）才调整 .fenix/verify.yaml "
    "的 regression timeout_seconds；MUST NOT 以单纯放宽超时掩盖性能退化。"
)


def convert_regression_snapshot_to_findings(snapshot, output_excerpt: str = "") -> list:
    """回归快照 → code-fix 台账 findings 列表（纯函数，add-regression-auto-fix 1.1）。

    映射固化（spec「daemon 消费信号并转换为台账条目」Requirement）：
    - failures 逐条：kind=failure → category ``regression-failure``；
      kind=error → ``regression-error``；severity 均为 high；title 取用例名；
      description 携带分类、耗时与失败 message（截断 500 字）。
    - long_tests 逐条：category ``regression-long-test``、severity medium。
    - status=timeout：追加单条 ``regression-timeout``（severity high，file 固定
      ``.fenix/verify.yaml``，title「回归整体超时」），description 携带 reason 与
      输出摘要（``output_excerpt`` 由消费端预读快照 output 字段指向的日志文件
      尾部传入，读取失败置空；函数内截断 500 字）。

    输入容错：snapshot 缺失/非 dict/字段缺失不抛异常，返回空列表（消费端
    以当下快照为准，转换零条目时仍可继续走 checkpoint 既有守卫）。
    """
    findings: list = []
    if not isinstance(snapshot, dict):
        return findings

    failures = snapshot.get("failures")
    if isinstance(failures, list):
        for item in failures:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "failure")
            category = (
                f"{REGRESSION_CATEGORY_PREFIX}error"
                if kind == "error"
                else f"{REGRESSION_CATEGORY_PREFIX}failure"
            )
            name = str(item.get("name") or "").strip() or "unnamed"
            desc = (
                f"回归失败用例（{category}），耗时 {_regression_time_text(item.get('time'))}；"
                f"信息：{_regression_excerpt(item.get('message'))}"
            )
            findings.append({
                "file": str(item.get("file") or ""),
                "line": item.get("line"),
                "severity": "high",
                "category": category,
                "title": name,
                "description": desc,
                "suggestion": REGRESSION_SUGGESTIONS.get(
                    category, REGRESSION_SUGGESTIONS["regression-failure"]
                ),
                "evidence": "",
            })

    long_tests = snapshot.get("long_tests")
    if isinstance(long_tests, list):
        for item in long_tests:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip() or "unnamed"
            time_text = _regression_time_text(item.get("time"))
            findings.append({
                "file": str(item.get("file") or ""),
                "line": item.get("line"),
                "severity": "medium",
                "category": f"{REGRESSION_CATEGORY_PREFIX}long-test",
                "title": name,
                "description": (
                    f"长耗时用例（{REGRESSION_CATEGORY_PREFIX}long-test），"
                    f"耗时 {time_text}，超出回归长耗时阈值"
                ),
                "suggestion": REGRESSION_SUGGESTIONS["regression-long-test"],
                "evidence": "",
            })

    if str(snapshot.get("status") or "") == "timeout":
        desc = (
            "回归整体超时（未完成，无逐用例定位）；原因："
            + (_regression_excerpt(snapshot.get("reason")) or "未提供")
        )
        excerpt = _regression_excerpt(output_excerpt)
        if excerpt:
            desc += f"；输出摘要：{excerpt}"
        findings.append({
            "file": REGRESSION_TIMEOUT_FILE,
            "line": 1,
            "severity": "high",
            "category": f"{REGRESSION_CATEGORY_PREFIX}timeout",
            "title": "回归整体超时",
            "description": desc,
            "suggestion": _REGRESSION_TIMEOUT_SUGGESTION,
            "evidence": "",
        })

    return findings


def regression_findings_fingerprints(findings: list) -> set:
    """转换产物的指纹集合（重开语义的 live 集合；无 file/title 的条目跳过，
    与 upsert_findings 的关键字段硬规则同口径）。"""
    out: set = set()
    for finding in findings or []:
        if not isinstance(finding, dict):
            continue
        file_ = str(finding.get("file") or "")
        title = str(finding.get("title") or "")
        category = str(finding.get("category") or "")
        if not file_ or not title:
            continue
        out.add(fingerprint(file_, category, title))
    return out


def reopen_regression_items(project_root, live_fps) -> int:
    """重开复发的回归条目（add-regression-auto-fix 1.2）。

    仅 category 以 ``regression-`` 为前缀、fingerprint 命中 ``live_fps``
    （本次快照问题集指纹）且 status 非 open 的条目：status 重开为 open 并
    刷新 first_seen_at——保证同问题复发可再次触发修复（否则链会以
    no_open_items 拒绝、按钮一次性失效）。

    非 ``regression-`` 前缀条目（code-review 来源）零触碰，即使 file/title
    恰好同名（fingerprint 只在回归前缀子集内比对）。

    读-改-写 + flock 与台账写同锁（``_with_lock``；锁内 MUST NOT 再次加
    同一把锁）。Returns: 重开条目数。
    """
    fps = {fp for fp in (live_fps or ()) if isinstance(fp, str) and fp}
    if not fps:
        return 0
    now = _now_iso()
    path = items_path(project_root)
    reopened = 0

    def _do() -> None:
        nonlocal reopened
        corrupted: list = []
        read_degraded: list = []
        current = _read_items_unlocked(path, corrupted_out=corrupted, degraded_out=read_degraded)
        if read_degraded:
            # 读降级（OSError 类）：拒绝本次全量替换，保持台账原样
            #（code-review item 9a358bba128c）
            _logger.warning("code_review: items.jsonl 读取降级，regression 重开跳过落盘")
            return
        changed = False
        for rec in current.values():
            if not str(rec.get("category") or "").startswith(REGRESSION_CATEGORY_PREFIX):
                continue
            if rec.get("status") == "open":
                continue
            if rec.get("fingerprint") not in fps:
                continue
            rec["status"] = "open"
            rec["first_seen_at"] = now
            rec["last_seen_at"] = now
            reopened += 1
            changed = True
        if changed:
            content = "".join(
                json.dumps(current[k], ensure_ascii=False) + "\n" for k in sorted(current)
            )
            # JSON 损坏行原样回写保留（code-review item 9a358bba128c）
            content += "".join(raw + "\n" for raw in corrupted)
            _atomic_write(path, content)

    _with_lock(path, _do)
    return reopened


# ── 产物解析（编排侧读 out 文件；与 run_code_fix 的写入口径一致）────────


def read_fix_out(worktree, run_id: str) -> list:
    """读取 code-fix run 的增量产物 ``fix-out-<run_id>.jsonl``。

    每行一个条目处置结果（``{item_id, status, file}``）。损坏行跳过；
    文件缺失返回空列表（run 失败路径由 CodeFixResult.success 承载）。
    """
    path = Path(worktree) / ".fenix" / "code-review" / f"fix-out-{run_id}.jsonl"
    rows: list = []
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        if isinstance(rec, dict) and rec.get("item_id"):
            rows.append(rec)
    return rows


def _split_fix_rows(rows: list) -> tuple:
    """批收尾产物行分区（纯函数，LLM 拒绝出口 2026-09-23）。

    返回 ``(fixed_ids, skip_reasons)``：

    - ``fixed_ids``：``status == "fixed"`` 的条目 id（保序去重）——合回后
      经 ``mark_resolved`` 核销；
    - ``skip_reasons``：``item_id → skip_reason``，仅收录 ``status ==
      "skipped"`` 且 skip_reason ∈ ``IGNORE_ELIGIBLE_SKIP_REASONS``（判误报/
      不值得修，批收尾经 ``mark_ignored`` 置终态）。同条目多行时**后行覆盖
      前行**——先按 ``item_id`` 取末行再做白名单过滤（并集口径下重试轮的
      判定更新生效，含以普通 skipped 撤回可忽略标注）；但最终态为 fixed
      的条目 MUST NOT 出现在 skip_reasons——「首轮 skipped 判误报、重试
      轮 fixed」以 fixed 为准（不降级）。
    """
    fixed_ids = [r.get("item_id") for r in rows if r.get("status") == "fixed"]
    fixed_ids = list(dict.fromkeys(fixed_ids))
    fixed_set = set(fixed_ids)
    # 先取末行再过滤（后行覆盖的生效前提）：若边过滤边收行，重试轮的普通
    # skipped（无可忽略标注）会被白名单直接丢掉，首轮陈旧 false_positive
    # 判定残留并被 mark_ignored 洗成 ignored 终态，违背缺省保守。
    last_rows = {r.get("item_id"): r for r in rows}
    skip_reasons = {
        item_id: last.get("skip_reason")
        for item_id, last in last_rows.items()
        if last.get("status") == "skipped"
        and last.get("skip_reason") in IGNORE_ELIGIBLE_SKIP_REASONS
        and item_id not in fixed_set
    }
    return fixed_ids, skip_reasons


def _apply_llm_reject_exits(root, wt, run_ids, batch_item_ids) -> tuple:
    """LLM 拒绝出口共用分区（批收尾合回路径与定向重试耗尽收口共用）。

    读取首轮与各定向轮产物行**并集**（定向轮产物是独立文件
    ``fix-out-<retry_run_id>.jsonl``：首轮与各定向轮改动都落在同一 worktree、
    随同一次收尾出账，只读首次 run 会漏掉「重试才修复/重试才标注」的条目）
    → ``_split_fix_rows`` 分区 → 本批 ``item_ids`` 批界过滤（mark_ignored
    对命中 id 无条件置终态、无批界保护，agent 产物行带出的批外 open 条目
    MUST NOT 被置终态，与核销前 batch_set 守卫同口径）→ ``mark_ignored``
    置终态。

    返回 ``(ignored 命中数, ignore_set, fixed_ids)``：链级核销计数累加
    （``_chain_bump``）与批内排除集续接由调用方按各自收尾语义完成。模块内
    去重（code-review item a65abf0929ce）：白名单/后行覆盖/批界过滤的判定
    口径单源，两条收尾路径不再各自复刻（86cf2dca9179 的不拆分裁决针对跨
    模块抽取，不适用于此）。
    """
    rows = read_fix_out(wt, run_ids[0]) if run_ids else []
    for rid in run_ids[1:]:
        rows.extend(read_fix_out(wt, rid))
    fixed_ids, skip_reasons = _split_fix_rows(rows)
    batch_set = set(batch_item_ids)
    ignore_ids = [i for i in skip_reasons if i in batch_set]
    ignored = (
        mark_ignored(root, ignore_ids, reasons=skip_reasons)
        if ignore_ids
        else 0
    )
    return ignored, set(ignore_ids), fixed_ids


def _worktree_commit_count(worktree, created_sha: str):
    """worktree 分支相对建树点的提交数（零有效修复守卫的 git 侧判据，5.8）。

    返回 ``None`` 表示 git 判据不可用（非零退出/超时/输出非数值），与
    「确认零提交」区分（code-review item e992bc1af898）——瞬时故障按 0
    返回会把已提交修复的有效批误判拒合回、弃置成果。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-list", "--count", f"{created_sha}..HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return None
        return int(out.stdout.strip() or "0")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _worktree_head(worktree) -> str:
    """worktree 当前 HEAD sha（判据不可得返回空串；code-review item 09ed10f24830）。

    rev-parse 失败（无提交仓库/引用解析失败）时 git 会向 stdout 输出字面量
    "HEAD" 且退出码非零——只取 stdout 会把垃圾值当有效 sha 返回（绕过建树点
    ``created_sha`` 空串守卫、污染失败档案/延迟台账的 tip_sha 追溯字段），对齐
    ``_branch_head`` 口径按非零退出返回空串，由调用方既有「判据不可得」分支兜底。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _worktree_branch(worktree) -> str:
    """worktree 分支名（失败档案的追溯线索之一，selfheal D2；判据不可得返回空串）。

    rev-parse 失败（无提交仓库/引用解析失败）时 git 会向 stdout 输出字面量
    "HEAD" 且退出码非零——只取 stdout 会把垃圾值当分支名返回（写入失败档案
    /延迟台账的 branch 追溯字段、甚至成为 _salvage_restore_branch 的 checkout
    目标而分离头），对齐 ``_worktree_head``/``_branch_head`` 口径按非零退出
    返回空串（code-review item 8793c23ff014），由调用方既有「判据不可得」
    分支兜底。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if out.returncode != 0:
            return ""
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _worktree_porcelain(worktree) -> str:
    """worktree 未提交改动原文（``git status --porcelain``；异常返回空串）。

    salvage 三元组的第三元判据（add-codefix-commit-first-contract D2）：
    排在产物行与提交数之后——porcelain 只在怀疑搁浅时执行。porcelain 不含
    gitignored 文件，worktree 内运行时产物（``.fenix/`` 等，经 .gitignore
    不入库）不会被卷入。
    """
    try:
        out = subprocess.run(
            ["git", "-C", str(worktree), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return out.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _salvage_commit(worktree, message: str) -> bool:
    """把 worktree 未提交改动自动提交到批分支（编排 salvage 兜底，2.1）。

    ``git add -A``（worktree 内本就只有批分支工作区；gitignored 噪音经
    add 语义天然排除）；任一步失败返回 False，由调用方回落既有拒合回语义。
    """
    try:
        add = subprocess.run(
            ["git", "-C", str(worktree), "add", "-A"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if add.returncode != 0:
            return False
        commit = subprocess.run(
            ["git", "-C", str(worktree), "commit", "-m", message],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return commit.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


# ── 合回冲突定向救回的 git 取证原语（evo-add-codefix-mergeback-conflict-salvage）──


def _git_try(worktree, args: list, timeout: float = 120):
    """worktree 内跑一条 git 命令，返回 CompletedProcess。

    超时/OSError 返回 None——调用方按「判据不可得」保守处理（救回降级/放弃，
    回落既有整批入档案兜底），MUST NOT 向批 worker 上抛。text 解码按
    ``errors="replace"`` 容错（对齐同模块 read_fix_out/_read_run_metrics 纪律，
    code-review item 83e76f5ab735）：git 输出含非 UTF-8 字节（提交消息原文
    可含任意字节）时，严格解码会在 run() 内部抛 UnicodeDecodeError——既非
    OSError 也非 SubprocessError，不在本函数捕获面内，会直接上穿炸掉救回与
    收尾流程；容错后坏字节只废该条输出。
    """
    try:
        return subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _salvage_batch_commits(worktree, created_sha: str) -> list:
    """批分支相对建树点的提交清单（旧→新序）；判据不可得返回空清单。

    在救回入口（rebase/cherry-pick 改写分支前）枚举一次：rebase 会改写提交
    SHA，``created_sha..HEAD`` 在改写后不再可用，原始 SHA 由 reflog 保全、
    cherry-pick 跨基线照常可用。"""
    if not created_sha:
        return []
    res = _git_try(
        worktree, ["rev-list", "--reverse", f"{created_sha}..HEAD"], timeout=30,
    )
    if res is None or res.returncode != 0:
        return []
    return [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]


def _commit_changed_paths(worktree, sha: str):
    """提交触碰的文件路径清单；git 判据不可得返回 None（保守按不可回收）。"""
    res = _git_try(
        worktree,
        ["diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha],
        timeout=30,
    )
    if res is None or res.returncode != 0:
        return None
    return [ln.strip() for ln in (res.stdout or "").splitlines() if ln.strip()]


def _commit_item_ids(worktree, sha: str):
    """解析提交 body 的 ``items:`` 清单（agents/code-fix.md 契约的归属单源）。

    返回条目 id 清单；body 无 ``items:`` 行（旧契约提交）或 git 判据不可得
    返回 None——调用方保守处理：不做无据归属，剩余未出账条目整体随兜底入
    失败档案（与现状整批入档同口径）。"""
    res = _git_try(worktree, ["show", "-s", "--format=%B", sha], timeout=30)
    if res is None or res.returncode != 0:
        return None
    for line in (res.stdout or "").splitlines():
        s = line.strip()
        if s.startswith("items:"):
            return [p.strip() for p in s[len("items:"):].split(",") if p.strip()]
    return None


def _branch_head(worktree, branch: str) -> str:
    """分支引用当前指向（入档追溯线索；判据不可得返回空串）。"""
    res = _git_try(
        worktree, ["rev-parse", "--verify", "--quiet", branch], timeout=30,
    )
    if res is None or res.returncode != 0:
        return ""
    return (res.stdout or "").strip()


def _salvage_restore_branch(worktree, branch0: str) -> bool:
    """救回放弃时把 worktree 还原回批分支（尽力而为）。

    先 abort 可能挂在飞中的 cherry-pick，再 checkout 回批分支。任一步失败
    返回 False：现场随既有 ``cleanup(success=False)`` 的 recovery legacy 保全，
    不影响兜底入档案（``_wt_branches`` 登记的批分支名与 checkout 态无关）。"""
    _git_try(worktree, ["cherry-pick", "--abort"], timeout=60)
    res = _git_try(worktree, ["checkout", branch0], timeout=60)
    return res is not None and res.returncode == 0


# ── 回归契约缺失信号（5.5 / D5，分流口径对齐 regression_routes 既有区分）──

# 「项目名=」字段解析单源：core.admin_store.evidence_project
# （原模块级 `_evidence_project` 副本已收敛，mergeback / settings_routes 同款）。


def _log_alert_rejected(logger, signal_type: str) -> None:
    """AdminStore.append 返回 None（文件损坏留底被下限保护拒写，记录未落盘）
    时的留痕（code-review item bea407d9016c）：一次性告警（如
    code_fix_retry_budget_exhausted）无重发机制，拒写即静默丢失，MUST 至少
    记 warning；日志失败无副作用。logger 为 None（无日志器调用形态）跳过。
    """
    if logger is None:
        return
    try:
        logger.warning(
            "code-fix",
            f"告警写盘被 AdminStore 下限保护拒写（记录未落盘）: {signal_type}",
        )
    except Exception:  # noqa: BLE001 — 留痕失败不影响主流程
        pass


def _signal_inflight(store, signal_type: str, project_name: str) -> bool:
    """同项目同类型、未摄取未处置的在途信号已存在 → 不重复写。"""
    from core.admin_store import SIGNAL, evidence_project

    for rec in store.read_all():
        if rec.get("kind") != SIGNAL or rec.get("signal_type") != signal_type:
            continue
        if rec.get("handled") or rec.get("escalated"):
            continue
        # 项目名按字段全等比较而非裸子串：``项目名=web`` 不得命中
        # ``项目名=webapp``（前缀关系项目名互判在途 → 新信号被静默跳写）。
        if evidence_project(str(rec.get("evidence") or "")) == project_name:
            return True
    return False


def write_regression_signal(project_root, signal_type: str, logger=None) -> None:
    """写回归契约缺失信号（AdminStore kind=SIGNAL 通道，fail-closed 附属动作）。

    分流口径（MUST 对齐 core/dashboard/routes/regression_routes.py:195-236
    与 core/admin_monitor.py:214-216 的既有区分，用错信号会令 administrator
    重写一份有效且在服务的 prepare/serve/ready）：
    - ``verify_contract_missing``：契约整体缺失 → 起草**完整**契约；
    - ``verify_regression_missing``：契约有效仅缺 regression 段 → **仅补段**。
    payload 形态对齐既有 `_api_regression_autodraft_post` 写入（含
    signal_type/spec/severity:"major"/description/evidence/recommended_action），
    evidence 携带 ``项目名=`` 供 admin_monitor 摄取（无 spec 信号）。
    """
    from core.admin_store import AdminStore, SIGNAL

    project_name = Path(project_root).name
    store = AdminStore(project_root, logger=None)
    if _signal_inflight(store, signal_type, project_name):
        return
    if signal_type == "verify_contract_missing":
        description = "code-fix 车道 fail-closed：verify.yaml 契约整体缺失，请 Administrator 起草完整契约（含 regression 段）"
        recommended = (
            "Administrator 按 agents/administrator.md 的契约起草手册生成完整 "
            ".fenix/verify.yaml（有测试体系时一并生成 regression 段）并自证落位；"
            "完成后下一轮 full scan 自动续做自动修复。"
        )
    else:
        description = "code-fix 车道 fail-closed：verify.yaml 缺 regression 段，请 Administrator 仅补该段"
        recommended = (
            "Administrator 仅补 regression 段（MUST NOT 动 prepare/serve/ready 与"
            "其它顶层键），自证落位后 git 提交；完成后下一轮 full scan 自动续做自动修复。"
        )
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": signal_type,
            "spec": None,
            "severity": "major",
            "description": description,
            "evidence": (
                f"项目名={project_name}; code-fix 车道在派批前经 "
                f"load_verify_contract 检测到 {signal_type}，本批 fail-closed 未合回"
            ),
            "source": "code-fix-lane",
            "recommended_action": recommended,
        }
    )
    if rec is None:
        _log_alert_rejected(logger, signal_type)
    else:
        if logger is not None:
            try:
                logger.warning("code-fix", f"已写回归契约缺失信号: {signal_type}")
            except Exception:  # noqa: BLE001 — 日志失败不影响信号落盘
                pass


def write_regression_failed_alert(
    project_root, item_ids, worktree, failures_summary: str,
    branch="", tip_sha="", logger=None,
    retry_rounds: int = TARGETED_RETRY_MAX_DEFAULT,
    reg_form: str = "", reason: str = "",
) -> None:
    """回归多轮（首轮 + 定向重试）耗尽仍失败丢弃批时写失败告警。

    ``retry_rounds``：定向重试轮数，调用方按生效 targeted_retry_max 传入
    （缺省 TARGETED_RETRY_MAX_DEFAULT），文案按「首轮 + N 轮重试」如实
    描述回归轮数——历史文案「两次全量回归均未通过」已随定向重试机制
    漂移（add-codefix-targeted-retry），不再使用。
    ``reg_form``（可选，evo-add-codefix-anomaly-redispatch-budget 1.3）：
    ``anomaly`` 时切换为异常形态降档/停派文案（零失败面、预算降档耗尽、
    停止自动重派）——signal_type 不变（复用既有通道，不新增告警类型），
    一次性判重由调用方以失败档案记录上的 ``budget_alerted`` 标记承担
    （本通道与 AdminStore 去重白名单均无对此类型的指纹去重）。
    ``reason``（可选）：失败档案 reason 标识，随 evidence 留痕供检索。
    ``worktree`` 形参保留兼容既有签名，但现场即弃后 worktree 已清理，
    evidence 改以 ``branch``/``tip_sha`` 作为追溯线索（git reflog 可找回）。
    ``logger``（可选）：AdminStore 拒写（记录未落盘）时留痕。
    """
    from core.admin_store import AdminStore, SIGNAL

    if reg_form == REG_FORM_ANOMALY:
        description = (
            "code-fix 批回归终局为零失败面（reg_form=anomaly：parse_error、"
            f"failed 无明细或 timeout 无明细），自动重派预算按分档降为 "
            f"{ANOMALY_FAIL_RETRY_MAX} 且已耗尽，停止自动重派，待人工排查"
        )
        recommended = (
            "零失败面整批重派无证据价值，已停止自动重派；按 branch/tip_sha 经 "
            "git reflog 追溯丢弃的修复提交，人工排查后调用 "
            "core.code_fix.release_failed_batch 解除该批条目的跳过"
        )
    else:
        # [fenix-ignore:eebdeefa1bc6] 告警文案已随定向重试机制改为「首轮 + N 轮定向重试」如实描述（retry_rounds 由调用方按生效上限传入），「两次全量回归」旧文案已废除；reason 标识 regression_failed_twice 保持历史兼容名并已在批收尾 record_failed_batch 调用处加注。
        description = (
            f"code-fix 批首轮及 {retry_rounds} 轮定向重试共 "
            f"{retry_rounds + 1} 轮回归均未通过，已跳过（未合回、条目保持 open，"
            "worktree 已清理，下轮自动重试）"
        )
        recommended = (
            "已跳过，下轮自动重试（达重试上限后需人工介入）；丢弃的修复提交"
            "可按 branch/tip_sha 经 git reflog 追溯"
        )
    evidence = (
        f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
        f"tip_sha={tip_sha or 'unknown'}; "
    )
    if reg_form:
        evidence += f"reg_form={reg_form}; "
    evidence += f"item_ids={', '.join(str(i) for i in item_ids)}; "
    if reason:
        evidence += f"失败原因: {reason}; "
    evidence += f"失败用例摘要: {failures_summary[:2000]}"
    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_regression_failed",
            "spec": None,
            "severity": "warning",
            "description": description,
            "evidence": evidence,
            "source": "code-fix-lane",
            "recommended_action": recommended,
        }
    )
    if rec is None:
        _log_alert_rejected(logger, "code_fix_regression_failed")


def _write_anomaly_budget_alert(
    project_root, item_ids, reason, branch, tip_sha, logger=None
) -> None:
    """anomaly 形态降档/停派一次性告警（evo-add-codefix-anomaly-redispatch-budget 1.3）。

    复用 ``write_regression_failed_alert`` 通道（signal_type
    ``code_fix_regression_failed`` 不变，不新增告警类型），文案登记
    reg_form 与被跳过条目；一次性判重由 ``record_failed_batch`` 锁内置于
    失败记录的 ``budget_alerted`` 标记承担（拒写即丢失与既有触顶告警同
    口径）。与既有每次失败的常规收口告警并存（后者仍在批收尾按次发送）。
    """
    write_regression_failed_alert(
        project_root, item_ids, "", "",
        branch=branch, tip_sha=tip_sha, logger=logger,
        reg_form=REG_FORM_ANOMALY, reason=reason,
    )


def _epoch_iso(ts: float) -> str:
    """epoch 秒 → UTC ISO8601（冷却告警 evidence 的到期时刻展示形态）。"""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── 每日夜间静默窗（evo-codefix-night-quiet-window 1.1）─────────────────────

# 缺省窗区间（本地时刻）：死亡集中于 04:31-04:34，断窗本体 04:30:01-04:31:23
# 加 DNS 余波；窗起点须早于批链典型批时长对应的最早在飞启动时刻。不在模板
# 强配（与冷却 300 秒缺省同策略），空串/off 显式禁用。
NIGHT_QUIET_WINDOW_DEFAULT = "04:15-04:45"

# 「预计跨窗」时长估计样本数（evo-add-night-window-inflight-guard 1.1，design
# D1）：取同链最近 N 批 run_metrics ``duration_s`` 均值作预计批时长——近批
# 实测对慢批次自适应，均值对快/慢批折中保守；无有效样本回退仅判派发时刻。
NIGHT_QUIET_DURATION_SAMPLE_LIMIT = 3

_NIGHT_QUIET_HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")


def _night_quiet_window_disabled(raw) -> bool:
    """空串/off（大小写不敏感）＝显式禁用静默窗（合法值，非法告警不覆盖它）。"""
    text = str(raw if raw is not None else "").strip().lower()
    return text in ("", "off")


def _parse_night_quiet_hhmm(fragment: str):
    """"HH:MM" → 当日分钟数；非法返回 None（小时<24、分钟<60）。"""
    m = _NIGHT_QUIET_HHMM_RE.match(fragment.strip())
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def _parse_night_quiet_windows(raw):
    """解析多窗列表 → ``[(start_min, end_min, text), …]``；禁用/非法返回 None。

    多窗化（evo-add-review-night-defer-snapshot-writeoff 1.1）：上游断窗并非
    单点（kern.log 保留期内 04:30 窗外已现 6 次散布断窗），单窗模型对
    "03:00-03:15,04:15-04:45" 形态无覆盖——升级为逗号/分号分隔的多窗列表，
    命中任一窗即避让。每段走既有单段校验（``_parse_night_quiet_hhmm``，
    ``HH:MM-HH:MM``；end<=start 含相等逆序非法——本场景不要求跨午夜，小时/
    分钟越界同样非法）；空段（如 ``"04:15-04:45,,"``）同按非法。任一段非法
    → 整体返回 None（宁缺毋错，不部分生效）。空串/off 禁用语义与单窗版一致
    （返回 None；禁用不触发 WARNING 由调用方以
    ``_night_quiet_window_disabled`` 区分）。本函数纯解析不告警。
    """
    text = str(raw if raw is not None else "").strip()
    if _night_quiet_window_disabled(text):
        return None
    windows = []
    for fragment in text.replace(";", ",").split(","):
        fragment = fragment.strip()
        parts = fragment.split("-")
        if len(parts) != 2:
            return None
        start = _parse_night_quiet_hhmm(parts[0])
        end = _parse_night_quiet_hhmm(parts[1])
        if start is None or end is None or end <= start:
            return None
        windows.append((start, end, fragment))
    return windows or None


def _parse_night_quiet_window(raw):
    """解析 "HH:MM-HH:MM" → ``(start_min, end_min, text)``；禁用/非法返回 None。

    单窗薄包装（evo-add-review-night-defer-snapshot-writeoff 1.1）：内部改调
    多窗版取首窗，保持旧签名与旧返回值（既有消费方/测试逐字节兼容）；多窗
    列表解析见 ``_parse_night_quiet_windows``。本函数纯解析不告警，非法值的
    WARNING 由调用方（``_night_quiet_window``）按「一次」纪律补。
    """
    windows = _parse_night_quiet_windows(raw)
    if not windows:
        return None
    return windows[0]


def _local_window_end_epoch(end_min: int) -> float:
    """今日本地窗末时刻 → epoch 秒（静默窗「下一可投递时刻」比较/展示基准）。

    以 ``time.localtime`` 当前本地日期 + 窗末时分构造（与守卫判定同源，不
    引入第二个时钟面；DST 交由 mktime 按墙钟自行判定）。
    """
    lt = time.localtime()
    return time.mktime((
        lt.tm_year, lt.tm_mon, lt.tm_mday,
        end_min // 60, end_min % 60, 0,
        lt.tm_wday, lt.tm_yday, -1,
    ))


CODE_FIX_COOLDOWN_SIGNAL_TYPE = "code_fix_switch_window_deferred"

# 夜间静默窗告警 signal_type（与冷却告警同 source/kind，独立类型便于过滤）
CODE_FIX_NIGHT_QUIET_SIGNAL_TYPE = "code_fix_night_quiet_window"


def _write_switch_cooldown_alert(
    project_root, run_id: str, cause_text: str, until_ts: float,
    cooldown_seconds: float, logger=None,
) -> None:
    """连接类失败冷却触发告警（evo-add-codefix-conn-error-cooldown 2.3，D5）。

    经 AdminStore 写 kind=SIGNAL（signal_type=code_fix_switch_window_deferred，
    source=code-fix-lane），evidence 携带 run_id / 死因文本 / 到期时刻（spec
    R3）；AdminStore 拒写（文件损坏留底被下限保护拒写，记录未落盘）走
    ``_log_alert_rejected`` 留痕。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": CODE_FIX_COOLDOWN_SIGNAL_TYPE,
            "spec": None,
            "severity": "warning",
            "description": (
                "code-fix 批死于上游连接类 api_error，同链下一批派发已推迟"
                f"至冷却到期（{cooldown_seconds:.0f} 秒）"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; run_id={run_id or 'unknown'}; "
                f"死因={str(cause_text or 'unknown')[:300]}; "
                f"冷却到期={_epoch_iso(until_ts)}; 冷却时长={cooldown_seconds:.0f}s"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "上游网关连接性窗口通常自愈：冷却到期后同链下一批自动恢复投递，"
                "无需人工介入；若跨日同刻复发请检查网关侧定时故障"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, CODE_FIX_COOLDOWN_SIGNAL_TYPE)


def _write_switch_cooldown_release_alert(
    project_root, until_ts: float, deferred_seconds: float, logger=None,
) -> None:
    """冷却解除告警（evo-add-codefix-conn-error-cooldown 2.3，D5）。

    无后台定时器写入口：由冷却到期后**首个通过守卫的 checkpoint** 补写一条，
    evidence 携带实际推迟时长（=该 checkpoint 时刻 − 冷却起点）；冷却期内无
    后续 checkpoint 通过（台账清空空转）则不写解除。拒写留痕同触发告警。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": CODE_FIX_COOLDOWN_SIGNAL_TYPE,
            "spec": None,
            "severity": "warning",
            "description": "code-fix 连接类失败冷却到期，恢复同链下一批投递",
            "evidence": (
                f"项目名={Path(project_root).name}; "
                f"冷却到期={_epoch_iso(until_ts)}; 实际推迟={deferred_seconds:.0f}s"
            ),
            "source": "code-fix-lane",
            "recommended_action": "冷却已解除，同链下一批已恢复投递，无需操作",
        }
    )
    if rec is None:
        _log_alert_rejected(logger, CODE_FIX_COOLDOWN_SIGNAL_TYPE)


def _write_night_quiet_window_alert(
    project_root, window_text: str, window_date: str, until_ts: float,
    logger=None,
) -> None:
    """夜间静默窗武装告警（evo-codefix-night-quiet-window 1.1）。

    形态对齐 ``_write_switch_cooldown_alert``：经 AdminStore 写 kind=SIGNAL
    （signal_type=code_fix_night_quiet_window，source=code-fix-lane），
    evidence 携带窗次（含日期）/窗区间/下一可投递时刻。「按窗次至多一次」
    的幂等由调用方（checkpoint 守卫读 ``night_quiet_armed_date``）保证，
    本函数纯写。AdminStore 拒写走 ``_log_alert_rejected`` 留痕。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": CODE_FIX_NIGHT_QUIET_SIGNAL_TYPE,
            "spec": None,
            "severity": "warning",
            "description": (
                "code-fix 批投递进入每日夜间静默窗，窗内暂停启动新批"
                "（本机每日固定上游断窗的防御性投递闸）"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; 窗次={window_date}; "
                f"窗区间={window_text}; 下一可投递时刻={_epoch_iso(until_ts)}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "静默窗窗末自动恢复投递，无需人工介入；如需关闭可将 "
                "admin.code_review_fix.night_quiet_window 置 off"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, CODE_FIX_NIGHT_QUIET_SIGNAL_TYPE)


def _write_night_quiet_window_release_alert(
    project_root, window_text: str, window_date: str, logger=None,
) -> None:
    """静默窗解除告警（形态对齐 ``_write_switch_cooldown_release_alert``）。

    无后台定时器写入口：由窗末/配置关闭后**首个通过守卫的 checkpoint** 补写
    一条并清窗次标识（惰性清理，标识不拦截投递）；窗末后无后续 checkpoint
    通过（台账清空空转）则不写解除。evidence 窗区间取武装时快照
    （``night_quiet_armed_text``），配置中途变更不使解除记录失真。拒写留痕
    同武装告警。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": CODE_FIX_NIGHT_QUIET_SIGNAL_TYPE,
            "spec": None,
            "severity": "warning",
            "description": "code-fix 每日夜间静默窗结束，恢复同链下一批投递",
            "evidence": (
                f"项目名={Path(project_root).name}; 窗次={window_date}; "
                f"窗区间={window_text or 'unknown'}"
            ),
            "source": "code-fix-lane",
            "recommended_action": "静默窗已结束，同链下一批已恢复投递，无需操作",
        }
    )
    if rec is None:
        _log_alert_rejected(logger, CODE_FIX_NIGHT_QUIET_SIGNAL_TYPE)


def _write_retry_exhausted_alert(
    project_root, item_ids, reason, branch, tip_sha, logger=None,
    budget: int = FAIL_RETRY_MAX,
) -> None:
    """失败档案条目集 fail_count 达生效预算时的一次性 warning 告警（D4）。

    点名录条目集与历次失败原因；此后该记录不再被释放、不再触发新告警。
    ``budget``：生效自动重派预算（调用方按记录分档传入），文案如实呈现。
    ``logger``（可选）：AdminStore 拒写（记录未落盘）时留痕——本告警仅
    fail_count 恰好递增至上限的那次入档发送、无重发机制，拒写即永久丢失。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_retry_budget_exhausted",
            "spec": None,
            "severity": "warning",
            "description": (
                f"code-fix 失败批自动重试已达上限（{budget} 轮），"
                "停止自动重派，待人工排查"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"tip_sha={tip_sha or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"失败原因: {reason or 'unknown'}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "按 branch/tip_sha 经 git reflog 追溯丢弃的修复提交，人工排查后"
                "调用 core.code_fix.release_failed_batch 解除该批条目的跳过"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, "code_fix_retry_budget_exhausted")


def _write_defer_info_alert(
    project_root, item_ids, overlap, branch="", logger=None
) -> None:
    """首次进入 defer 路径的 info 提示（fix-codefix-wipgate-defer 1.3）。

    正文含 last_overlap 交集文件清单；处置话术复用 mergeback.py 升级出口
    （「提交（git add/commit）或 stash（git stash push）主树这些改动」）。
    ``logger``（可选）：AdminStore 拒写（记录未落盘）时留痕。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_wip_gate_deferred",
            "spec": None,
            "severity": "info",
            "description": (
                "code-fix 批合回被主树未提交改动挡住（WIP overlap 预检阻断），"
                "批已保留（worktree 与分支未动、不烧失败预算），主树清理后链"
                "边界自动合回核销"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"重叠文件: {_fmt_overlap(overlap)}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "提交（git add/commit）或 stash（git stash push）主树这些改动后，"
                "无需人工重派——链边界（选批前/收敛出口）自动重试合回"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, "code_fix_wip_gate_deferred")


def _write_defer_expired_alert(
    project_root, item_ids, overlap, branch="", tip_sha="", logger=None
) -> None:
    """延迟批预算耗尽降级的一次性 warning 告警（D6/3.2）。

    一次性语义按条目集指纹（调用方以 ``_has_expired_archive`` 先查后记——
    同 fix-failed「递增至上限那次发一次性 warning」先例）。``logger``
    （可选）：AdminStore 拒写（记录未落盘）时留痕。
    """
    from core.admin_store import AdminStore, SIGNAL

    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": "code_fix_wip_gate_defer_expired",
            "spec": None,
            "severity": "warning",
            "description": (
                f"code-fix 延迟批合回超预算（90 分钟或 {DEFER_RETRY_MAX} 次重试"
                "仍被主树未提交改动挡住），已降级入失败档案，待人工处置主树"
            ),
            "evidence": (
                f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
                f"tip_sha={tip_sha or 'unknown'}; "
                f"item_ids={', '.join(str(i) for i in item_ids)}; "
                f"重叠文件: {_fmt_overlap(overlap)}"
            ),
            "source": "code-fix-lane",
            "recommended_action": (
                "提交（git add/commit）或 stash（git stash push）主树这些改动；"
                "该批修复提交可按 branch/tip_sha 经 git reflog 追溯，人工排查后"
                "调用 core.code_fix.release_failed_batch 解除该批条目的跳过"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, "code_fix_wip_gate_defer_expired")


def _write_defer_orphan_alert(
    project_root, item_ids, overlap, branch="", tip_sha="",
    grace_minutes=30, orphan_since="", owner_note="", logger=None,
) -> None:
    """无主陈旧 WIP 宽限耗尽升级的一次性 major 告警（add-mergeback-wip-active-
    coordination 2.2/D4）。

    ``signal_type=mergeback_wip_orphan_stuck``（admin_monitor 已登记 major 分级
    与批语义适配指引）——``mergeback_wip_overlap`` 同级 major：升级是既有 WIP
    重叠人工告警族的「无主限期」变体，附 overlap 文件清单与识别证据（含 D1
    已知盲区注记）；处置指引按批语义适配——批无 spec 可重派，指引指向提交/
    stash 重叠文件。调用方以台账 ``owner_escalated_at`` 先查后记（同
    ``_has_expired_archive`` 指纹去重语义），一次性不重复升级。``logger``
    （可选）：AdminStore 拒写（记录未落盘）时留痕。
    """
    from core.admin_store import AdminStore, SIGNAL
    from core.worktree_manager.types import WipOccupantInfo

    evidence = (
        f"项目名={Path(project_root).name}; branch={branch or 'unknown'}; "
        f"tip_sha={tip_sha or 'unknown'}; "
        f"item_ids={', '.join(str(i) for i in item_ids)}; "
        f"重叠文件: {_fmt_overlap(overlap)}; "
        f"宽限={grace_minutes}分钟（自 {orphan_since or '?'} 起）; "
        f"识别证据: {owner_note or '无主（在飞实现车道分支改动集零命中）'}; "
        f"盲区注记: {WipOccupantInfo.BLIND_SPOT_NOTE}"
    )
    store = AdminStore(project_root, logger=None)
    rec = store.append(
        {
            "kind": SIGNAL,
            "signal_type": "mergeback_wip_orphan_stuck",
            "spec": None,
            "severity": "major",
            "description": (
                "code-fix 延迟批合回被主树未提交改动挡住，占用者识别为"
                f"无主陈旧 WIP（在飞实现车道分支改动集零命中），宽限 "
                f"{grace_minutes} 分钟内无人认领、主树 WIP 未清除——升级"
                "人工处置（批保持保留待自动合回语义，未丢弃、未触碰主树）"
            ),
            "evidence": evidence,
            "source": "code-fix-lane",
            "recommended_action": (
                "该批无 spec 可重派：人工核对重叠文件归属后，提交"
                "（git add/commit）或 stash（git stash push）主树这些改动，"
                "链边界自动合回核销该批；无需人工重派"
            ),
        }
    )
    if rec is None:
        _log_alert_rejected(logger, "mergeback_wip_orphan_stuck")



def _main_tree_dirty_files(project_root) -> list:
    """主树脏 tracked 文件清单（evo-add-codefix-batch-wip-precheck 1.1）。

    复用 ``G6StashGuardMixin._list_dirty_tracked_files`` 的提取口径（porcelain
    脏判定 / rename 两侧计入 / untracked 不计 / 命令失败返回空表按「无重叠」
    处理，不阻塞选批）。函数级 import 规避装载环（worktree_manager 包装载
    较重且与车道装配顺序无耦合，``_preset_run_id`` 同纪律）。
    """
    from core.worktree_manager.stash_guard import G6StashGuardMixin

    class _Probe(G6StashGuardMixin):
        """仅承载 project_root 的探针壳（完整 WorktreeManager 装配是死重）。"""

        def __init__(self, project_root):
            self.project_root = Path(project_root)

    return _Probe(project_root)._list_dirty_tracked_files()


# ── 编排器（5.3-5.8）──────────────────────────────────────────────────


class CodeFixOrchestrator:
    """自动修复编排器：单一入口 ``checkpoint()``（两路激活共用，D4）。

    守卫链（任一命中即不投递）：``enabled`` → ``already_running`` →
    ``no_open_items`` → 回归契约（fail-closed）→ 投递批 worker。

    单飞：``_in_flight`` + ``threading.Lock`` 保证两路并发至多一次投递；
    批 worker 收尾复位单飞并经 executor 再投递 checkpoint 推进下一批。
    """

    def __init__(self, agent_runner, project_root, config=None, logger=None, executor=None):
        self._agent_runner = agent_runner
        self.project_root = Path(project_root)
        self._config = config
        self._logger = logger
        self._executor = executor
        self._lock = threading.Lock()
        self._in_flight = False
        # 静默窗非法配置「WARNING 一次」的去重记忆（值变更后重新告警）。
        self._night_quiet_warned_raw = None

    # -- 基础 ------------------------------------------------------------

    def _log(self, level: str, msg: str) -> None:
        if self._logger is None:
            return
        try:
            getattr(self._logger, level)("code-fix", msg)
        except Exception:  # noqa: BLE001 — 日志失败不影响编排
            pass

    def _get_root_config(self) -> dict:
        """解析**根形态** config（dict / callable / None→runner 运行时配置）。

        `_get_config` 与选批前 WIP 预检（``worktree.build_artifact_paths`` /
        ``worktree.has_build_artifacts``，evo-add-codefix-batch-wip-precheck
        1.1）共用的单一解析点：产物豁免口径与开关读取 MUST 同源，否则 daemon
        装配形态（config=None）下豁免静默退化。
        """
        raw = self._config
        if callable(raw):
            raw = raw()
        if raw is None:
            # daemon 装配形态（fenixd.py 传 config=None）：读 **根** config。
            # `ConfigLoader.get_code_review_fix_config` 的契约是根形态（内部
            # `config.get("admin")`），而 `runner._get_config("admin.code_review_fix")`
            # 按嵌套键路径返回的是**子段**——直接把子段交给读取器会被判定「段缺失」
            # 而恒返回缺省 disabled，令设置页开关在唯一的生产路径上静默失效
            # （两路激活都经 checkpoint，整条自动修复车道不生效）。
            # 直接取 runner.config（与 runner._get_config 同源对象，热更新同样生效）。
            runner = self._agent_runner
            root = getattr(runner, "config", None)
            if isinstance(root, dict):
                return root
            # 退化：runner 无根 config 属性（测试替身）时，把子段回包成根形态
            try:
                seg = runner._get_config("admin.code_review_fix", {})
            except Exception:  # noqa: BLE001 — 测试 fake runner 可能无此方法
                seg = {}
            return {"admin": {"code_review_fix": seg}} if isinstance(seg, dict) else {}
        return raw or {}

    def _get_config(self) -> dict:
        """解析 admin.code_review_fix 生效值（根形态 → 段读取器）。"""
        return ConfigLoader.get_code_review_fix_config(self._get_root_config())

    def _severity_gate(self):
        """severity 分级门限生效值（evo-add-codefix-severity-batch-gate 2.1）。

        经 ``_get_config()`` 段读取器（新键已登记白名单）取
        min_immediate_severity / minor_batch_cadence；测试替身 config 段
        未走读取器的形态由 ``severity_gate_from_config_segment`` 同一归一
        兜底（与 code_review.severity_gate_config 磁盘解析路径共用）。

        总开关关闭（severity_batch_gate_enabled 缺省 False，2026-10-11）：
        返回 ``None``＝门限整体旁路（select_batch 的既有 None 兼容分支
        不过滤，当天发现的所有内容当天处理）。
        """
        return severity_gate_from_config_segment(self._get_config())

    def _targeted_retry_max(self) -> int:
        """定向重试轮上限（add-codefix-targeted-retry 2.2/2.4）。

        读 ``admin.code_review_fix.targeted_retry_max``，缺省 3；约束 1-5，
        越界/非法回退缺省（读取器已做同款守卫，此处对「测试替身 config 段
        未走读取器」的形态兜底）。
        """
        try:
            raw = self._get_config().get("targeted_retry_max", TARGETED_RETRY_MAX_DEFAULT)
            v = int(raw)
        except (TypeError, ValueError):
            return TARGETED_RETRY_MAX_DEFAULT
        if TARGETED_RETRY_MAX_MIN <= v <= TARGETED_RETRY_MAX_MAX:
            return v
        return TARGETED_RETRY_MAX_DEFAULT

    def _switch_cooldown_seconds(self) -> float:
        """连接类失败冷却时长（秒，evo-add-codefix-conn-error-cooldown 2.2）。

        缺省复用 PROVIDER_SWITCH_COOLDOWN_SECONDS（300s > 实测约 101 秒连接
        窗口）；配置键 ``admin.code_review_fix.switch_cooldown_seconds`` 覆盖。
        读取与防御转换仿 ``_orphan_grace_minutes``：解析失败/负值/NaN/inf 回退
        缺省（配置事故 MUST NOT 放大成「无限期停摆」极端）；``0`` 合法＝关闭
        冷却（spec R2「0 表示关闭」）。读取走 ``ConfigLoader.get`` 点号键——
        ``_get_config()`` 段读取器是白名单形态（未登记的新键会被剥掉），直接
        问段会恒取缺省。
        """
        try:
            raw = ConfigLoader.get(
                self._get_root_config(),
                "admin.code_review_fix.switch_cooldown_seconds",
                PROVIDER_SWITCH_COOLDOWN_SECONDS,
            )
            val = float(raw)
        except (TypeError, ValueError):
            return float(PROVIDER_SWITCH_COOLDOWN_SECONDS)
        # 负值/NaN（val != val）回退；inf 与负值同属「配置事故放大」极端。
        # 0 不回退（合法的关闭语义）。
        if val != val or val < 0 or val == float("inf"):
            return float(PROVIDER_SWITCH_COOLDOWN_SECONDS)
        return val

    def _night_quiet_window(self):
        """解析每日静默窗配置（evo-codefix-night-quiet-window 1.1；多窗化
        evo-add-review-night-defer-snapshot-writeoff 1.2）。

        读 ``admin.code_review_fix.night_quiet_window`` 点号键——沿
        ``_switch_cooldown_seconds`` 既有模式走根形态 ``ConfigLoader.get``
        （段读取器是白名单形态，未登记的新键会被剥掉，直接问段恒取缺省），
        缺省 ``NIGHT_QUIET_WINDOW_DEFAULT``。空串/off（大小写不敏感）＝完全
        禁用；格式非法（缺分隔符/非 HH:MM/小时分钟越界/end<=start 逆序/
        多窗列表中任一段坏——本场景不要求跨午夜）按无窗处理并 WARNING 一次
        （防配置错误静默吞掉；同实例对同一非法值只告警一次，值变更后重新
        告警）。

        返回窗元组列表 ``[(start_min, end_min, text), …]``；禁用/非法返回
        None。
        """
        try:
            raw = ConfigLoader.get(
                self._get_root_config(),
                "admin.code_review_fix.night_quiet_window",
                NIGHT_QUIET_WINDOW_DEFAULT,
            )
        except (TypeError, ValueError):
            return None
        parsed = _parse_night_quiet_windows(raw)
        if parsed is None and not _night_quiet_window_disabled(raw):
            if self._night_quiet_warned_raw != str(raw):
                self._night_quiet_warned_raw = str(raw)
                self._log(
                    "warning",
                    "code-fix 夜间静默窗配置非法（"
                    f"{str(raw)!r}，须形如 HH:MM-HH:MM（多窗以逗号分隔）"
                    "且各段 end>start，off/空串关闭），按无窗处理",
                )
        return parsed

    def _chain_recent_duration_mean(self, chain_run_ids):
        """同链近批实测时长均值（秒）；无有效样本返回 None（fail-open 依据）。

        样本源：链级 run 清单（chain_run_ids）最近
        ``NIGHT_QUIET_DURATION_SAMPLE_LIMIT`` 批的 run 归档末条 run_metrics
        行 ``duration_s``（evo-add-night-window-inflight-guard 1.2 补记字段）。
        历史行缺该字段/归档两处皆缺/负值/非有限数值一律剔除——「近批无有效
        样本」（新链冷启动/历史行未记时长）即回退既有「仅判派发时刻落窗」
        判定（design D1，MUST NOT 因缺样阻塞投递）。取均值而非最快样本：
        对慢批次保守自适应。
        """
        if not isinstance(chain_run_ids, list):
            return None
        samples: list = []
        for rid in list(chain_run_ids)[-NIGHT_QUIET_DURATION_SAMPLE_LIMIT:]:
            rec = _read_run_metrics(self.project_root, str(rid))
            try:
                dur = float(rec.get("duration_s"))
            except (TypeError, ValueError):
                continue
            if dur < 0 or not math.isfinite(dur):
                continue
            samples.append(dur)
        if not samples:
            return None
        return sum(samples) / len(samples)

    def _night_quiet_state(self, chain_run_ids=None):
        """静默窗状态快照：真实窗内态 + 预计跨窗态；两态皆不命中返回 None。

        判定显式走本地时区 ``time.localtime``（与断窗时刻对齐，spec R6，
        MUST NOT 用 UTC）。两级判定：

        - 真实窗内态（既有，evo-codefix-night-quiet-window）：当前本地时刻
          落 ``[start, end)``（左闭右开，边界见测试四点）即命中；
        - 预计跨窗态（evo-add-night-window-inflight-guard 1.1）：窗前派出
          （cur < start）且「当前时刻 + 同链近批实测时长均值」越过窗起点
          （预计在飞区间与窗区间相交）即命中——覆盖「窗前派出、窗中在飞」
          形态；近批无有效时长样本（``_chain_recent_duration_mean`` 返回
          None）回退仅判派发时刻，不阻塞投递；今日窗已过（cur >= end）不
          预测明日窗（窗解析单日语义，design 同款边界）。

        命中返回 ``{text, date, end_ts, predicted, est_duration_s}``：text
        为命中窗配置区间原文（告警 evidence 用），date 为窗次标识（本地日期，
        含日期故跨窗次自动重新武装），end_ts 为今日本地窗末 epoch 秒＝下一
        可投递时刻；predicted 标预计跨窗态——与真实窗内态共用同一窗次标识
        与武装告警语义（同窗次幂等，「预测态→真实窗内态」迁移不重复武装）；
        est_duration_s 仅预测态携带（秒，进度文案展示用）。

        多窗化（evo-add-review-night-defer-snapshot-writeoff 1.2）：命中判定
        为「任一窗 start<=cur<end」；多窗同中取最晚窗末（拦截至最晚 end，
        text 随该命中窗）；真实窗内态不命中时对今日尚未开始的窗做预计跨窗
        判定（已过的窗不预测），预计区间与任一未来窗相交即命中该窗。
        """
        windows = self._night_quiet_window()
        if not windows:
            return None
        lt = time.localtime()
        cur = lt.tm_hour * 60 + lt.tm_min
        predicted = False
        est_duration_s = None
        hits = [w for w in windows if w[0] <= cur < w[1]]
        if not hits:
            # 真实窗内态不命中：今日已过的窗剔除，仅对尚未开始的窗预测
            # （窗解析单日语义，design 同款边界——不预测明日窗）。
            future = [w for w in windows if cur < w[0]]
            if not future:
                return None
            est = self._chain_recent_duration_mean(chain_run_ids)
            if est is None:
                return None
            cur_s = lt.tm_hour * 3600 + lt.tm_min * 60 + lt.tm_sec
            # 区间相交（左闭右开对左开）：预计结束恰好压线窗起点（<=）视作
            # 不相交——批次在窗起点整点前收尾，不与窗共存。
            hits = [w for w in future if cur_s + est > w[0] * 60]
            if not hits:
                return None
            predicted = True
            est_duration_s = est
        # 多窗命中取最晚窗末：下一可投递时刻以最晚 end 为准（多窗同中或
        # 预计区间跨多窗时一次拦到底），窗次文本随该命中窗。
        start_min, end_min, text = max(hits, key=lambda w: w[1])
        return {
            "text": text,
            "date": time.strftime("%Y-%m-%d", lt),
            "end_ts": _local_window_end_epoch(end_min),
            "predicted": predicted,
            "est_duration_s": est_duration_s,
        }

    def _arm_night_quiet_window(self, quiet_window, prev_armed_date,
                                prev_armed_text=None) -> None:
        """窗次武装（evo-codefix-night-quiet-window 1.2）：同窗次幂等。

        窗次标识含日期（``night_quiet_armed_date``，形如 "2026-10-06"）连同
        窗区间快照（``night_quiet_armed_text``）持久化于 fix-progress.json
        （合并写，进程重启后仍幂等）；同窗次武装至多写一次告警，跨窗次自动
        重新武装，残留标识不拦截投递（惰性清理见 checkpoint 守卫块）。告警/
        写盘异常均不劫持拦截返回（对齐冷却守卫同款纪律）。

        多窗化（evo-add-review-night-defer-snapshot-writeoff 1.2）起窗次
        幂等键含命中窗文本：同日多窗各自武装一次（03:00-03:15 与
        04:15-04:45 是两个窗次），配置变更当日新旧窗文本亦视为不同窗次
        （告警按窗次幂等、不拦截投递，design 已知可接受偏差）。
        """
        if (prev_armed_date == quiet_window["date"]
                and prev_armed_text == quiet_window["text"]):
            return
        try:
            _write_night_quiet_window_alert(
                self.project_root,
                window_text=quiet_window["text"],
                window_date=quiet_window["date"],
                until_ts=quiet_window["end_ts"],
                logger=self._logger,
            )
        except Exception as e:  # noqa: BLE001 — 告警通道失败只留痕
            self._log("warning", f"code-fix 静默窗武装告警写盘异常: {e}")
        try:
            write_progress(
                self.project_root,
                night_quiet_armed_date=quiet_window["date"],
                night_quiet_armed_text=quiet_window["text"],
            )
        except Exception as e:  # noqa: BLE001 — 武装态写盘失败下轮重试
            self._log("warning", f"code-fix 静默窗武装态写盘异常: {e}")

    def _arm_switch_cooldown(self, result) -> None:
        """连接类失败收尾置同链冷却态（2.1/2.3）：持久化冷却字段 + 触发告警。

        命中判定读信封 ``conn_error`` 布尔（runner 层判别单源透传，调用方
        ``getattr`` 守护测试替身信封缺字段形态）；配置关闭（0）不置冷却。
        冷却起点一并落盘（解除告警「实际推迟时长」度量基准，design D5）；
        写盘/告警异常均不劫持失败收尾（对齐 write_regression_signal 调用点
        纪律，code-review item 2ab1bb5633f0）。
        """
        cooldown = self._switch_cooldown_seconds()
        if cooldown <= 0:
            return
        now_ts = time.time()
        until_ts = now_ts + cooldown
        try:
            write_progress(
                self.project_root,
                switch_cooldown_until=until_ts,
                switch_cooldown_from=now_ts,
                current=(
                    f"上游连接类失败（run {getattr(result, 'run_id', '') or 'unknown'}），"
                    f"同链下一批推迟至 {_epoch_iso(until_ts)}"
                ),
            )
        except Exception as e:  # noqa: BLE001 — 冷却态写盘失败不劫持失败收尾
            self._log("warning", f"code-fix 冷却态写盘异常: {e}")
        try:
            _write_switch_cooldown_alert(
                self.project_root,
                run_id=getattr(result, "run_id", "") or "",
                cause_text=(
                    getattr(result, "result_text", "") or ""
                    or getattr(result, "error", "") or ""
                ),
                until_ts=until_ts,
                cooldown_seconds=cooldown,
                logger=self._logger,
            )
        except Exception as e:  # noqa: BLE001 — 告警通道失败只留痕
            self._log("warning", f"code-fix 冷却触发告警写盘异常: {e}")

    def _targeted_regression_enabled(self) -> bool:
        """批收尾定向回归开关（add-codefix-affinity-batching 4.1）。

        读 ``admin.code_review_fix.targeted_regression``，严格 bool、缺省
        true；非法值由读取器回退缺省并记 warning（MUST NOT 抛异常）——此处
        对「测试替身 config 段未走读取器」的形态再兜底同款回退。
        """
        raw = self._get_config().get("targeted_regression", True)
        if isinstance(raw, bool):
            return raw
        return True

    def _resolve_batch_regression_spec(
        self, reg_spec, wt, run_id: str, batch_no: int, is_last_batch: bool
    ) -> tuple:
        """批收尾回归两段式分流（add-codefix-affinity-batching 3.4）。

        返回 ``(eff_spec, targeted, targets)``：
        - 末批（``is_last_batch``）恒回退全量 ``(消毒副本, False, [])``——
          兜底，无论开关取值与 cmd 是否声明占位符；
        - 非末批且 ``targeted_regression=true`` 且 cmd 含 ``{test_targets}``
          且触碰面映射非空 → 定向（替换后的 RegressionSpec 副本）；
        - 否则（配置关 / 映射空集 / cmd 无占位符——定向判别仍用原 spec，
          ctx 入口不盲替）回退全量并记日志留痕（fail-open：映射是优化
          不是门槛，MUST NOT 回退到「跳过回归」）。

        两个回退出口返回消毒副本（add-codefix-test-targets-fallback-
        sanitization）：cmd 含占位符时替换为缺省 ``tests/`` 后再执行，无
        占位符 spec 原样返回——回退路径不再把字面占位符透传给执行层。

        第三个返回值（targets）仅供定向轮的 FENIX_TEST_TARGETS 同值双轨导出
        与救回重跑复用，两个回退出口恒返回空列表：回退全量语义下 MUST NOT
        导出该环境变量——env 形态 cmd（收集通道写作
        ``${FENIX_TEST_TARGETS:-缺省}``，占位符以注释哨兵形态 inert 存在）
        的实际收集面由它驱动，导出首轮映射的陈旧 targets 会把声明的「全量」
        静默收窄成子集、不可映射的失败用例未复跑即合回（code-review item
        5f88b3b78f7c）；不导出时 env 形态 cmd 按自身缺省目标收集，与占位符
        形态的消毒语义对齐。
        """
        if is_last_batch or not self._targeted_regression_enabled():
            return _sanitize_test_targets(reg_spec), False, []
        targets = _map_fix_files_to_tests(
            _fixed_files_from_rows(read_fix_out(wt, run_id)), wt
        )
        if targets and _cmd_has_test_targets(reg_spec):
            self._log(
                "info",
                f"code-fix 第 {batch_no} 批定向回归"
                f"（触碰面 {len(targets)} 个测试路径）",
            )
            return _apply_test_targets(reg_spec, targets), True, targets
        why = (
            "触碰面映射空集" if not targets
            else "regression.cmd 未声明 {test_targets} 占位符"
        )
        self._log("info", f"code-fix 第 {batch_no} 批回退全量回归（{why}）")
        # [fenix-ignore:f87f64aeca2e] 回退出口已经 _sanitize_test_targets 消毒：
        # 占位符替换为缺省 tests/ 再执行（add-codefix-test-targets-fallback-
        # sanitization），字面占位符不再透传执行层，问题不成立
        # targets 恒返回空列表：回退全量不导出 FENIX_TEST_TARGETS（env 形态
        # cmd 不被首轮映射的陈旧目标集收窄，item 5f88b3b78f7c）。
        return _sanitize_test_targets(reg_spec), False, []

    def _code_fix_running(self) -> bool:
        """在途判据：编排器单飞标记或 runner 侧存在 code-fix- 前缀 run。"""
        if self._in_flight:
            return True
        running = getattr(self._agent_runner, "_running_agents", None) or {}
        return any(str(rid).startswith("code-fix-") for rid in running)

    def _wip_overlap_at_select(self, batch) -> list:
        """选批前 WIP 重叠预检（evo-add-codefix-batch-wip-precheck 1.1）。

        主树脏 tracked 文件 × 候选批条目 file（台账条目为仓库相对路径，
        items.jsonl 实证）求交；交集经产物判别过滤——ArtifactPathMatcher 以
        与 WorktreeManager 同配置源构造（normalize_artifact_patterns(
        build_artifact_paths) + has_build_artifacts 三态，先例
        core/worktree_manager/lifecycle.py:127）。dist 类产物路径不计入命中：
        merge-time 闸门（_wip_overlap_gate D3b）豁免纯产物重叠，预检若不同
        口径即「预检拦、merge-time 放行」倒退；MUST NOT 硬编码 dist 前缀、
        MUST NOT 无参默认构造——空 patterns 判定恒假是「未裁决」保守侧（此
        时 merge-time 闸门同样按语义重叠处置），与 merge-time 同语义不算豁免。

        Returns: 语义（非产物）重叠文件排序列表；无重叠为空列表。
        """
        candidates = {rec.get("file") for rec in batch if rec.get("file")}
        if not candidates:
            return []
        dirty = _main_tree_dirty_files(self.project_root)
        if not dirty:
            return []
        overlap = sorted(candidates & set(dirty))
        if not overlap:
            return []
        from core.worktree_manager.artifact_paths import (
            ArtifactPathMatcher,
            normalize_artifact_patterns,
        )

        root_cfg = self._get_root_config()
        return ArtifactPathMatcher(
            normalize_artifact_patterns(
                ConfigLoader.get(root_cfg, "worktree.build_artifact_paths", None)
            ),
            has_build_artifacts=ConfigLoader.get(
                root_cfg, "worktree.has_build_artifacts", None
            ),
        ).non_artifacts_in(overlap)

    # -- 检查点（单一入口）--------------------------------------------------

    def checkpoint(self, override_enabled: bool = False) -> dict:
        """激活检查点：守卫链判定，通过则投递一批（返回 ``{triggered, reason}``）。

        两路激活（审查收尾 / full scan）与批 worker 的自驱动再投递共用本入口；
        幂等（开关关闭 / 已在跑 / 无 open 条目 / 回归契约缺失均不投递）。

        ``override_enabled``（add-code-fix-manual-trigger）：手动触发即临时授权
        ——为 True 时跳过 ``enabled`` 守卫（唯一调用方是 daemon 手动信号消费
        函数 ``fenixd._check_code_fix_requests``），其余守卫（单飞 already_running
        / 无 open 条目 / 失败保留 / 回归契约 fail-closed）原样生效。缺省 False。

        手动授权语义（2026-09-22 事故修复）：授权的是**整条链**而非一批。手动
        投递时把 ``manual_authorized=true`` 写进进度快照（随链身份持久化），
        批收尾后 ``_resubmit`` 的 checkpoint（无 override）凭「链 live 且旗标
        为真」越过 enabled 总开关，自驱动跑完剩余 open 条目；终态（idle /
        blocked / failed）清除旗标——收尾链的授权不外溢到新链。仅当 live 链
        撞上 disabled（开关被中途关闭）时落终态进度（phase=blocked /
        reason=disabled），MUST NOT 静默冻结在 running=true。

        进度链身份（D8）：读到 ``running=true`` 且 activation_id 未变 → 视为
        同一激活链，MUST NOT 重算 total（否则每批收尾再投递会把 total 重置为
        已缩小的 open 数，前端出现「已处理 0/40」倒退）。

        批失败自愈（add-code-fix-batch-selfheal）：链身份判定前移到选批之前
        ——新链启动（非同一 activation_id）先释放预算内失败档案
        （``release_retryable_failed_batches``，等效人工 release 的自动化）
        并重置 ``chain_skipped``，再选批；否则上一链以全跳过收敛后，下一
        checkpoint 会因 open 条目全被排除而恒走「选批为空」早退，永远到不了
        新链分支，车道锁死（自愈失效）。选批排除口径 = 失败档案 ∪
        ``chain_skipped``；「选批为空」是 consumed 链的正常收敛出口，文案按
        排除来源区分（D5），不误报为故障。
        """
        with self._lock:
            cfg = self._get_config()
            # 链上授权旗标：只有 live 链（running=true）的旗标被消费，
            # 收尾链残留的旗标不外溢到新链。
            prev_chain = read_progress(self.project_root)
            chain_authorized = bool(prev_chain.get("running")) and bool(
                prev_chain.get("manual_authorized")
            )
            if not cfg.get("enabled") and not override_enabled and not chain_authorized:
                # 开关关闭且无授权 = 不投递；但 live 链撞上 disabled（开关被
                # 中途关闭）必须落终态进度——静默早退会让前端永久停在陈旧的
                # 「进行中」快照上（2026-09-22「合回主树中」冻结事故缺陷面）。
                if prev_chain.get("running"):
                    if self._code_fix_running():
                        # 批在飞（code-review item 1421fde483a3）：不落终态——
                        # 此处写 blocked 会把在飞批刚置的 running=true 快照连同
                        # 批上下文（worktree/run_id）一并抹成「已终止」，而批
                        # worker 不感知开关，照常回归、合回主树再写 merging
                        # 进度，终止语义与真实在飞状态互相矛盾。改为仅追加
                        # reason=disabled 的提示性 current（合并写保留 running
                        # 与批上下文），终态改写留给批收尾后的下一次 checkpoint
                        # （自驱动 _resubmit 或下一轮 full scan）。提示文案按
                        # 手动授权分流：手动链收尾后的 checkpoint（无 override）
                        # 凭 chain_authorized 越过 enabled 守卫继续派批，写
                        # 「终止链」会与实际继续跑批矛盾。
                        if chain_authorized:
                            current = (
                                "自动修复总开关已关闭，本链由手动授权，"
                                "批收尾后将继续跑完剩余条目"
                            )
                        else:
                            current = (
                                "自动修复总开关已关闭，本批收尾后终止链（不再投递后续批次）"
                            )
                        write_progress(
                            self.project_root,
                            reason="disabled",
                            current=current,
                        )
                    else:
                        write_progress(
                            self.project_root,
                            running=False,
                            phase="blocked",
                            reason="disabled",
                            current="自动修复总开关已关闭，链终止（可重新触发）",
                            worktree=None,
                            run_id=None,
                            batch_total=None,
                            manual_authorized=False,
                            chain_skipped=[],
                            **self._chain_terminal_fields("disabled"),
                        )
                return {"triggered": False, "reason": "disabled"}
            if self._code_fix_running():
                return {"triggered": False, "reason": "already_running"}

            root = self.project_root
            # 延迟批链边界重试（fix-codefix-wipgate-defer D4/2.2）：单一调用点
            # 挂在既有节拍上，同时覆盖两个重试时机——「count_open_items==0 收敛
            # 早退之前」与「选批之前」（两判定都在其后，重试结果即时反映进 open
            # 计数与可选池）；台账空时零开销早退。位置在 already_running 守卫
            # 之后：批在飞时上方恒 already_running 早退，重试不与在飞批的建树/
            # 合回交叠；本调用仍在既有 ``self._lock`` 段内（不重入 checkpoint，
            # 无死锁面）。返回（本轮核销条数, 结果文案）：核销数并入下方链身份
            # 的 done（防 dispatch 写进度用陈旧 done 覆写），文案供两个收敛
            # 早退出口透传（D7）。
            deferred_done, deferred_msg = self._process_deferred_merges()
            total_open = count_open_items(root)
            if total_open == 0:
                # 失败登记闭环核销（code-review item 3798ed26db5c）：空转车道
                # 此后不再产生新链启动簿记块，被跳过条目被人工在台账侧全部置
                # 终态后，本收敛 checkpoint 是唯一收敛写点——在此即时核销，
                # 失败登记/todo 登记块/告警不再滞留到未来某次新链启动（项目
                # 不再产生新发现时即无限期滞留）。fail-open，不阻断收敛出口。
                self._consume_failed_registrations(root)
                # 链收尾（无 open 条目）：进度落 running=false（若曾有链）；
                # 链上状态（授权旗标/链内跳过集）随链终止一并清除。本轮刚有
                # 延迟批核销时 current 携带其结果文案（spec：进度显示「延迟批
                # 合回成功（核销 N 条）」），无延迟批时保持空串原语义。
                if _progress_path(root).exists():
                    write_progress(
                        root,
                        running=False,
                        phase="idle",
                        current=deferred_msg,
                        reason="",
                        worktree=None,
                        run_id=None,
                        batch_total=None,
                        manual_authorized=False,
                        chain_skipped=[],
                        **self._chain_terminal_fields("chain_converged"),
                    )
                return {"triggered": False, "reason": "no_open_items"}

            # 连接类失败冷却守卫（evo-add-codefix-conn-error-cooldown 2.2）：
            # 本入口是全部激活路径（full scan 末尾兜底 event_bus / 新条目激活
            # / 自驱动 _resubmit / 事件驱动重试回调）的唯一共用投递入口，闸在
            # 这里才能同时拦住「full scan 在窗口内再触发的批次」（design D3；
            # _resubmit 只覆盖自驱动一路，不取）。冷却态持久化于
            # fix-progress.json（合并写），进程重启后残余窗口内仍拦（D4）。
            # 位置在 no_open_items 早退之后：台账清空空转的 checkpoint 不写
            # 解除告警（D5），且冷却不改失败批条目记账语义（consumed/
            # chain_skipped 维持现状，仅推迟下一批投递，spec R2）。
            try:
                cooldown_until = float(
                    prev_chain.get("switch_cooldown_until") or 0
                )
            except (TypeError, ValueError):
                cooldown_until = 0.0
            # 配置关闭（switch_cooldown_seconds=0，spec R2「0=关闭」）时守卫
            # 不生效：_arm 层 0 不武装新冷却，但已落盘的残留未来冷却态若仍按
            # 字面拦截，关闭配置解除不了窗口（验证轮 BUG-01）。命中残留态时
            # 一并清除，避免日后重新启用配置时旧窗口复活；关闭态不写解除
            # 告警——冷却从未实际推迟过投递，evidence 会误报「实际推迟时长」。
            if cooldown_until > 0 and self._switch_cooldown_seconds() <= 0:
                try:
                    write_progress(
                        root,
                        switch_cooldown_until=None,
                        switch_cooldown_from=None,
                        current="连接类失败冷却已由配置关闭，清除残留冷却态",
                        reason="",
                    )
                except Exception as e:  # noqa: BLE001 — 清态失败不阻断投递
                    self._log("warning", f"code-fix 冷却残留态清除写盘异常: {e}")
                cooldown_until = 0.0
            now_ts = time.time()
            cooldown_active = cooldown_until > 0 and now_ts < cooldown_until

            # 夜间静默窗守卫（evo-codefix-night-quiet-window 1.1/1.2）：与冷却
            # 守卫同闸在本唯一共用投递入口——四路激活路径（批收尾自驱动
            # _resubmit / full-scan 兜底 event_bus / 持有者终态回调 / 审查收尾
            # 新条目激活 maintenance_runs）全部汇入 checkpoint()，单点判定即
            # 全覆盖，分散判定反而引入不一致（该不变量由
            # tests/test_code_fix_night_quiet_window.py 源码契约测试固定）；
            # override_enabled=True 的手动触发同样生效（手动授权仅越过
            # enabled 总开关，沿冷却现状）。判定显式走本地时区 time.localtime
            # （与断窗时刻对齐，MUST NOT 用 UTC）。evo-add-night-window-
            # inflight-guard 1.1 起判定升级为「真实窗内态 + 预计跨窗态」两
            # 级：窗前派出但预计结束时刻落窗同样拦截——两态共用 reason、窗
            # 次标识与武装告警语义（同窗次幂等，预测态→真实窗内态迁移不重
            # 复武装）。窗内返回 triggered=False、
            # reason=night_quiet_window；与冷却同时命中取更晚可投递时刻
            # （reason 取更晚者对应守卫），二者独立武装/解除、互不复位。
            # evo-add-night-window-inflight-guard 1.1：预计跨窗升级——判定
            # 入参带链级 run 清单（窗前派出时以近批实测时长估预计结束时刻，
            # 与窗区间相交即顺延到窗末；prev_chain 可能被外部写坏成非列表，
            # 估计器按非列表回退无样本，fail-open 不阻塞投递）。多窗配置
            # （evo-add-review-night-defer-snapshot-writeoff 1.2）命中任一窗
            # 即拦截，多窗同中取最晚窗末为可投递时刻，窗次幂等含窗文本。
            quiet_window = self._night_quiet_state(
                prev_chain.get("chain_run_ids"))
            quiet_armed_date = prev_chain.get("night_quiet_armed_date")
            if not isinstance(quiet_armed_date, str):
                quiet_armed_date = ""
            quiet_armed_text = prev_chain.get("night_quiet_armed_text")
            if not isinstance(quiet_armed_text, str):
                quiet_armed_text = ""
            if quiet_window is None and quiet_armed_date:
                # 窗末/配置关闭后的残留窗次标识：惰性清理（沿上方冷却残留态
                # 清理先例）——补写解除告警（一次）并清标识；标识本身不拦截
                # 投递，清理失败只留痕（下一个 checkpoint 重试清理）。
                try:
                    _write_night_quiet_window_release_alert(
                        root,
                        window_text=str(
                            prev_chain.get("night_quiet_armed_text") or ""
                        ),
                        window_date=quiet_armed_date,
                        logger=self._logger,
                    )
                except Exception as e:  # noqa: BLE001 — 告警通道失败只留痕
                    self._log("warning", f"code-fix 静默窗解除告警写盘异常: {e}")
                try:
                    write_progress(
                        root,
                        night_quiet_armed_date=None,
                        night_quiet_armed_text=None,
                        current="夜间静默窗已结束，恢复同链下一批投递",
                        reason="",
                    )
                except Exception as e:  # noqa: BLE001 — 清态失败不阻断投递
                    self._log("warning", f"code-fix 静默窗残留态清除写盘异常: {e}")
            if cooldown_until > 0 and not cooldown_active:
                # 到期：本 checkpoint 即「冷却到期后首个通过守卫的 checkpoint」
                # ——补写解除告警（evidence 携带实际推迟时长）并清冷却态，
                # 保证只发一次；静默窗随后接管拦截时本解除照写（二者独立
                # 武装/解除，互不复位）。告警/清态异常不阻断后续投递（同款纪律）。
                try:
                    cooldown_from = float(
                        prev_chain.get("switch_cooldown_from")
                        or (cooldown_until - self._switch_cooldown_seconds())
                    )
                except (TypeError, ValueError):
                    cooldown_from = cooldown_until - self._switch_cooldown_seconds()
                try:
                    _write_switch_cooldown_release_alert(
                        root,
                        until_ts=cooldown_until,
                        deferred_seconds=max(0.0, now_ts - cooldown_from),
                        logger=self._logger,
                    )
                except Exception as e:  # noqa: BLE001 — 告警通道失败只留痕
                    self._log("warning", f"code-fix 冷却解除告警写盘异常: {e}")
                try:
                    write_progress(
                        root,
                        switch_cooldown_until=None,
                        switch_cooldown_from=None,
                        current="连接类失败冷却到期，恢复同链下一批投递",
                        reason="",
                    )
                except Exception as e:  # noqa: BLE001 — 清态失败不阻断投递
                    self._log("warning", f"code-fix 冷却态清除写盘异常: {e}")

            if cooldown_active or quiet_window is not None:
                # 二守卫同时命中：可投递时刻取更晚者，reason 取更晚者对应守卫
                # （时刻相等归冷却；任意一方单命中即取该方）。
                deliver_ts = max(
                    (cooldown_until if cooldown_active else 0.0),
                    (quiet_window["end_ts"] if quiet_window is not None else 0.0),
                )
                if cooldown_active and deliver_ts == cooldown_until:
                    reason = "switch_cooldown"
                else:
                    reason = "night_quiet_window"
                if quiet_window is not None:
                    # 窗次武装（同窗次幂等）：首次进入本窗次才写武装告警与
                    # 窗次标识；跨窗次自动重新武装，残留标识不拦截投递。
                    # 多窗化起幂等键含命中窗文本（同日多窗各自武装一次）。
                    self._arm_night_quiet_window(
                        quiet_window, quiet_armed_date, quiet_armed_text)
                if reason == "switch_cooldown":
                    current = (
                        "上游连接类失败冷却中，同链下一批暂缓派发至 "
                        f"{_epoch_iso(cooldown_until)}"
                    )
                    guard_label = "冷却"
                else:
                    if quiet_window.get("predicted"):
                        # 预计跨窗态（evo-add-night-window-inflight-guard
                        # 1.1）：批次预计结束时刻落窗，窗前顺延——文案区分
                        # 预测/真实以便审计对账，拦截语义与窗内态一致。
                        current = (
                            "预计本批跨夜间静默窗（近批均时长 "
                            f"{quiet_window['est_duration_s']:.0f} 秒），"
                            f"暂停启动新批至 {_epoch_iso(deliver_ts)}"
                            f"（窗区间 {quiet_window['text']}）"
                        )
                        guard_label = "静默窗(预计)"
                    else:
                        current = (
                            "每日夜间静默窗内，暂停启动新批至 "
                            f"{_epoch_iso(deliver_ts)}"
                            f"（窗区间 {quiet_window['text']}）"
                        )
                        guard_label = "静默窗"
                # 拦截：进度只刷提示文案（running/phase 链上状态不动——链仍
                # live，自驱动/兜底节拍到可投递时刻后自然续跑）。
                write_progress(root, reason=reason, current=current)
                self._log(
                    "info",
                    f"code-fix {guard_label}守卫拦截投递"
                    f"（至 {_epoch_iso(deliver_ts)}）",
                )
                return {"triggered": False, "reason": reason}

            # 进度链身份（D8）：同链沿用 activation_id，新链重算。判定
            # 前移到选批之前（selfheal）：新链启动先释放预算内失败档案并重置
            # chain_skipped——放在选批之后会让「上一链全跳过收敛」后的下一
            # checkpoint 恒走选批为空早退，新链分支不可达（车道锁死）。
            # （复用守卫段已读的 prev_chain——读取后中间可能经
            # _process_deferred_merges 写入 done/current/phase/reason，仅 done
            # 已按 deferred_done 补偿，其余被依赖字段重试路径不触碰，新增对
            # prev 其他字段的依赖须复核）
            prev = prev_chain
            if prev.get("running") and prev.get("activation_id"):
                activation_id = prev["activation_id"]
                # 本轮链边界重试刚核销的延迟批条目并入 done（prev 读点在重试
                # 之前，陈旧 done 若直传 dispatch 写点会覆掉重试的累加）。
                # done 数值形态守卫（code-review item c95bc89c37d6，与下方
                # chain_skipped/chain_run_ids 及上方 switch_cooldown_until 同
                # 读取点同款防御）：progress 被外部写坏成非数值标量时裸加法
                # 在本读点抛 TypeError，checkpoint 每轮同位崩溃且无自愈路径
                # ——读侧按「损坏不炸主流程」纪律 try int 归一，非法值重置
                # 0（truthy 垃圾值 warning 留痕），下次链级写点即以合法数值
                # 覆盖自愈。
                try:
                    prev_done = int(prev.get("done") or 0)
                except (TypeError, ValueError):
                    if prev.get("done"):
                        self._log(
                            "warning",
                            "code-fix 进度 done 字段形态异常（非数值："
                            f"{type(prev.get('done')).__name__}），按 0 容错",
                        )
                    prev_done = 0
                done = prev_done + deferred_done
                # 分母活口径（2026-09-25 用户事故）：total 曾沿用链起点定格
                # 快照——链在飞期间新审查轮追加的 open 条目会被本链继续处置
                # （select_batch 全 open 池选取），但分母不涨，done 追平定格
                # total 后前端恒 100%。改为 done+open：核销转移（done+1 且
                # open-1）不变分母，新 arrivals 推高、外部核销缩小；
                # deferred_done 已并入 done 且对应条目已离开 open 池
                # （total_open 统计在合并之后），口径自洽不双计。
                total = done + total_open
                # batch_no 同款数值形态守卫（code-review item c95bc89c37d6）：
                # 非数值标量重置 0（truthy 垃圾值 warning 留痕），防链调度
                # 在本读点反复崩溃。
                try:
                    batch_no = int(prev.get("batch_no") or 0)
                except (TypeError, ValueError):
                    if prev.get("batch_no"):
                        self._log(
                            "warning",
                            "code-fix 进度 batch_no 字段形态异常（非数值："
                            f"{type(prev.get('batch_no')).__name__}），按 0 容错",
                        )
                    batch_no = 0
                # 链级字段形态守卫（code-review item 3f883a9ac93c，与上方
                # switch_cooldown_until 同位置同款防御）：read_progress 对
                # 「JSON 合法、字段被外部写坏成非列表标量」原样透传，直接
                # list() 会在 int/bool 等不可迭代值上抛 TypeError 中断本轮
                # 投递——读侧按「损坏不炸主流程」纪律先判 isinstance(list)
                # 再拷贝，非列表回退空列表（truthy 垃圾值 warning 留痕；
                # None/空值静默回退，等价旧 or [] 语义），下次链级写点即以
                # 空列表覆盖自愈。
                chain_skipped = prev.get("chain_skipped")
                if isinstance(chain_skipped, list):
                    chain_skipped = list(chain_skipped)
                else:
                    if chain_skipped:
                        self._log(
                            "warning",
                            "code-fix 进度 chain_skipped 字段形态异常（非列表："
                            f"{type(chain_skipped).__name__}），按空列表容错",
                        )
                    chain_skipped = []
                # 链级 run 清单随链身份沿用（2.2）：合并写语义下未传字段保留
                # 现值，这里显式读出仅供 ctx 下发批 worker 追加本批 run_id。
                chain_run_ids = prev.get("chain_run_ids")
                if isinstance(chain_run_ids, list):
                    chain_run_ids = list(chain_run_ids)
                else:
                    if chain_run_ids:
                        self._log(
                            "warning",
                            "code-fix 进度 chain_run_ids 字段形态异常（非列表："
                            f"{type(chain_run_ids).__name__}），按空列表容错",
                        )
                    chain_run_ids = []
                new_chain = False
            else:
                activation_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
                total = total_open
                done = 0
                batch_no = 0
                # 新链启动：预算内失败档案自动释放（下轮自动重试，等效原人工
                # release_failed_batch）；链内跳过集随链身份更替重置为空。
                chain_skipped = []
                # 上一链未走终局写点即被更替（daemon 重启/崩溃中途）：按落盘
                # 累积值补发一行 rollup 日志（不落盘——本链的终局快照已在既往
                # 终态写点落盘或随重启丢失，紧随的新链写点会归零累积值）。
                self._emit_chain_rollup("chain_superseded")
                chain_run_ids = []
                new_chain = True
                released = release_retryable_failed_batches(root)
                if released:
                    self._log(
                        "info",
                        f"code-fix 新链启动：释放 {released} 条预算内失败档案"
                        "（下轮自动重试）",
                    )
                # 失败登记闭环核销（add-codefix-failure-registration-closeout
                # 1.1）：新链启动簿记块周期兜底——批收尾/合回核销点错过的
                # 全终态登记在此收敛。
                self._consume_failed_registrations(root)
                # 换链/重启再认领（fix-codefix-wipgate-defer D5/4.1）：台账核对
                # 磁盘——worktree 目录仍在且 tip_sha 可解析的条目原样保留
                # （defer_count/first_deferred_at 不重置，链边界重试照常覆盖）；
                # 丢失条目清出台账（条目未核销，天然仍在 open 池，无需回写）。
                dropped = reclaim_deferred_batches(root)
                if dropped:
                    self._log(
                        "warning",
                        f"code-fix 新链启动：{dropped} 条延迟批 worktree 已丢失，"
                        "清出台账（条目保持 open，可被重新选批）",
                    )
            # 选批排除并集（D4 配套约束）：chain_skipped ∪ 延迟台账 item_ids
            # （失败档案并集由 select_batch 内部经 _failed_item_ids 并入，不在
            # 本变量）——defer 条目在合回成功前始终是 open 且不在失败档案，不
            # 排除则下一边界 earliest-first 立即重选同批、重跑 agent。
            # severity 分级门限（evo-add-codefix-severity-batch-gate 2.1）：
            # 低于门限且未到周批窗口的条目由 select_batch 同一谓词过滤（不进
            # exclude_ids——挂起集是「暂缓」而非本链排除，周批窗口到期后须
            # 自然回流可选池），regression- 前缀条目豁免。
            severity_gate = self._severity_gate()
            exclude_ids = set(chain_skipped) | _deferred_item_ids(root)
            batch = select_batch(
                root,
                cfg.get("batch_size", 20),
                exclude_ids=exclude_ids,
                severity_gate=severity_gate,
            )
            if not batch:
                # open 条目全被排除（失败档案 ∪ chain_skipped）→ consumed 链的
                # 正常收敛出口（selfheal D5），MUST NOT 误报为故障；进度刷新为
                # 终态防前端停在陈旧的「修复中」快照，文案按排除来源区分：
                # 链内跳过/预算内档案=下轮自动重试，仅达上限档案保留人工指引
                # （reason 亦区分：failed_batch_retained=自愈等待 vs
                # failed_batch_maxed=需人工，供前端分级渲染）。
                prev_snapshot = read_progress(root)
                if prev_snapshot.get("running") or prev_snapshot.get("phase") in (
                    "failed",
                    "blocked",
                ):
                    # maxed 判定收窄到本轮实际参与排除的档案记录（code-review
                    # item 4ac4bea334b2 收窄语义保留 + item 643b6d778de3 修复
                    # 不可达）：按「该档案条目在台账中仍为 open」判定而非与
                    # exclude_ids 求交——各失败收尾路径入档都不写
                    # chain_skipped/延迟台账（defer 降级入档时条目已移出台账），
                    # 档案条目与 exclude_ids 求交恒为空集，旧判据下 maxed 恒
                    # False、failed_batch_maxed 需人工态不可达。仍 open 的在档
                    # 条目即真实参与本轮排除（select_batch 排除非 released 失败
                    # 档案并集）；人工已置终态（resolved/in_spec/ignored）条目
                    # 不计入，released 墓碑（重回可选池）同口径跳过；台账读失败
                    # 按空集 fail-open（同 _open_ids_for_archive 先例）。fail_count
                    # 解析类型容错（外部直改非数值按缺省 1）。
                    try:
                        ledger = read_items(root)
                    except Exception:  # noqa: BLE001 — 台账读失败按空集（maxed 判 False）
                        ledger = {}
                    # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档
                    # 非列表标量的记录不计 maxed，MUST NOT 让 TypeError 上穿
                    # 炸掉本轮投递的「选批为空」收敛出口。
                    maxed = any(
                        not rec.get("released")
                        and isinstance(rec.get("item_ids"), list)
                        and any(
                            (ledger.get(str(i)) or {}).get("status") == "open"
                            for i in rec["item_ids"]
                        )
                        and _fail_count_int(rec.get("fail_count"))
                        >= _effective_retry_budget(rec)
                        for rec in load_failed_batches(root)
                    )
                    # severity 挂起集对账（evo-add-codefix-severity-batch-gate
                    # 2.1）：选批为空若因「剩余 open 条目全部低于门限挂起」
                    # 所致，按「挂起」收敛而非 skipped/lost（spec「deferred
                    # 不误判收敛」）——链内跳过/失败档案在档条目不属挂起集，
                    # 混合场景仍走下方既有分级文案并附加挂起注记。
                    # 挂起集与 select_batch 同池同排除（2026-10-11 误报
                    # 修复）：exclude_ids 并失败档案并集＝选批内部排除
                    # 口径，且池限定 open（resolved/ignored 条目残留老锚
                    # 不参与组放行判定——曾令挂起集恒空、blocked 误落
                    # failed_batch_retained「链内跳过/预算内失败」文案）。
                    sev_deferred_ids = severity_deferred_open_ids(
                        root,
                        gate=severity_gate,
                        exclude_ids=exclude_ids | _failed_item_ids(root),
                    )
                    open_ids_now = {
                        str(iid)
                        for iid, rec in ledger.items()
                        if isinstance(rec, dict) and rec.get("status") == "open"
                    }
                    sev_note = (
                        f"；另 {len(sev_deferred_ids)} 条低于门限条目挂起至周批"
                        if sev_deferred_ids
                        else ""
                    )
                    sev_pure = (
                        bool(sev_deferred_ids)
                        and bool(open_ids_now)
                        and open_ids_now <= sev_deferred_ids
                    )
                    if deferred_msg:
                        # 延迟批本轮有结果：收敛文案以 defer 语义为主（D7），
                        # 跳过/达上限信息保留后半句。reason 按返回消息分类
                        # （code-review item 204d1fc36266）：仅「延迟批合回待
                        # 重试」前缀＝仍被 WIP 阻断，保持 wip_gate_blocked
                        # 受阻态透传；已合回终态（合回成功核销/已合回未核销/
                        # 超预算入失败档案，_retry_one_deferred 其余非空返回）
                        # 非受阻，MUST NOT 误标 wip_gate_blocked——按排除来源
                        # 分级 reason（与下方无延迟批分支同口径），phase 由写
                        # 点按 severity_deferred=idle／其余=blocked 落。前缀
                        # 须与 _retry_one_deferred 阻断文案（「延迟批合回待
                        # 重试（主树未提交改动：…）」）保持同步。
                        current = deferred_msg + (
                            "；含已达自动重试上限条目，需人工排查"
                            if maxed
                            else "；其余跳过条目下轮自动重试"
                        ) + sev_note
                        if deferred_msg.startswith("延迟批合回待重试"):
                            reason = "wip_gate_blocked"
                        elif maxed:
                            reason = "failed_batch_maxed"
                        elif sev_pure:
                            reason = "severity_deferred"
                        else:
                            reason = "failed_batch_retained"
                    elif maxed:
                        current = (
                            "open 条目均已跳过（含已达自动重试上限的条目，需人工排查）；"
                            "其余条目下轮自动重试" + sev_note
                        )
                        # 含达上限条目=需人工，与纯自愈等待（failed_batch_retained）
                        # reason 区分：前端按 reason 渲染中性等待态 vs 红色需人工态
                        # （reason 漂移时前端按需人工回退，宁严勿松）。
                        reason = "failed_batch_maxed"
                    elif sev_pure:
                        # 纯挂起收敛（健康等待态）：phase=idle 与「无 open 条目」
                        # 收敛同态，reason 单列供前端透传；周批窗口到期后下一
                        # checkpoint 自然放行整组重投。
                        current = (
                            f"剩余 {len(sev_deferred_ids)} 条 open 条目均低于严重度"
                            f"门限（min_immediate_severity="
                            f"{severity_gate.get('min_immediate_severity')}），"
                            "挂起至周批窗口（minor_batch_cadence="
                            f"{severity_gate.get('minor_batch_cadence')} 天）"
                            "后统一修复"
                        )
                        reason = "severity_deferred"
                    else:
                        current = (
                            "open 条目均已跳过（链内跳过/预算内失败），下轮自动重试"
                            + sev_note
                        )
                        reason = "failed_batch_retained"
                    if reason == "severity_deferred":
                        write_progress(
                            root,
                            running=False,
                            phase="idle",
                            reason=reason,
                            current=current,
                            worktree=None,
                            run_id=None,
                            batch_total=None,
                            manual_authorized=False,
                            chain_skipped=chain_skipped,
                            # 纯挂起收敛＝链正常收敛出口（周批窗口到期重投）
                            **self._chain_terminal_fields("chain_converged"),
                        )
                    else:
                        write_progress(
                            root,
                            running=False,
                            phase="blocked",
                            reason=reason,
                            current=current,
                            worktree=None,
                            run_id=None,
                            batch_total=None,
                            manual_authorized=False,
                            chain_skipped=chain_skipped,
                            # 跳批终局（2.1「链中途终局（失败/跳批）同样输出累计值」）
                            **self._chain_terminal_fields("chain_exhausted"),
                        )
                return {"triggered": False, "reason": "no_open_items"}

            # 选批前 WIP 重叠预检（evo-add-codefix-batch-wip-precheck 1.1）：
            # select_batch 之后、契约守卫与批投递之前——主树脏 tracked 文件
            # 与候选批条目 file 重叠时整批推迟，把冲突消在 agent run 与回归
            # 之前（merge-time 闸门只兜 agent 实际改动超出台账 file 的残余）。
            wip_overlap = self._wip_overlap_at_select(batch)
            if wip_overlap:
                # 推迟出口（1.2/1.3）：不置单飞、不投递批 worker、不耗实现
                # 预算，台账条目保持 open，下轮节拍自然重查；不投递即无自驱动
                # 再投递，重查只随外部节拍发生（无空转面）。进度写点无条件写
                # （MUST NOT 照抄「选批为空」出口的 live 链条件——无链状态下
                # WIP 冲突不可观测，违反「推迟可观测」Requirement），字段形态
                # 纳入既有 blocked 分流文案体系（reason 前端直接透传，无需
                # 前端改动）。
                current = (
                    "选批预检：主树未提交改动与候选批重叠，整批推迟"
                    f"（提交或 stash 主树这些改动后自动恢复）："
                    f"{_fmt_overlap(wip_overlap)}"
                )
                self._log(
                    "info",
                    "code-fix 选批预检命中 WIP 重叠，整批推迟："
                    f"{_fmt_overlap(wip_overlap)}",
                )
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="wip_overlap_at_select",
                    current=current,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                    **self._chain_terminal_fields("wip_overlap_blocked"),
                )
                return {"triggered": False, "reason": "wip_overlap_at_select"}
            batch_no += 1

            # 回归契约守卫（D5 fail-closed）：契约缺失/缺段 → 发信号、不派批
            contract = load_verify_contract(root, logger=self._logger)
            if contract is None:
                # 告警写盘失败不得劫持 fail-closed 收尾（code-review item
                # 2ab1bb5633f0，同 _defer_merge_back 手法）：异常上穿会跳过
                # 紧随的 blocked 进度写点并中断 checkpoint 调用方。
                try:
                    write_regression_signal(
                        root, "verify_contract_missing", logger=self._logger
                    )
                except Exception as e:  # noqa: BLE001 — 信号通道失败只留痕
                    self._log(
                        "warning",
                        f"code-fix 回归契约缺失信号写盘异常（收尾不受影响）: {e}",
                    )
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="regression_contract_missing",
                    current="等待 verify.yaml 契约起草完成",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                    **self._chain_terminal_fields("regression_contract_missing"),
                )
                return {"triggered": False, "reason": "regression_contract_missing"}
            if contract.regression is None:
                # 同上（code-review item 2ab1bb5633f0）：告警写盘失败不劫持收尾。
                try:
                    write_regression_signal(
                        root, "verify_regression_missing", logger=self._logger
                    )
                except Exception as e:  # noqa: BLE001 — 信号通道失败只留痕
                    self._log(
                        "warning",
                        f"code-fix 回归段缺失信号写盘异常（收尾不受影响）: {e}",
                    )
                write_progress(
                    root,
                    running=False,
                    phase="blocked",
                    reason="regression_section_missing",
                    current="等待 verify.yaml regression 段补写完成",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    manual_authorized=False,
                    chain_skipped=chain_skipped,
                    **self._chain_terminal_fields("regression_section_missing"),
                )
                return {"triggered": False, "reason": "regression_section_missing"}

            # 投递：置单飞 → 写运行中进度 → 批 worker（经 executor 或同步）。
            # 异常安全（ocr 收尾审查）：置位后任一步（进度盘写 / executor.submit）
            # 抛出时必须复位单飞，否则后续 checkpoint 恒 already_running，车道死锁。
            self._in_flight = True
            try:
                item_ids = [rec.get("item_id") for rec in batch]
                write_progress(
                    root,
                    running=True,
                    phase="selecting",
                    activation_id=activation_id,
                    total=total,
                    done=done,
                    batch_no=batch_no,
                    current=f"第 {batch_no} 批启动（{len(batch)} 条）",
                    reason="",
                    # 批上下文防御性归零（D2）：上一批收尾写点已清三键，此处
                    # 显式置 null 保证「切批 selecting 写时批上下文必为 null」
                    # （含保留 worktree 的失败批防陈旧索引）；新批上下文在建
                    # 树成功后的 fixing 写点才落。
                    worktree=None,
                    run_id=None,
                    batch_total=None,
                    # 手动授权随链持久化：本批由 override 投出，或延续 live
                    # 链已有的授权（batch 间 phase 改写不得丢失旗标）。
                    manual_authorized=bool(override_enabled) or chain_authorized,
                    # 链内跳过集：同链沿用（merge 语义下显式透传防剥落），新链
                    # 已在上分支重置为空——写入 [] 覆盖上一链残留。
                    chain_skipped=chain_skipped,
                    # 链级累积（2.2）：新链显式归零重置（含上一链被更替时未
                    # 出账的残余）；同链不传——合并写保留现值，run 清单由批
                    # worker 在 run 启动写点逐 run 追加。
                    **(
                        {
                            "chain_run_ids": [],
                            "chain_resolved": 0,
                            "chain_ignored": 0,
                        }
                        if new_chain
                        else {}
                    ),
                )
                ctx = {
                    "activation_id": activation_id,
                    "total": total,
                    "done": done,
                    "batch_no": batch_no,
                    "items": batch,
                    "item_ids": item_ids,
                    "regression_spec": contract.regression,
                    # 链内跳过集随批上下文下发（add-codefix-affinity-batching
                    # 3.1）：批 worker 的链末批判定与链选批同口径必需（失败
                    # 档案在 select_batch 内部排除，chain_skipped/延迟台账
                    # 由判定函数并入排除集）。
                    "chain_skipped": list(chain_skipped),
                    # 链级 run 清单基线（2.2）：批 worker 在首个 run 启动写点
                    # 追加本批 run_id（重试轮由 _run_batch_created 续加）。
                    "chain_run_ids": list(chain_run_ids),
                }
            except Exception as exc:
                self._in_flight = False
                self._log("error", f"code-fix 投递前置异常（已复位单飞）: {exc}")
                return {"triggered": False, "reason": "dispatch_prepare_error"}
        # 锁外投递（worker 内会再进 checkpoint，锁内 submit 会死锁）
        try:
            self._dispatch(ctx)
        except Exception as exc:
            # 同步模式下批 worker 自身已兜底（_run_batch 的 try/finally），
            # 走到这里的是 submit 被拒（解释器关闭）等投递层异常。
            self._in_flight = False
            self._log("error", f"code-fix 投递异常（已复位单飞）: {exc}")
            return {"triggered": False, "reason": "dispatch_error"}
        return {"triggered": True, "reason": "dispatched"}

    def _dispatch(self, ctx: dict) -> None:
        if self._executor is not None:
            self._executor.submit(self._run_batch, ctx)
        else:
            # 无 executor（测试/禁用态）：同步执行，保证 checkpoint 语义可断言
            self._run_batch(ctx)

    def _resubmit(self) -> None:
        """批收尾后的自驱动再投递（D4：经 executor 而非递归直调，避免嵌套）。"""
        if self._executor is not None:
            self._executor.submit(self.checkpoint)
        else:
            self.checkpoint()

    # -- 批 worker（5.4/5.6/5.8）-------------------------------------------

    def _finish(self, phase: str, reason: str = "", **fields) -> None:
        """halt 收尾（链终止）：复位单飞 + 刷新进度（running 由下次 checkpoint 收尾）。

        仅环境性失败路径使用（worktree_manager_missing / worktree_create_failed /
        批 worker 异常，selfheal D1）：链终止、不自驱动，授权旗标一并清除；
        批上下文三键同步清除——不清则读侧会带着陈旧 worktree/run_id 继续合成
        条级字段（D2 防陈旧索引）。consumed 失败收尾走 ``_consumed_progress``
        （链继续，不请旗标）。
        """
        self._in_flight = False
        write_progress(
            self.project_root,
            phase=phase,
            reason=reason,
            worktree=None,
            run_id=None,
            batch_total=None,
            manual_authorized=False,
            # 链中途终局（halt）同样出账（2.1）：rollup 随本写点落盘并清账。
            **self._chain_terminal_fields("halt"),
            **fields,
        )

    # -- 链级 rollup（evo-add-codefix-digest-cost-metrics 2.1/2.2）---------

    def _chain_bump(self, root, **deltas) -> None:
        """链级核销计数累加（2.1「条目计数与台账核销一致」）。

        在 mark_resolved / mark_ignored 真实命中**之后**调用（传终态过滤后的
        返回值），随链累积进进度快照——rollup 时点读出即台账口径，不另设独立
        计数通道。失败仅告警，MUST NOT 阻断批收尾主流程。
        """
        if not deltas:
            return
        try:
            prev = read_progress(root)
            fields = {}
            for key, delta in deltas.items():
                try:
                    step = int(delta)
                    base = int(prev.get(key) or 0)
                except (TypeError, ValueError):
                    continue
                if step:
                    fields[key] = base + step
            if fields:
                write_progress(root, **fields)
        except Exception as e:  # noqa: BLE001 — 计数失败不阻断批收尾
            self._log("warning", f"code-fix 链级核销计数更新失败: {e}")

    def _consume_failed_registrations(self, root) -> int:
        """失败登记闭环核销的统一挂点（add-codefix-failure-registration-closeout
        1.1）：批收尾/合回核销点（mark_ignored/mark_resolved 及延迟批合回）
        后即时检查 + 新链启动簿记块周期兜底，各挂点共用本方法。fail-open：
        对账/写盘异常只留痕，MUST NOT 阻断批收尾与链启动主流程。返回本轮
        核销的记录数。
        """
        try:
            consumed = consume_resolved_failed_batches(
                root, logger=self._logger
            )
        except Exception as e:  # noqa: BLE001 — 核销失败不阻断主流程
            self._log(
                "warning", f"code-fix 失败登记核销对账异常（跳过本轮）: {e}"
            )
            return 0
        if consumed:
            self._log(
                "info",
                f"code-fix 失败登记核销：{consumed} 条登记的被跳过条目已全部"
                "终态，已收口对应告警与 todo 登记",
            )
        return consumed

    def _chain_rollup_snapshot(self) -> dict:
        """按链级累积值汇总 rollup 快照（纯读侧，2.1/2.2）。

        run 维度：以链级持久 run 清单（chain_run_ids）逐 run 读 run 归档（先
        顶层 ``.fenix/runs/<run_id>.jsonl``，缺失回退 ``archive/`` 副本）末
        条 run_metrics 行求和——「覆盖链中全部 run 不漏样本」由清单机械达成；
        两处皆缺按零贡献。条目维度：读
        链级核销计数（chain_resolved/chain_ignored，即台账核销口径）。
        """
        prog = read_progress(self.project_root)
        # 链级 run 清单形态守卫（code-review item 28ee3c6558b0，对齐 checkpoint
        # 与 _chain_recent_duration_mean 对同字段既有守卫）：坏档非列表真值直接
        # 迭代会按字符拆出假 run_id，rollup 静默产出垃圾统计（runs=字符个数）。
        # 先判 isinstance(list) 再归一去重，非列表回退空列表（truthy 垃圾值
        # warning 留痕；None/空值静默回退，等价旧 or [] 语义）。
        raw_run_ids = prog.get("chain_run_ids")
        if isinstance(raw_run_ids, list):
            prev_run_ids = list(raw_run_ids)
        else:
            if raw_run_ids:
                self._log(
                    "warning",
                    "code-fix 进度 chain_run_ids 字段形态异常（非列表："
                    f"{type(raw_run_ids).__name__}），按空列表容错",
                )
            prev_run_ids = []
        run_ids: list[str] = []
        for rid in prev_run_ids:
            s = str(rid)
            if s and s not in run_ids:
                run_ids.append(s)
        total_turns = total_tools = total_text = 0
        for rid in run_ids:
            m = _read_run_metrics(self.project_root, rid)
            try:
                turns = int(m.get("turns") or 0)
                tools = int(m.get("tool_uses_total") or 0)
                text = int(m.get("text_turns") or 0)
            except (TypeError, ValueError):
                continue
            total_turns += turns
            total_tools += tools
            total_text += text

        def _chain_count_int(key: str) -> int:
            # 链级核销计数容错解析（同条目 28ee3c6558b0，对齐 defer_count 解析
            # 口径）：非数值坏值裸 int() 抛 ValueError 会被 _emit_chain_rollup
            # 吞成返回 None——链终局清零字段永不落地，该链后续 rollup 永久
            # 失效、坏值无法自愈。非数值按 0 出账（truthy 垃圾值 warning
            # 留痕），确保链终局归零总能落地。
            raw = prog.get(key)
            try:
                return int(raw or 0)
            except (TypeError, ValueError):
                if raw:
                    self._log(
                        "warning",
                        f"code-fix 进度 {key} 字段形态异常（非数值："
                        f"{type(raw).__name__}），按 0 容错",
                    )
                return 0

        resolved = _chain_count_int("chain_resolved")
        ignored = _chain_count_int("chain_ignored")
        items = resolved + ignored
        return {
            "runs": len(run_ids),
            "turns": total_turns,
            "tool_uses_total": total_tools,
            "text_turns": total_text,
            "resolved": resolved,
            "ignored": ignored,
            "avg_turns_per_item": (round(total_turns / items, 1) if items else None),
            "run_ids": run_ids,
        }

    def _emit_chain_rollup(self, trigger: str) -> dict | None:
        """汇总并打一行结构化 rollup 日志（2.1）；无链级累积返回 None。

        「有累积」判据 = run 清单非空或核销计数非零（延迟批在链终局后核销的
        残余也可见，runs=0 仍出账）。异常一律吞掉转 warning——rollup 是纯
        观测，MUST NOT 阻断链终局写点。
        """
        try:
            snap = self._chain_rollup_snapshot()
        except Exception as e:  # noqa: BLE001 — 观测失败不阻断链收尾
            self._log("warning", f"code-fix chain rollup 汇总失败: {e}")
            return None
        if not snap["run_ids"] and not (snap["resolved"] or snap["ignored"]):
            return None
        snap["trigger"] = trigger
        snap["finished_at"] = _now_iso()
        self._log(
            "info",
            "code-fix chain rollup: "
            f"trigger={trigger} runs={snap['runs']} turns={snap['turns']} "
            f"tool_uses={snap['tool_uses_total']} text_turns={snap['text_turns']} "
            f"resolved={snap['resolved']} ignored={snap['ignored']} "
            f"avg_turns_per_item={snap['avg_turns_per_item']} "
            f"run_ids={','.join(snap['run_ids'])}",
        )
        return snap

    def _chain_terminal_fields(self, trigger: str) -> dict:
        """链终局写点字段（2.1「随链状态落盘」）：rollup 快照 + 累积值归零。

        供各链终局 write_progress 调用点 ``**`` 展开；无链级累积时返回空
        dict（不触碰链级字段，无链 checkpoint 零开销）。归零即「出账后清账」
        ——同一链不会被后续终局写点重复出账，新链从空累积起步。
        """
        rollup = self._emit_chain_rollup(trigger)
        if rollup is None:
            return {}
        return {
            "chain_rollup": rollup,
            "chain_run_ids": [],
            "chain_resolved": 0,
            "chain_ignored": 0,
        }

    def _consumed_progress(self, current: str, reason: str = "", chain_skip_ids=None) -> None:
        """consumed 失败收尾（selfheal D6）：链内跳过 + 非终态进度，链继续。

        与 ``_finish``（halt 终态）相对：不复位 running、不清 manual_authorized
        （链上授权随自驱动继续生效）；``chain_skip_ids`` 非 None 时把该批条目
        并入进度快照 ``chain_skipped``（原子写合并语义，本链 select_batch 不再
        选中，新链启动时重置）；批上下文三键同步清除（worktree 已 cleanup，
        D2 防陈旧索引）。
        """
        self._in_flight = False
        fields = {}
        if chain_skip_ids is not None:
            # 字段形态守卫与 checkpoint 链级读侧同口径（code-review item
            # 3f883a9ac93c / 959c61f66ce3）：chain_skipped 被外部写坏成非列表
            # 标量时直接迭代会抛 TypeError，沿批 worker 兜底升级成 halt 终止
            # 链；非空字符串则被逐字符拆成假 item_id 并入排除集。按「损坏不炸
            # 主流程」纪律先判 isinstance(list) 再拷贝，非列表回退空列表
            # （truthy 垃圾值 warning 留痕；None/空值静默回退）。
            raw_ids = read_progress(self.project_root).get("chain_skipped")
            if isinstance(raw_ids, list):
                prev_ids = list(raw_ids)
            else:
                if raw_ids:
                    self._log(
                        "warning",
                        "code-fix 进度 chain_skipped 字段形态异常（非列表："
                        f"{type(raw_ids).__name__}），按空列表容错",
                    )
                prev_ids = []
            fields["chain_skipped"] = list(
                dict.fromkeys(
                    [str(i) for i in prev_ids] + [str(i) for i in chain_skip_ids]
                )
            )
        write_progress(
            self.project_root,
            phase="fixing",
            reason=reason,
            current=current,
            worktree=None,
            run_id=None,
            batch_total=None,
            **fields,
        )

    # -- 延迟合回（fix-codefix-wipgate-defer D4/D6）-------------------------

    def _process_deferred_merges(self):
        """链边界重试延迟批合回：遍历台账逐条对保留 worktree 重跑 merge_back。

        不重跑 agent（产物已提交在分支上，只差合回）；不新增线程/定时器，
        挂在既有链节拍上（调用点见 checkpoint：选批之前 ∪ 收敛早退之前）。
        逐条 try/except 兜底（同 ``_safe_cleanup`` 哲学：单条异常记 warning
        后继续下一条，不炸链节拍）。

        Returns: ``(deferred_done, deferred_msg)``——本轮累计核销条数（供调用
        方并入链 done）与末条结果文案（供收敛早退出口透传，D7）；台账空时
        ``(0, "")``（零开销早退）。
        """
        root = self.project_root
        entries = load_deferred_batches(root)
        if not entries:
            return 0, ""
        wm = getattr(self._agent_runner, "worktree_manager", None)
        if wm is None:
            return 0, ""
        done_hits = 0
        last_msg = ""
        for entry in entries:
            try:
                hit, msg = self._retry_one_deferred(wm, entry)
            except Exception as e:  # noqa: BLE001 — 单条重试异常不炸链节拍
                self._log(
                    "warning",
                    f"code-fix 延迟批重试异常（branch="
                    f"{entry.get('branch')}）: {e}",
                )
                continue
            done_hits += hit
            if msg:
                last_msg = msg
        return done_hits, last_msg

    # ── 占用者协调（add-mergeback-wip-active-coordination 1.1/2.1/2.2）────

    def _orphan_grace_minutes(self) -> float:
        """无主陈旧 WIP 宽限（分钟）：``admin.mergeback_wip_orphan_grace_minutes``。

        缺省 30（对齐 admin escalation cooldown 量级，design D4）；解析失败/
        负值/NaN 回退缺省——配置事故 MUST NOT 放大成「无限期静默等待」极端。
        ``0`` 是合法配置＝「耗尽即升级」（spec 3.2「配置可收紧」契约，
        test_grace_zero_escalates_immediately 冻结；告警经 owner_escalated_at
        一次性去重，秒升级无刷屏风险）。
        """
        try:
            raw = ConfigLoader.get(
                self._get_root_config(),
                "admin.mergeback_wip_orphan_grace_minutes",
                30,
            )
            val = float(raw)
        except (TypeError, ValueError):
            return 30.0
        # 负值/NaN 回退（NaN 由 val != val 判别）：NaN 使宽限比较恒假，退化
        # 为被声明禁止的「无限期静默等待」极端。0 不在回退之列（见 docstring；
        # code-review item 56c8f34f1df5 曾把 0 一并回退，与本冻结场景契约冲突
        # 令回归红，此处按 spec 口径恢复 0 的合法语义）。
        if val != val or val < 0:
            return 30.0
        # inf 或超合理上限（一天）等同「无限期静默等待」，同回退缺省。
        if val == float("inf") or val > 24 * 60:
            return 30.0
        return val

    def _make_holder_retry_callback(self, branch: str):
        """持有者 run 终态回调工厂（D5）。

        事件驱动的重试 MUST 复用既有单一重试入口——``checkpoint()``（
        ``_process_deferred_merges`` 的唯一调用点，位于 ``self._lock`` 段内、
        ``already_running`` 守卫之后），MUST NOT 从事件回调线程旁路直调
        ``_process_deferred_merges``；在飞批期间本回调按 ``already_running``
        早退，由链边界节拍兜底（秒级让位于正确性）。回调异常自兜（fire 侧
        还有 runner 侧兜底），轮询路径始终在场作为事件丢失防线（D3）。

        锁占用守卫（``threading.Lock`` 不可重入）：注册时「run 已终态→立即
        触发」的同步路径可能发生在**本线程已持有 ``self._lock``** 的上下文
        （``_retry_one_deferred`` 的注册点位于 checkpoint 锁段内）——此时重入
        ``checkpoint()`` 即自锁死；另一线程的 checkpoint 在飞时，该 checkpoint
        本身就会重试延迟批，事件重试亦属冗余。两种形态一律让位：锁空闲才投
        递 checkpoint，否则并入当前/后续节拍（竞态窗口内锁被他人抢占只是
        bounded 等待，无死锁面）。
        """
        def _cb():
            self._log(
                "info",
                f"持有者 run 终态到达（branch={branch}）— 事件驱动重试延迟批合回",
            )
            if self._lock.locked():
                self._log(
                    "info",
                    "checkpoint 锁占用中——事件重试并入当前/后续链节拍"
                    "（该节拍同样会重试延迟批，无需重入）",
                )
                return
            try:
                self.checkpoint()
            except Exception as e:  # noqa: BLE001 — 事件重试失败由轮询兜底
                self._log(
                    "warning",
                    f"事件驱动重试触发失败（轮询兜底路径继续在场）: {e}",
                )
        return _cb

    def _inflight_impl_run_ids(self) -> list:
        """在飞实现车道 run_id 列表（agent_runner 注册表快照，D1 数据源）。"""
        running = getattr(self._agent_runner, "_running_agents", None) or {}
        return [str(rid) for rid in running.keys()]

    def _coordinate_blocked_merge(self, entry, item_ids, overlap, branch, tip_sha) -> str:
        """被挡批的占用者协调：识别 → 订阅/宽限 → 台账与留痕。

        在 defer 消费路径的两个被挡点（批收尾 ``_defer_merge_back`` 与重试
        ``_retry_one_deferred``）调用（design D5：识别与订阅挂在 defer 消费
        路径上）。行为：

        - overlap 为空 → 直接返回空串（零识别、零订阅开销，spec「无 overlap
          零变化」）；
        - 识别命中在飞持有者 → ``owner_*`` 字段随台账留痕 + 注册持有者 run
          终态监听（subscriber 键按分支稳定覆盖，轮询重复注册不累积）；
        - 识别为无主 → 记 ``owner_orphan_since``（首次）宽限计时；宽限耗尽
          且未升级过 → 写一次性 major 告警（``_write_defer_orphan_alert``）
          并记 ``owner_escalated_at``。批保持「保留待自动合回」语义——升级
          不改变批的预算/台账状态（D5）；
        - 识别结果随台账 ``owner_*`` 字段与进度/日志留痕（返回摘要文案供
          调用方并入进度 current）。

        Returns: 识别摘要文案（识别不可用/无 overlap 时为空串）。
        """
        if not overlap:
            return ""
        try:
            return self._coordinate_blocked_merge_impl(
                entry, item_ids, overlap, branch, tip_sha
            )
        except Exception as e:  # noqa: BLE001 — 协调异常不影响 defer 保留语义
            self._log(
                "warning",
                f"占用者协调异常（不影响 defer 保留语义，轮询兜底）: {e}",
            )
            return ""

    def _coordinate_blocked_merge_impl(self, entry, item_ids, overlap, branch, tip_sha) -> str:
        root = self.project_root
        runner = self._agent_runner
        wm = getattr(runner, "worktree_manager", None)
        identify = getattr(wm, "identify_wip_occupant", None)
        if not callable(identify):
            return ""
        info = identify(overlap, self._inflight_impl_run_ids())
        # 会话归因（主树活交互会话，evo-add-maintree-interactive-session-
        # attribution 2.2）的采信受 admin.maintree_session_attribution_action
        # 同键约束（与 stray_wip 盘点侧对称，复用同一读取器、不复制探测）：
        # info＝采信（owner_kind=holder，不计时升级）；keep＝视同零命中走
        # 现状 orphan 宽限升级流（evidence 仍透传 describe() 会话线索）。
        # 会话归因 holders 无 run_ids → 终态回调注册自然缺席（事件驱动重试
        # 缺席、既有轮询兜底在场，行为安全）。
        session_attributed = info.holder and info.is_session_attribution()
        session_trusted = True
        if session_attributed:
            from core.worktree_manager.stray_wip import session_attribution_action

            session_trusted = session_attribution_action(self._get_root_config()) != "keep"
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        fields = {
            "owner_kind": (
                "holder" if (info.holder and (not session_attributed or session_trusted)) else "orphan"
            ),
            "owner_holders": info.to_dict()["holders"],
            "owner_identified_at": now,
        }
        if info.holder and (not session_attributed or session_trusted):
            # 识别结果变化（无主→有主）：宽限计时清零重计（design D2 轮询
            # 时识别结果变化随之更新）。
            fields["owner_orphan_since"] = None
            holder_run_ids = info.holder_run_ids()
            register = getattr(runner, "register_run_terminal_callback", None)
            if holder_run_ids and callable(register):
                for rid in holder_run_ids:
                    register(
                        rid,
                        self._make_holder_retry_callback(branch),
                        subscriber=f"code-fix-defer:{branch}",
                    )
                self._log(
                    "info",
                    f"延迟批占用者为在飞车道，已注册其终态监听（事件驱动重试）"
                    f": branch={branch}, holder_runs={holder_run_ids}",
                )
            elif session_attributed:
                self._log(
                    "info",
                    f"延迟批占用者为主树活交互会话（会话归因无 run 终态可订阅"
                    f"，事件驱动重试缺席、轮询兜底在场）: branch={branch}",
                )
            note = info.describe()
        else:
            # 无主：宽限计时（首次记 since），耗尽升级一次性 major 告警。
            since = str(entry.get("owner_orphan_since") or "") or now
            fields["owner_orphan_since"] = since
            note = info.describe()
            if session_attributed and not session_trusted:
                note += (
                    "（会话归因未采信：admin.maintree_session_attribution_action"
                    "=keep，视同零命中走无主宽限升级）"
                )
            grace = self._orphan_grace_minutes()
            try:
                start = calendar.timegm(time.strptime(since, "%Y-%m-%dT%H:%M:%SZ"))
                elapsed_min = (time.time() - start) / 60.0
            except (ValueError, TypeError):
                elapsed_min = 0.0
            if elapsed_min >= grace and not entry.get("owner_escalated_at"):
                fields["owner_escalated_at"] = now
                _write_defer_orphan_alert(
                    root, item_ids, overlap, branch=branch, tip_sha=tip_sha,
                    grace_minutes=grace, orphan_since=since,
                    owner_note=note, logger=self._logger,
                )
                self._log(
                    "warning",
                    f"延迟批占用者为无主陈旧 WIP 且宽限（{grace} 分钟）耗尽，"
                    f"已升级 major 人工告警（批保持保留待自动合回）"
                    f": branch={branch}, 重叠={_fmt_overlap(overlap)}",
                )
                note = f"{note}；宽限已耗尽，已升级 major 人工告警"
            else:
                note = (
                    f"{note}；宽限 {grace:g} 分钟内继续事件驱动等待"
                    f"（自 {since} 起）"
                )
        _patch_deferred_entry(root, item_ids, **fields)
        return note

    def _retry_one_deferred(self, wm, entry) -> tuple:
        """单条延迟批重试，结果四分派（D4/2.1）。返回 ``(核销数, 结果文案)``。"""
        root = self.project_root
        # item_ids 形态守卫（code-review item 3bf751ec88d9）：坏档非列表标量
        # 按空列表容错（后续移出/降级路径不炸；空集使 _remove_deferred_batch
        # 无命中，坏档滞留由时间门/磁盘对账兜底）。
        _raw_ids = entry.get("item_ids")
        item_ids = [str(i) for i in _raw_ids] if isinstance(_raw_ids, list) else []
        # fixed_ids 形态守卫（code-review item a4e188106d9e，对齐上方 item_ids
        # 既有守卫）：坏档非列表真值按字符拆出假 id，永不命中核销前 batch_set
        # ——合回成功 hit=0 仍清理现场并移出台账，已合回未核销、条目下链重选
        # 重跑（5905398dbbcb 同类危害）。先判 isinstance(list) 再归一，非列表
        # 回退空列表（truthy 垃圾值 warning 留痕并置坏档旗标；None/空值静默
        # 回退走既有 hit=0 防御路径）。
        _raw_fixed = entry.get("fixed_ids")
        fixed_ids_bad_shape = False
        if isinstance(_raw_fixed, list):
            fixed_ids = [str(i) for i in _raw_fixed]
        else:
            if _raw_fixed:
                fixed_ids_bad_shape = True
                self._log(
                    "warning",
                    "code-fix 延迟台账 fixed_ids 字段形态异常（非列表："
                    f"{type(_raw_fixed).__name__}），按空列表容错",
                )
            fixed_ids = []
        wt = Path(str(entry.get("worktree") or ""))
        branch = str(entry.get("branch") or "")
        tip_sha = str(entry.get("tip_sha") or "")
        # last_overlap 同款守卫：坏档非列表真值 list() 抛 TypeError，被
        # _process_deferred_merges 单条兜底吞成 warning——该条目每轮链边界
        # 重试稳定复现、永久滞留且其 items 被永久排除出选批。
        _raw_overlap = entry.get("last_overlap")
        if isinstance(_raw_overlap, list):
            overlap = list(_raw_overlap)
        else:
            if _raw_overlap:
                self._log(
                    "warning",
                    "code-fix 延迟台账 last_overlap 字段形态异常（非列表："
                    f"{type(_raw_overlap).__name__}），按空列表容错",
                )
            overlap = []

        # 磁盘真相对账：worktree 已丢失（手删/sweeper 回收）→ 条目回收 +
        # warning；条目未核销天然仍在 open 池，无需回写（D5 同款判据）。
        # 判死移出台账的同时回收仍在 _active_worktrees 在册的 worktree
        # （sweeper 扫孤儿跳过在册目录）：不清理则带修复提交的目录成孤儿，
        # 永无人合回也永无人回收；目录已不在磁盘时跳过（只省噪音日志）。
        if not _deferred_entry_alive(entry):
            if wt.name and wt.exists():
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
            _remove_deferred_batch(root, item_ids)
            self._log(
                "warning",
                f"code-fix 延迟批 worktree 已丢失，条目移出台账"
                f"（条目保持 open，可被重新选批）: {wt}",
            )
            return 0, ""

        # 预算时间门（D6/3.1，先到为准）：超时即降级，不再尝试 merge_back。
        if _defer_time_budget_exhausted(entry):
            self._downgrade_deferred(wm, entry, item_ids, wt, branch, tip_sha, overlap)
            return 0, f"延迟批合回超预算已入失败档案（branch={branch}）"

        merge_info = wm.merge_back(wt)
        if getattr(merge_info, "success", False):
            # 成功 → 核销 fixed_ids 中仍 open 的子集。defer 窗口内被人工置
            # 终态的条目跳过：mark_resolved 对命中 id 无条件置 resolved、无
            # 终态保护，核销方 MUST 先以 read_items 过滤（不能依赖其幂等）。
            hit = 0
            ledger_read_failed = False
            if fixed_ids:
                # 台账读有限重试（code-review item 5905398dbbcb）：merge_back
                # 成功后此刻瞬时读失败若按空集降级，会「已合回却不核销」且随即
                # 移除台账销毁 fixed_ids——条目仍 open 会被下链重选，agent 在已
                # 含修复的新 HEAD 上多半零提交，跨链反复空转。短间隔重试 3 次，
                # 仍失败则保留台账条目等下一链边界再核销（merge_back 幂等：
                # 分支已是 HEAD 祖先时跳过并报成功，重试无副作用）。
                items = None
                for attempt in range(3):
                    try:
                        items = read_items(root)
                        break
                    except Exception:  # noqa: BLE001 — 重试耗尽走「保留待下链」分支
                        if attempt < 2:
                            time.sleep(0.2 * (attempt + 1))
                if items is None:
                    ledger_read_failed = True
                else:
                    # 批界守卫（与 _run_batch_created 核销前 batch_set 过滤同
                    # 口径）：agent 产物带出的批外 id 不核销。
                    batch_set = set(item_ids)
                    still_open = [
                        i for i in fixed_ids
                        if i in batch_set
                        and (items.get(i) or {}).get("status") == "open"
                    ]
                    if still_open:
                        hit = mark_resolved(root, still_open)
            # 链级核销计数累加（2.1）：以 mark_resolved 真实命中为准，与主路径
            # _run_batch_created 同口径——缺它则延迟批核销不进任何链的 rollup
            # （resolved 计数低于真实台账核销数、纯延迟核销场景整行被判无累积
            # 跳过，code-review item 3776b9915001）。
            if hit:
                self._chain_bump(root, chain_resolved=hit)
            # 失败登记闭环核销（add-codefix-failure-registration-closeout
            # 1.1）：延迟批合回核销点即时检查（与主路径同口径）。
            self._consume_failed_registrations(root)
            if ledger_read_failed:
                # 已合回但核销状态未知（code-review item 5905398dbbcb）：MUST
                # NOT 此刻清理现场/移除台账——fixed_ids 随台账删除而丢失，下链
                # 无法识别修复已在主树。保留条目与 worktree，不动链计数，等下
                # 一链边界重试核销；持续读失败的极端由既有时间门降级路径兜底。
                self._log(
                    "warning",
                    f"code-fix 延迟批已合回但台账读失败（重试耗尽），已合回未核销"
                    f"——保留台账条目与 worktree 待下一链边界重试核销"
                    f"（branch={branch}, item_ids={item_ids}）",
                )
                write_progress(
                    root,
                    reason="",
                    current=(
                        f"延迟批已合回但台账读失败未核销，保留待下一链边界重试"
                        f"（branch={branch}）"
                    ),
                )
                return 0, "延迟批已合回未核销（台账读失败，保留待下链边界重试）"
            if fixed_ids_bad_shape:
                # 已合回但核销集合坏档（code-review item a4e188106d9e）：无法
                # 区分「确实无可核销」与「核销集合已损坏」，此刻清理现场/移除
                # 台账会销毁坏档原文并复刻「已合回未核销、下链重选重跑」危害
                # （5905398dbbcb 同款）。保留条目与 worktree 待人工对账（人工
                # 修复 fixed_ids 后下一边界重试即正常核销）；持续滞留由既有
                # 时间门/次数门降级路径兜底。
                self._log(
                    "warning",
                    f"code-fix 延迟批已合回但 fixed_ids 形态异常（非列表）无法"
                    f"核销——保留台账条目与 worktree 待人工对账"
                    f"（branch={branch}, item_ids={item_ids}）",
                )
                write_progress(
                    root,
                    reason="",
                    current=(
                        f"延迟批已合回但 fixed_ids 坏档未核销，保留待人工对账"
                        f"（branch={branch}）"
                    ),
                )
                return 0, "延迟批已合回未核销（fixed_ids 坏档，保留待人工对账）"
            _safe_cleanup(wm, wt, success=True, logger=self._logger)
            _remove_deferred_batch(root, item_ids)
            prog = read_progress(root)
            # done 数值形态守卫（code-review item 6d719838a2d2，对齐 checkpoint
            # 链级读点 c95bc89c37d6 同款 try-int 口径）：or 0 只兜 None/空值，
            # 进度被外部写坏成非数值标量（如字符串）时裸加法抛 TypeError，被
            # _process_deferred_merges 单条兜底吞成 warning——此刻 merge_back
            # 已成功、现场已清理、台账条目已移除，本批 hit 的进度增量与成功
            # 文案会一并丢失。try int 归一，非法值按 0 容错并 warning 留痕，
            # 本写点即以合法数值覆盖自愈。
            try:
                prev_done = int(prog.get("done") or 0)
            except (TypeError, ValueError):
                if prog.get("done"):
                    self._log(
                        "warning",
                        "code-fix 进度 done 字段形态异常（非数值："
                        f"{type(prog.get('done')).__name__}），按 0 容错",
                    )
                prev_done = 0
            write_progress(
                root,
                done=prev_done + hit,
                reason="",
                current=f"延迟批合回成功（核销 {hit} 条）",
            )
            self._log(
                "info",
                f"code-fix 延迟批合回成功：核销 {hit}/{len(item_ids)} 条"
                f"（branch={branch}）",
            )
            return hit, f"延迟批合回成功（核销 {hit} 条）"

        if bool(getattr(merge_info, "wip_gate_blocked", False)):
            # 仍被阻断：本次确有实际 merge_back 尝试 → defer_count +1（2.3）；
            # first_deferred_at 不动（超时判定只看它）；达次数门降级，否则
            # 台账原样保留等下一边界。
            # defer_count 容错解析（code-review item 601861075cf9，对齐
            # _fail_count_int 同款口径）：被外部写坏成非数值时裸 int() 抛
            # ValueError，会被 _process_deferred_merges 的单条兜底吞成
            # warning——defer_count 永不递增，DEFER_RETRY_MAX 次数门对该条目
            # 永久失效（只剩 90 分钟时间门兜底降级）。非数值按缺省 0 递增，
            # truthy 垃圾值 warning 留痕。
            try:
                prev_defer = int(entry.get("defer_count") or 0)
            except (TypeError, ValueError):
                self._log(
                    "warning",
                    "code-fix 延迟台账 defer_count 字段形态异常（非数值："
                    f"{type(entry.get('defer_count')).__name__}），按 0 递增容错",
                )
                prev_defer = 0
            defer_count = prev_defer + 1
            _patch_deferred_entry(root, item_ids, defer_count=defer_count)
            if defer_count >= DEFER_RETRY_MAX:
                self._downgrade_deferred(
                    wm, entry, item_ids, wt, branch, tip_sha, overlap
                )
                return 0, f"延迟批合回超预算已入失败档案（branch={branch}）"
            msg = (
                f"延迟批合回待重试（主树未提交改动：{_fmt_overlap(overlap)}）"
                "— 已保留，主树清理后自动合回"
            )
            # 占用者协调（add-mergeback-wip-active-coordination 1.1/2.1/2.2）：
            # 识别留痕 + 持有者订阅/无主宽限升级；识别摘要并入进度与返回文案。
            # 固定轮询保持原节拍在场（事件驱动重试的主要唤醒 + 轮询兜底双通道，
            # D3），本路径即轮询兜底本体。
            owner_note = self._coordinate_blocked_merge(
                entry, item_ids, overlap, branch, tip_sha
            )
            if owner_note:
                msg = f"{msg}；{owner_note}"
            write_progress(root, phase="merging", reason="wip_gate_blocked", current=msg)
            return 0, msg

        # 失败且非 wip_gate_blocked（主树 WIP 已被提交后的内容真冲突经预演
        # 闸、或其他 git 失败）→ 按真冲突同语义降级入失败档案（烧预算），
        # worktree 走既有失败收尾，台账移除。
        # 失败档案只收未终态条目（code-review item c94a1770a477，与主路径
        # pending_ids / 65f65b784f2a 核销前过滤同口径）：defer 窗口内被人工
        # 置终态的条目不随批入档。
        open_ids = _open_ids_for_archive(root, item_ids)
        if open_ids:
            # 入档收尾的触顶/降档告警在锁外经 AdminStore 落盘，磁盘满/权限类
            # OSError 上抛会跳过紧随的 cleanup 与台账移除（code-review item
            # ff69fd3d36ec，告警写盘失败不得劫持收尾）——异常降级留痕，收尾照常。
            try:
                record_failed_batch(
                    root, open_ids, wt,
                    reason="merge_back_conflict", branch=branch, tip_sha=tip_sha,
                    logger=self._logger,
                )
            except Exception as e:  # noqa: BLE001 — 入档/告警写盘失败只留痕
                self._log(
                    "warning",
                    f"code-fix 延迟批合回冲突入档案/告警写盘异常"
                    f"（收尾不受影响）: {e}",
                )
        _safe_cleanup(wm, wt, success=False, logger=self._logger)
        _remove_deferred_batch(root, item_ids)
        self._log(
            "error",
            f"code-fix 延迟批合回落真冲突，已入失败档案"
            f"（branch={branch}, tip_sha={tip_sha}）",
        )
        return 0, ""

    def _downgrade_deferred(
        self, wm, entry, item_ids, wt: Path, branch, tip_sha, overlap
    ) -> None:
        """预算双门耗尽降级（D6/3.1）：入失败档案 + 遗产收尾 + 台账移除。

        ``record_failed_batch(reason="wip_gate_blocked_expired")`` 走既有预算
        体系（FAIL_RETRY_MAX 之后是既有 blocked 出口）；``cleanup(success=False)``
        走 implementer 遗产分支，目录由 sweeper 宽限兜底回收。告警一次性按
        条目集指纹（3.2：先查后记，见 ``_has_expired_archive``）。
        """
        root = self.project_root
        # 失败档案只收未终态条目（code-review item c94a1770a477，与主路径
        # pending_ids / 65f65b784f2a 核销前过滤同口径）：defer 窗口内被人工
        # 置终态的条目不随批入档、不进一次性告警名录。
        open_ids = _open_ids_for_archive(root, item_ids)
        first_expire = bool(open_ids) and not _has_expired_archive(root, open_ids)
        if open_ids:
            # 告警写盘失败不得劫持降级收尾（code-review item ff69fd3d36ec，同
            # 下方 _write_defer_expired_alert 手法）：触顶告警经 AdminStore
            # 落盘，OSError 上抛会跳过紧随的 cleanup 与台账移除。
            try:
                record_failed_batch(
                    root, open_ids, wt,
                    reason="wip_gate_blocked_expired", branch=branch, tip_sha=tip_sha,
                    logger=self._logger,
                )
            except Exception as e:  # noqa: BLE001 — 入档/告警写盘失败只留痕
                self._log(
                    "warning",
                    f"code-fix defer 降级入档案/告警写盘异常（收尾不受影响）: {e}",
                )
        _safe_cleanup(wm, wt, success=False, logger=self._logger)
        _remove_deferred_batch(root, item_ids)
        if first_expire:
            # 告警写盘失败不得劫持降级收尾（code-review item 2ab1bb5633f0，
            # 同 _defer_merge_back 手法）：紧随的 write_progress 尚未执行。
            try:
                _write_defer_expired_alert(
                    root, open_ids, overlap, branch, tip_sha, logger=self._logger
                )
            except Exception as e:  # noqa: BLE001 — 告警失败只留痕
                self._log(
                    "warning",
                    f"code-fix defer 降级告警写盘异常（降级收尾不受影响）: {e}",
                )
        write_progress(
            root,
            reason="wip_gate_blocked_expired",
            current=f"延迟批合回超预算已入失败档案（branch={branch}）",
        )
        self._log(
            "warning",
            f"code-fix 延迟批合回超预算（90 分钟或 {DEFER_RETRY_MAX} 次重试），"
            f"降级入失败档案: branch={branch}",
        )

    def _defer_merge_back(
        self, wm, wt: Path, ctx: dict, merge_info, fixed_ids: list, pending_ids: list
    ) -> str:
        """批收尾 wip_gate_blocked 收尾（defer 路径，D1/D3）：保留现场 + 记
        台账 + 放锁 + 首次 info 告警。返回 "consumed"（链继续后续批）。

        保留：worktree 目录/分支/``_active_worktrees`` 在册（sweeper 扫孤儿
        跳过在册目录；重试收尾 ``wm.cleanup`` 语义不变）。放锁 MUST：``create()``
        对同键命中即返回 None、批 worker 对 None 走 halt 终止链——不放锁则
        defer 后下一批建树必败，整条车道在主树脏期间死锁（比现状更糟）。
        """
        root = self.project_root
        batch_no = ctx["batch_no"]
        overlap = list(getattr(merge_info, "wip_overlap", []) or [])
        tip_sha = _worktree_head(wt)
        branch = _worktree_branch(wt)
        # 台账先落（磁盘真相源），随后放锁/告警/进度。
        deferred_entry = record_deferred_batch(
            root, pending_ids, fixed_ids, wt,
            branch=branch, tip_sha=tip_sha, last_overlap=overlap,
        )
        try:
            wm.release_spec_lock("code-review-fix", "code-fix")
        except Exception as e:  # noqa: BLE001 — 放锁失败不影响 defer 记账，
            # 但车道可能死锁，必须留痕供排查。
            self._log("warning", f"code-fix defer 放锁异常（车道可能死锁）: {e}")
        # 首次 defer 即发 info 提示（1.3）：含交集文件清单与人工处置话术。
        # 告警写盘失败不得沿批 worker 兜底路径炸掉 defer 保留现场——台账刚
        # 登记保留、锁已放，异常上穿会触发 _safe_cleanup(success=False) 物理清
        # 掉刚保留的 worktree（条目变死条目，下轮 reclaim 重选重跑白丢一批）。
        try:
            _write_defer_info_alert(
                root, pending_ids, overlap, branch=branch, logger=self._logger
            )
        except Exception as e:  # noqa: BLE001 — 告警写盘失败不影响 defer 保留，
            # 只留痕供排查（后续轮询/升级路径仍可再发告警）。
            self._log(
                "warning",
                f"code-fix defer info 告警写盘异常（保留现场不受影响）: {e}",
            )
        # 占用者协调（add-mergeback-wip-active-coordination 1.1/2.1/2.2）：
        # 首次被挡即识别留痕 + 持有者订阅/无主宽限计时（识别与订阅挂在 defer
        # 消费路径上，design D5）；识别摘要并入进度 current。
        owner_note = self._coordinate_blocked_merge(
            deferred_entry, pending_ids, overlap, branch, tip_sha
        )
        current_txt = (
            f"第 {batch_no} 批合回待重试（主树未提交改动："
            f"{_fmt_overlap(overlap)}）— 已保留，主树清理后自动合回"
        )
        if owner_note:
            current_txt = f"{current_txt}；{owner_note}"
        # 进度写盘与上方告警同款兜底：异常上穿会沿批 worker 兜底路径触发
        # _safe_cleanup(success=False) 物理清掉刚保留的 worktree（台账已登记、
        # 锁已放），defer 保留现场丢失。
        try:
            write_progress(
                root,
                phase="merging",
                reason="wip_gate_blocked",
                current=current_txt,
                # 批上下文三键清除：agent run 已结束，保留现场由台账承载（防读
                # 侧按陈旧 run_id 合成条级进度，D2 同款防陈旧索引）。
                worktree=None,
                run_id=None,
                batch_total=None,
            )
        except Exception as e:  # noqa: BLE001 — 进度写盘失败不影响 defer 保留，
            # 只留痕供排查（defer 消费路径轮询会刷新进度）。
            self._log(
                "warning",
                f"code-fix defer 进度写盘异常（保留现场不受影响）: {e}",
            )
        self._log(
            "warning",
            f"code-fix 第 {batch_no} 批合回被主树未提交改动挡住"
            f"（重叠 {_fmt_overlap(overlap)}），批保留待自动合回"
            f"（不烧失败预算）: branch={branch}",
        )
        return "consumed"

    def _salvage_stranded_batch(self, wt, batch_no: int, run_id: str) -> bool:
        """搁浅批 salvage 兜底（add-codefix-commit-first-contract 2.1）。

        调用前提（三元组前两元已由调用方判定）：产物行存在 ``fixed``、分支
        相对建树点零提交。此处只补第三元：``git status --porcelain`` 非空 →
        把未提交改动自动提交到批分支（D3 message 约定：可追溯、与 agent 正常
        commit 显式区分），warning 日志 + 进度 current 留痕，返回 True——调用方
        重算提交数后继续既有合回裁决路径。porcelain 为空（真零改动，声明与
        事实不符）或提交失败返回 False，维持既有 ``no_effective_fix`` 拒合回
        语义，MUST NOT 空提交凑数（D4）。
        """
        if not _worktree_porcelain(wt).strip():
            return False
        message = f"orchestrator-salvage: batch {batch_no} run {run_id}"
        if not _salvage_commit(wt, message):
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批 salvage 兜底提交失败，按零有效修复拒合回处理",
            )
            return False
        self._log(
            "warning",
            f"code-fix 第 {batch_no} 批检测到搁浅（产物声明 fixed 但分支零提交、"
            f"worktree 有未提交改动），已 salvage 兜底提交：{message}",
        )
        write_progress(
            self.project_root,
            reason="",
            current=(
                f"第 {batch_no} 批搁浅兜底：分支零提交但工作区有未提交改动，"
                f"编排已 salvage 提交（{message}）"
            ),
        )
        return True

    def _salvage_api_timeout_wip(self, wt, result, batch_no: int) -> bool:
        """api_timeout 终局失败的 WIP 即时 salvage（evo-code-fix-api-timeout-salvage 2.1）。

        救回前移到失败当时（design D2），而非坐等陈旧清扫期的悬空 Pre-rmtree
        快照。仅 api_timeout 签名（车道层只读 run 信封布尔标记，判别单源在
        runner 层，design D1）且工作区脏（``git status --porcelain`` 非空）时
        以 ``_salvage_commit`` 提交到批分支；工作区干净跳过（Requirement 4）、
        提交失败 fail-open——一律返回 False，调用方照常 _safe_cleanup 并按
        现状失败收尾（不改变跳批推进），MUST NOT 空提交凑数（与
        ``_salvage_stranded_batch`` D4 同口径）。
        """
        if not getattr(result, "api_timeout", False):
            return False
        if not _worktree_porcelain(wt).strip():
            self._log(
                "info",
                f"code-fix 第 {batch_no} 批 api_timeout 终局但工作区干净，"
                f"跳过 salvage 按现状清理（run {result.run_id}）",
            )
            return False
        message = f"api-timeout-salvage: batch {batch_no} run {result.run_id}"
        if not _salvage_commit(wt, message):
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批 api_timeout salvage 提交失败，"
                f"按现状失败收尾（fail-open，run {result.run_id}）",
            )
            return False
        self._log(
            "warning",
            f"code-fix 第 {batch_no} 批 api_timeout 终局，未提交现场已 salvage "
            f"提交到批分支（cleanup 登记 recovery legacy 保全、下批认领继承）: "
            f"{message}",
        )
        return True

    def _mark_salvage_reusable(self, wm) -> bool:
        """给刚登记的 salvage legacy 补 reuse 标记（evo-code-fix-api-timeout-salvage 2.1）。

        调用前提：``_safe_cleanup(success=False)`` 已对非 verify- 前缀分支登记
        recovery legacy（lifecycle.py 既有语义）。对批建树既有 spec_name
        "code-review-fix"（``_run_batch_inner`` 的 ``wm.create`` 建树调用点）
        置 reuse，下一批 ``wm.create`` 经既有认领通路
        （``_take_reusable_worktree``）继承 salvaged 分支；无在册 legacy
        （cleanup 未登记）/标记失败只留 WARNING 不阻断（fail-open，下批按
        全新建树接续）。MUST NOT 调 ``consume_legacy``（回收端，删分支）。
        """
        marker = getattr(wm, "mark_legacy_reusable", None)
        if marker is None:
            return False
        try:
            marked = bool(marker("code-review-fix"))
        except Exception as e:  # noqa: BLE001 — 标记失败不改变失败收尾
            self._log("warning", f"code-fix salvage legacy reuse 标记异常（fail-open）: {e}")
            return False
        if not marked:
            self._log(
                "warning",
                "code-fix salvage 后无在册 legacy 可置 reuse"
                "（cleanup 未登记），下一批按全新建树接续",
            )
        return marked

    def _salvage_merge_back_conflict(
        self, wm, wt: Path, ctx: dict, orig_info,
        eff_spec: RegressionSpec, targets, fixed_ids: list, pending_ids: list,
        created_sha: str,
    ):
        """合回真冲突的定向救回（evo-add-codefix-mergeback-conflict-salvage 1.1/1.3）。

        调用前提：``merge_back`` 已返回真冲突（``conflict_paths`` 非空且
        ``wip_gate_blocked=False``——WIP 预检阻断走既有 defer，不进本方法）。
        救回发生在 ``_safe_cleanup`` 之前（批分支引用全程可用，design D4：
        现场即弃后分支即被删，救回 MUST 单轮闭环）；至多一次 rebase 救回，
        失败降级 commit 组粒度回收（``_salvage_cherry_pick_recover``）。

        返回 ``(merge_info, fixed_ids)``：
        - 救回合回成功（整批救回/部分回收）→ ``success=True``；部分回收时
          ``fixed_ids`` 收窄为可归属到回收集的条目（随调用方成功核销路径出账；
          仍冲突/无法归属条目已在回收阶段入失败档案）；
        - 救回重走合回命中 ``wip_gate_blocked`` → 原样透传：调用方按既有 defer
          零预算路径处理，不计救回失败、不触发组粒度回收；
        - 其余失败 → 批分支已还原（rebase abort / checkout 回批分支），调用方
          走既有整批入档案兜底（行为与现状兼容）。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        branch0 = _worktree_branch(wt)
        tip0 = _worktree_head(wt)
        commits = _salvage_batch_commits(wt, created_sha)
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批合回冲突救回开始：branch={branch0} "
            f"tip={tip0[:12]} commits={len(commits)}",
        )
        try:
            base = resolve_base_branch(root)
            rb = _git_try(wt, ["rebase", base], timeout=300)
            if rb is not None and rb.returncode == 0:
                self._log(
                    "info",
                    f"code-fix 第 {batch_no} 批救回 rebase 到基线 {base} 成功，重跑批回归",
                )
                write_progress(
                    root, phase="regressing", reason="",
                    current=f"第 {batch_no} 批合回冲突救回中（rebase 后重跑回归）",
                )
                with _with_test_targets_env(targets):
                    reg = runner.run_regression(
                        eff_spec, reason="code-fix", project_root=wt, lock_root=root
                    )
                if getattr(reg, "status", "") == "passed":
                    self._log("info", f"code-fix 第 {batch_no} 批救回回归通过，重走合回")
                    info = wm.merge_back(wt)
                    if getattr(info, "success", False):
                        self._log(
                            "info",
                            f"code-fix 第 {batch_no} 批合回冲突救回终局：整批救回"
                            f"（rebase 后合回成功，resolved 候选 {len(fixed_ids)} 条）",
                        )
                        return info, list(fixed_ids)
                    if bool(getattr(info, "wip_gate_blocked", False)):
                        # defer 零预算（task 1.3）：WIP 预检是可等待自愈的暂态，
                        # 不计救回失败、不触发组粒度回收，交既有 defer 通路。
                        self._log(
                            "warning",
                            f"code-fix 第 {batch_no} 批合回冲突救回终局：救回合回被"
                            "主树 WIP 预检阻断，转 defer 零预算（不计救回失败）",
                        )
                        return info, list(fixed_ids)
                    self._log(
                        "warning",
                        f"code-fix 第 {batch_no} 批救回合回仍冲突，"
                        "降级 commit 组粒度回收",
                    )
                else:
                    self._log(
                        "warning",
                        f"code-fix 第 {batch_no} 批救回回归未通过"
                        f"（{getattr(reg, 'status', '')}），降级 commit 组粒度回收",
                    )
            else:
                _git_try(wt, ["rebase", "--abort"], timeout=60)
                why = (
                    "git 不可用" if rb is None
                    else ((rb.stderr or rb.stdout or "rebase 冲突").strip()[:200])
                )
                self._log(
                    "warning",
                    f"code-fix 第 {batch_no} 批救回 rebase 失败（{why}），"
                    "已 abort 还原批分支，降级 commit 组粒度回收",
                )
            # 阶段二：commit（组）粒度回收（2.1）
            return self._salvage_cherry_pick_recover(
                wm, wt, ctx, orig_info, base=base, commits=commits,
                eff_spec=eff_spec, targets=targets,
                fixed_ids=fixed_ids, pending_ids=pending_ids,
                branch0=branch0, tip0=tip0,
            )
        except Exception as e:  # noqa: BLE001 — 救回自身异常 MUST NOT 劫持既有
            # 整批入档案兜底（与 defer 收尾同款兜底手法）：尽力还原现场后按
            # 现状收尾，异常细节留日志。
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批合回冲突救回终局：救回异常（{e}），"
                "整批入档案兜底（现状口径）",
            )
            _salvage_restore_branch(wt, branch0)
            return orig_info, list(fixed_ids)

    def _salvage_give_up(self, wt, ctx: dict, orig_info, fixed_ids: list,
                         branch0: str, why: str, carrier: str = ""):
        """组粒度回收放弃收口：还原批分支 + 终局单行汇总，回落整批入档案兜底。

        返回 ``(orig_info, fixed_ids)``（调用方既有兜底路径按现状收尾）。"""
        self._log(
            "warning",
            f"code-fix 第 {ctx['batch_no']} 批合回冲突救回终局：兜底全弃"
            f"（{why}）——整批入档案（现状口径）",
        )
        _salvage_restore_branch(wt, branch0)
        if carrier:
            # 未合并的承载分支 best-effort 删除（其提交均来自批分支，无信息损失）
            _git_try(wt, ["branch", "-D", carrier], timeout=30)
        return orig_info, list(fixed_ids)

    def _salvage_cherry_pick_recover(
        self, wm, wt: Path, ctx: dict, orig_info, base: str, commits: list,
        eff_spec: RegressionSpec, targets, fixed_ids: list, pending_ids: list,
        branch0: str, tip0: str,
    ):
        """救回阶段二：commit（组）粒度回收（evo-add-codefix-mergeback-conflict-salvage 2.1）。

        从当前基线新建承载分支，按「提交是否触碰冲突文件」（冲突集来自
        ``wm.rehearsal_conflict_paths`` 只读预演，task 1.2）逐组 cherry-pick
        回收；回收集重跑批回归（与 ``_run_batch_created`` 首轮回归调用同参）
        通过后经 ``merge_back_from_branch`` 重走合回。条目归属以提交 body 的
        ``items:`` 清单解析为准：可归属到回收集的条目随调用方成功核销路径
        resolved；仍冲突提交对应条目与「无法归属到非冲突组的剩余未出账条目」
        （旧契约批解析不出清单）保守整体入失败档案计 fail_count（与现状整批
        入档同口径，不做无据归属）。

        返回形态同 ``_salvage_merge_back_conflict``。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]

        def _give_up(why: str, carrier: str = ""):
            return self._salvage_give_up(
                wt, ctx, orig_info, fixed_ids, branch0, why, carrier=carrier,
            )

        conflict_paths: list = []
        query = getattr(wm, "rehearsal_conflict_paths", None)
        probe_branch = _worktree_branch(wt) or branch0
        if callable(query):
            try:
                conflict_paths = list(query(probe_branch) or [])
            except Exception:  # noqa: BLE001 — 查询失败按不可得保守处理
                conflict_paths = []
        if not commits:
            return _give_up("批提交清单不可得")
        if not conflict_paths:
            return _give_up("冲突文件集不可得（无法判定提交可回收性）")
        cp_set = set(conflict_paths)
        # still 列表已删（code-review item 6e9772d3f9ae）：只写不读的死变量，
        # 仍冲突提交的出账实际走下方「pending_ids 中未被 recovered_ids 覆盖
        # 者整体入失败档案」的保守口径，与逐提交记录无关。
        recoverable: list = []
        for sha in commits:
            paths = _commit_changed_paths(wt, sha)
            if paths is None or (set(paths) & cp_set):
                # 仍触碰冲突文件/变更集不可得：该提交组不入回收集。
                continue
            recoverable.append(sha)
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批组粒度回收：冲突文件 {len(cp_set)} 个，"
            f"可回收 {len(recoverable)}/{len(commits)} 组",
        )
        if not recoverable:
            return _give_up("无可回收提交组")
        carrier = f"{branch0}-salvage-{int(time.time())}"
        co = _git_try(wt, ["checkout", "-b", carrier, base], timeout=60)
        if co is None or co.returncode != 0:
            return _give_up(
                "承载分支建树失败（"
                + ("" if co is None else (co.stderr or "").strip()[:120]) + ")"
            )
        picked: list = []
        for sha in recoverable:
            cp = _git_try(wt, ["cherry-pick", sha], timeout=120)
            if cp is not None and cp.returncode == 0:
                picked.append(sha)
                continue
            # 单组冲突：--skip 跳过失败组继续回收后续组（保留已回收前缀）；
            # skip 失败则 abort 放弃回收（整批兜底）。
            skip = _git_try(wt, ["cherry-pick", "--skip"], timeout=120)
            if skip is None or skip.returncode != 0:
                return _give_up(
                    f"cherry-pick 冲突且跳过失败（{(cp.stderr or '').strip()[:120] if cp else 'git 不可用'}）",
                    carrier=carrier,
                )
        if not picked:
            return _give_up("零提交组被回收", carrier=carrier)
        write_progress(
            root, phase="regressing", reason="",
            current=f"第 {batch_no} 批合回冲突救回中（组粒度回收集回归，"
                    f"回收 {len(picked)}/{len(commits)} 组）",
        )
        with _with_test_targets_env(targets):
            reg = runner.run_regression(
                eff_spec, reason="code-fix", project_root=wt, lock_root=root
            )
        if getattr(reg, "status", "") != "passed":
            return _give_up(
                f"回收集二次回归未通过（{getattr(reg, 'status', '')}）",
                carrier=carrier,
            )
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批回收集回归通过，承载分支 {carrier} 重走合回",
        )
        info = wm.merge_back_from_branch(carrier)
        if not getattr(info, "success", False):
            return _give_up(
                "承载分支合回未成功（"
                + str(getattr(info, "error", ""))[:120] + "）",
                carrier=carrier,
            )
        # 条目归属与出账（2.1）：归属以提交 body 的 items: 清单解析为准。
        fixed_set = {str(i) for i in fixed_ids}
        recovered_ids: list = []
        for sha in picked:
            ids = _commit_item_ids(wt, sha)
            if not ids:
                continue  # 旧契约提交：无法归属（保守兜底，不做无据出账）
            for iid in ids:
                if str(iid) in fixed_set and str(iid) not in recovered_ids:
                    recovered_ids.append(str(iid))
        accounted = set(recovered_ids)
        archive_ids = [str(i) for i in pending_ids if str(i) not in accounted]
        archived = 0
        if archive_ids:
            # 失败档案只收未终态条目（与主路径入档同口径）；含仍冲突组条目
            # 与旧契约批无法归属条目（保守整批口径）。
            open_ids = _open_ids_for_archive(root, archive_ids)
            if open_ids:
                # 告警写盘失败不得劫持救回收尾（code-review item ff69fd3d36ec）：
                # 异常上穿会经批 worker 兜底把「部分回收成功核销」翻成 halt。
                try:
                    record_failed_batch(
                        root, open_ids, wt,
                        reason="merge_back_conflict",
                        branch=branch0, tip_sha=_branch_head(wt, branch0) or tip0,
                        logger=self._logger,
                    )
                    archived = len(open_ids)
                except Exception as e:  # noqa: BLE001 — 入档/告警写盘失败只留痕
                    self._log(
                        "warning",
                        f"code-fix 救回兜底入档案/告警写盘异常"
                        f"（收尾不受影响）: {e}",
                    )
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批合回冲突救回终局：部分回收"
            f"（回收 {len(picked)}/{len(commits)} 组，resolved 候选 "
            f"{len(recovered_ids)} 条，兜底入档案 {archived} 条）",
        )
        return info, recovered_ids

    def _run_batch(self, ctx: dict) -> None:
        batch_no = ctx["batch_no"]
        outcome = "halt"
        try:
            outcome = self._run_batch_inner(ctx)
        except Exception as e:  # noqa: BLE001 — 批异常兜底：不炸线程池/不挂死单飞
            self._log("error", f"批 worker 异常（第 {batch_no} 批）: {e}")
            self._finish("failed", reason=f"batch_worker_error: {e}")
            outcome = "halt"
        finally:
            self._in_flight = False
        # 自驱动链（selfheal D1/D4）：success 与 consumed 均推进下一批——
        # consumed 批的条目已全部离开可选池（失败档案 ∪ chain_skipped），
        # 可选池严格单调缩小，再投递循环必然收敛；原「失败即终止」的无限
        # 递归/空转顾虑只对「条目未离开可选池的失败」（halt：如
        # worktree_create_failed 每轮复现同批）成立，halt 保持终止链、条目
        # 保持 open，由下一轮 full scan 兜底重试。
        if outcome in ("success", "consumed"):
            self._resubmit()

    def _run_batch_inner(self, ctx: dict) -> str:
        """执行一批；返回三态收尾（selfheal D1）。

        ``"success"`` 批成功合回并核销；``"consumed"`` 该批条目已全部离开
        可选池（可推进下一批）；``"halt"`` 环境性失败（链终止，条目保持 open）。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        items = ctx["items"]

        # 建树（5.4）：create() 返回 None 即收尾——不派 run、不合回、条目保持
        # open、复位单飞，进度 failed（halt：下一轮 full scan 重试）。
        wm = getattr(runner, "worktree_manager", None)
        if wm is None:
            self._finish("failed", reason="worktree_manager_missing")
            return "halt"
        wt = wm.create(spec_name="code-review-fix", agent_type="code-fix")
        if wt is None:
            self._log("warning", "code-fix: worktree 创建失败（锁占用或 git 失败）")
            self._finish("failed", reason="worktree_create_failed")
            return "halt"
        wt = Path(wt)
        # 批上下文落盘（task 2.1）：phase="fixing" 写点整体后移至建树成功
        # 之后、agent run 启动之前——原写点位于建树前，彼时 worktree/run_id
        # 均不存在。run_id 由编排器预生成（_preset_run_id，code-fix- 前缀 +
        # 同口径去重）并经 run_code_fix 既有 run_id 形参传入（缺省在其内部
        # 生成、run 返回前编排器无从得知），保证 run 在飞期间进度文件已可
        # 解析（读侧定位 out 文件实时合成条级进度）。
        # 三条前置语句（code-review item cc79d58138f1）：_preset_run_id /
        # write_progress（_atomic_write 盘写）/ _worktree_head 均可能抛异常
        # （OSError/ImportError 等），MUST 位于 try 内——否则异常绕过
        # _safe_cleanup，create() 已登记的 code-review-fix:code-fix spec 锁
        # 永久滞留（后续 create() 恒 None，车道死锁）。
        try:
            run_id = _preset_run_id(runner)
            write_progress(
                root,
                phase="fixing",
                current=f"第 {batch_no} 批修复中（{len(items)} 条）",
                worktree=str(wt),
                run_id=run_id,
                batch_total=len(items),
                # 链级 run 清单逐 run 追加（2.2）：进度文件 run_id 字段批收尾
                # 即清除、不能充当链内 run 事实源，清单随链状态持久累积。
                chain_run_ids=[*(ctx.get("chain_run_ids") or []), run_id],
            )
            created_sha = _worktree_head(wt)
            return self._run_batch_created(wm, wt, created_sha, ctx, run_id=run_id)
        except Exception:
            # 未预期异常兜底（ocr 收尾审查）：create() 已登记 code-review-fix:code-fix
            # spec 锁，仅 cleanup() 释放——漏掉则下一批 create() 恒 None（车道死锁）。
            # 枚举失败分支各自已按语义 cleanup，不经此路径。
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            raise

    # [fenix-ignore:5afcd68672ca] 各失败收尾点的顺序约定各不相同（档案入档先于 cleanup、salvage reuse 标记夹在 cleanup 与进度写点之间、连接冷却在进度之后）且多处正确性由历史补丁注释锚定，不存在可纯机械抽取的统一「三元组」形态；部分抽取只覆盖少数干净分支、漂移面反而扩大，修复风险大于收益。
    def _run_batch_created(self, wm, wt: Path, created_sha, ctx: dict, run_id: str) -> str:
        """执行已建树批次的主体（首次/重试 run、回归、守卫、合回核销清理）。

        返回三态收尾（selfheal D1，语义见 ``_run_batch_inner``）。由
        _run_batch_inner 在建树成功后调用；未预期异常在本层被兜底 cleanup 后
        原样上抛（_run_batch 收口）。``run_id`` 为编排器预生成的首轮 run 标识
        （进度文件已携带同值）。
        """
        root = self.project_root
        runner = self._agent_runner
        batch_no = ctx["batch_no"]
        items = ctx["items"]
        item_ids = ctx["item_ids"]
        total = ctx["total"]
        done = ctx["done"]
        reg_spec = ctx["regression_spec"]
        # 链级 run 清单本地跟踪（2.2）：批上下文基线 + 本批首轮 run_id；
        # 定向重试轮逐轮续加并随各写点持久化（链级事实源，rollup 汇总用）。
        chain_runs = [*(ctx.get("chain_run_ids") or []), run_id]

        # 第一次修复 run（run_id 预生成传入，与进度文件 run_id 一致）
        result = runner.run_code_fix(wt, items, run_id=run_id)
        if not result.success:
            self._log("error", f"code-fix run 失败（run {result.run_id}）: {result.error}")
            # evo-code-fix-api-timeout-salvage 2.1：api_timeout 终局且工作区脏时
            # 先把 WIP salvage 提交到批分支，再照常 _safe_cleanup——MUST NOT 跳过
            # cleanup（漏掉则 code-review-fix:code-fix spec 锁滞留，下一批 create()
            # 恒 None 车道死锁，见 _run_batch_inner 既有警告）；salvage 未命中或
            # 提交失败 fail-open 按现状失败收尾（2.3：非 api_timeout 行为不变）。
            salvaged = self._salvage_api_timeout_wip(wt, result, batch_no=batch_no)
            # agent run 失败（瞬态，selfheal D3）：不合回不核销；条目入
            # chain_skipped（链内跳过，不烧跨轮预算）；清理 worktree 释放
            # spec 锁（否则下一批 create() 恒 None，车道死锁）；consumed：
            # 链继续推进下一批。cleanup success=False 对非 verify- 前缀分支
            # 自动登记 recovery legacy（lifecycle.py 既有语义，宽限期内豁免
            # 陈旧清扫）——salvaged 现场由 legacy 机制保全而非物理清理。
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            if salvaged:
                # 补 reuse 标记（register_legacy 自身不置 reuse）：下一批
                # wm.create 经既有认领通路 _take_reusable_worktree 继承 salvaged
                # 分支（2.2，认领端零新增）；MUST NOT 走 consume_legacy——其
                # 语义是后继成功 merge 后回收（会删分支，复刻悬空 commit 净损失）。
                self._mark_salvage_reusable(wm)
            self._consumed_progress(
                current=f"第 {batch_no} 批失败已跳过（run 失败）— 继续后续批次",
                reason=f"agent_run_failed: {result.error}"[:500],
                chain_skip_ids=item_ids,
            )
            # evo-add-codefix-conn-error-cooldown 2.1：连接类失败置同链冷却
            # ——写持久化冷却态 + 触发告警（在 _consumed_progress 之后：冷却
            # 提示文案是收尾时刻的最终进度面）。consumed 记账语义不变（R2：
            # 仅推迟下一批投递）；紧随的 _resubmit → checkpoint 被冷却守卫
            # 拦下，实现「失败后零延迟重派改为冷却到期再投递」。getattr
            # 守护测试替身信封（SimpleNamespace）缺 conn_error 字段的形态。
            if getattr(result, "conn_error", False):
                self._arm_switch_cooldown(result)
            return "consumed"

        # 批收尾回归两段式分流（add-codefix-affinity-batching 3.4）：链末批
        # （核销前判定，3.1）恒全量；非末批按开关/占位符/映射三分支分流
        # （fail-open 回退全量——定向化是优化不是门槛）。severity 门限随
        # 选批同口径传入（evo-add-codefix-severity-batch-gate 2.1）：挂起
        # 条目不阻链末批判定、不计 skipped/lost。
        is_last_batch = is_chain_last_batch(
            root,
            item_ids,
            chain_skipped=ctx.get("chain_skipped"),
            severity_gate=self._severity_gate(),
        )
        eff_spec, targeted, targets = self._resolve_batch_regression_spec(
            reg_spec, wt, run_id, batch_no=batch_no, is_last_batch=is_last_batch
        )
        # 第一次回归（执行根=worktree、锁根=主树，D10）；定向与全量共用既有
        # run_regression（不新增执行通道），失败同走下方定向重试块（零新增
        # 处置分支）。
        attempt_run_ids: list[str] = []
        # 首轮回归 passed 的快路径不进下方定向重试块，retry_run_id 须预初始
        # 化为空串——批收尾 salvage 守卫按 ``retry_run_id or result.run_id``
        # 取提交归属 run：快路径回落首轮（裸引用在快路径抛 UnboundLocalError，
        # 批 worker 收尾整体中断，2026-09-25 验证打回实证）。
        retry_run_id = ""
        reg_mode = "定向回归" if targeted else "全量回归"
        # 中间阶段写点显式清 reason（code-review item 48ee3596117c）：合并写
        # 语义下 checkpoint 的 disabled 提示写点（reason="disabled"）会一直
        # 粘到批收尾，前端按 reason 分级渲染会把仍在推进的批误显示成终止态
        # ——与批收尾成功写点的 reason="" 同口径。
        write_progress(
            root,
            phase="regressing",
            reason="",
            current=f"第 {batch_no} 批{reg_mode}中（{len(items)} 条）",
        )
        # FENIX_TEST_TARGETS 双轨导出（3.3，{port} 先例）：仅回归窗口内设置，
        # 空目标零触碰（全量回归路径零环境变更）。
        with _with_test_targets_env(targets):
            reg = runner.run_regression(
                eff_spec, reason="code-fix", project_root=wt, lock_root=root
            )
        if reg.status != "passed":
            # 定向重试轮循环（add-codefix-targeted-retry 2.2，D4）：重试轮从
            # 「整批重做 + 全量回归」改为「定向修复（只修失败用例相关问题，
            # 可修测试本身）+ 失败用例子集回归」，上限 targeted_retry_max
            # （缺省 3）。首轮与重试轮复用既有 _preset_run_id/write_progress
            # 机制，进度 phase 沿用 retrying（轮次号入文案）。
            retry_max = self._targeted_retry_max()
            cumulative: list[dict] = []   # 轮间累计明细注入集（2.3）
            last_detail_ref = ""          # 最后一轮明细引用（入失败档案，4.4）
            exhausted = False
            # 回归异常熔断计数（add-codefix-parse-error-breaker 1.2/1.3）：
            # 同批连续异常计数，首轮与每个定向轮回归都进计数窗口；真实测试
            # 失败（有明细）清零不计数、回归 passed 天然离开循环；批 worker
            # 局部变量——跨批/跨链不累计（D4）。anomaly_rounds 留各异常轮的
            # status 与明细形态，供熔断 WARNING 日志呈现触发判据（2.1）。
            anomaly_streak = 0
            anomaly_rounds: list[str] = []
            breaker_triggered = False
            for attempt in range(1, retry_max + 1):
                # ① 失败明细提取 + 合并 + 落盘（1.1/1.2/2.3）：本轮注入的
                # reg 为上一轮回归结果；映射失败（非 pytest 形态、classname
                # 不足以唯一重构、无明细）→ fallback_full，重试侧回退全量
                # 重试（fail-closed）。文件名含该轮回归 run_id。
                fail_items, mapped, detail_rel, cumulative = _ingest_failure_round(
                    root, reg, cumulative, wt)
                if detail_rel:
                    last_detail_ref = detail_rel
                # 首轮回归计数（1.3）：此处 reg 即首轮回归、fail_items 即其
                # 提取明细，与定向轮同口径（1.2）。evo-codefix-zero-face-
                # regression-hardening 1.2：阈值按形态取值后，timeout 形态
                # 首轮单次计数即达阈值，须在此接同款短路判断——否则首轮全量
                # 回归即 timeout 零失败面（2026-10-08 批 1 实际形态）时仍会
                # 先派 1 个定向 run 并再烧一轮 1800s 全量回归才熔断，违背
                # 「首记即收口」。parse_error/failed 阈值 2 下首轮不可能达
                # 阈值，判断对它们是零开销直通。
                if attempt == 1:
                    if _is_regression_anomaly(reg, fail_items):
                        anomaly_streak += 1
                        anomaly_rounds.append(
                            _anomaly_round_form(reg, mapped, fail_items))
                    else:
                        anomaly_streak = 0
                        anomaly_rounds.clear()
                    if anomaly_streak >= _anomaly_breaker_threshold(
                            getattr(reg, "status", "")):
                        # 首记即收口：显式置位再 break（for-else 语义——
                        # break 跳过 else 分支，exhausted 不会自动置位，下方
                        # 耗尽收口块依赖它）。首轮命中 → 未派任何定向 run、
                        # 不再烧第二轮全量回归。
                        breaker_triggered = True
                        exhausted = True
                        self._log(
                            "warning",
                            f"code-fix 第 {batch_no} 批回归异常熔断触发"
                            f"（连续 {anomaly_streak} 次未产出可用失败明细："
                            f"{'；'.join(anomaly_rounds)}），首轮全量回归即收口"
                            f"（0/{retry_max} 轮定向重试，不再派发）",
                        )
                        break
                # ③ 定向轮 run_id 预生成 + 进度刷新（沿用 5.6 机制）：exclude
                # 排除首轮与本批此前各轮（同 worktree 内主树残留判据覆盖不到，
                # 同秒撞名会复用 out 文件）。
                retry_run_id = _preset_run_id(runner, exclude=(run_id, *attempt_run_ids))
                chain_runs.append(retry_run_id)
                write_progress(
                    root,
                    phase="retrying",
                    reason="",
                    current=(
                        f"第 {batch_no} 批定向重试 {attempt}/{retry_max}"
                        f"（失败 {len(cumulative)} 例"
                        + ("，子集回归）" if mapped else "，明细不可映射，全量回归）")
                    ),
                    run_id=retry_run_id,
                    chain_run_ids=list(chain_runs),
                )
                # ④ 派定向轮 run（同一 worktree）：prompt 注入累计失败明细
                # （2.3）+ 只修失败相关的硬指令；映射失败时注入旧式摘要。
                summary = (
                    _render_targeted_retry_brief(cumulative)
                    if mapped and cumulative
                    else _failure_summary(reg)
                )
                self._log(
                    "warning",
                    f"code-fix 第 {batch_no} 批回归未通过（{reg.status}），"
                    f"定向重试 {attempt}/{retry_max}"
                    + (f"（{len(fail_items)} 例子集）" if mapped else "（回退全量）"),
                )
                retry_result = runner.run_code_fix(
                    wt, items, failure_summary=summary, run_id=retry_run_id
                )
                if not retry_result.success:
                    self._log(
                        "error",
                        f"code-fix 重试 run 失败（run {retry_result.run_id}）: {retry_result.error}",
                    )
                    # run 失败（本轮回归根本没跑）≠ 回归均失败：不入失败
                    # 档案（不烧跨轮预算），与首次 run 失败同语义——条目入
                    # chain_skipped；清理 worktree 释放 spec 锁（否则
                    # code-review-fix:code-fix 被永久持有，下一批 create() 恒返回
                    # None，车道首批后即死）；consumed：链继续。
                    _safe_cleanup(wm, wt, success=False, logger=self._logger)
                    self._consumed_progress(
                        current=f"第 {batch_no} 批失败已跳过（重试 run 失败）— 继续后续批次",
                        reason=f"regression_retry_run_failed: {retry_result.error}"[:500],
                        chain_skip_ids=item_ids,
                    )
                    return "consumed"
                attempt_run_ids.append(retry_result.run_id)
                # ⑤ 回归：映射成功 → 只重跑失败子集（2.1，范围=本轮失败集，
                # 非累计集——上一轮已通过的用例不重跑）；映射失败 → 全量
                # （fail-closed 到现状语义）。
                write_progress(
                    root,
                    phase="regressing",
                    reason="",
                    current=(
                        f"第 {batch_no} 批定向轮 {attempt} 回归中"
                        + (f"（子集 {len(fail_items)} 例）" if mapped else "（全量）")
                    ),
                )
                # 回退路径消毒（add-codefix-test-targets-fallback-sanitization）：
                # 重试轮两态（mapped 真假）原共用 ctx 原件 reg_spec，占位符
                # 在参数位时字面透传必挂——统一改用消毒副本（无占位符零
                # 迁移）。FENIX_TEST_TARGETS 窗口只在 mapped 态进入：env 形态
                # cmd 的实际收集通道就是该变量，mapped=False 声明全量重试时
                # 仍导出首轮映射的陈旧 targets 会把收集面静默收窄成子集、
                # 不可映射的失败用例未复跑即合回（code-review item
                # 5f88b3b78f7c）。mapped 态子集语义不变：subset_nodeids 由
                # 门面按消毒后 cmd 的既有收集目标替换（消毒后 tests/ 成为
                # 可替换目标），targets 保持同值双轨。
                with _with_test_targets_env(targets if mapped else []):
                    reg = runner.run_regression(
                        _sanitize_test_targets(reg_spec),
                        reason="code-fix", project_root=wt, lock_root=root,
                        subset_nodeids=[i["nodeid"] for i in fail_items] if mapped else None,
                    )
                if reg.status == "passed":
                    break
                # 定向轮回归计数（1.3，passed-break 的对偶位置）：本轮明细
                # 尚未进 ① 的提取点（那是在为下一轮注入准备本轮之前的明细），
                # 按本轮 snapshot 现提取，与首轮计数同口径（1.2）。
                round_items, round_mapped = _map_junit_failures_to_nodeids(
                    # 同经归一入口（fix-codefix-mapping-dotted-file-poison
                    # 1.2）：点分 file 兜底不毒化熔断计数口径——真实失败
                    # （有明细）MUST NOT 被误计 anomaly。
                    _snapshot_failures_for_mapping(
                        (getattr(reg, "snapshot", None) or {}).get("failures") or []),
                    exec_root=wt)
                if _is_regression_anomaly(reg, round_items):
                    anomaly_streak += 1
                    anomaly_rounds.append(
                        _anomaly_round_form(reg, round_mapped, round_items))
                    # 阈值按形态取值（evo-codefix-zero-face-regression-
                    # hardening 1.2）：timeout 首记即收口（1），其余维持 2。
                    if anomaly_streak >= _anomaly_breaker_threshold(
                            getattr(reg, "status", "")):
                        # 熔断（add-codefix-parse-error-breaker 2.1）：不再
                        # 派发下一轮定向 run 与全量回归，以 exhausted 等价
                        # 状态进入既有现场即弃收口块（入档/清理/告警零分叉
                        # 复用）。WARNING 含各异常轮 status 与明细形态。
                        breaker_triggered = True
                        exhausted = True
                        self._log(
                            "warning",
                            f"code-fix 第 {batch_no} 批回归异常熔断触发"
                            f"（连续 {anomaly_streak} 次未产出可用失败明细："
                            f"{'；'.join(anomaly_rounds)}），提前终止定向重试"
                            f"（已执行 {len(attempt_run_ids)}/{retry_max} 轮），"
                            "不再派发下一轮 run 与全量回归",
                        )
                        break
                else:
                    # 真实测试失败（有明细）不进熔断计数且清零（D1）——
                    # 「偶发一次异常后恢复正常」不应累积误杀。
                    anomaly_streak = 0
                    anomaly_rounds.clear()
            else:
                exhausted = True
            if exhausted:
                # 最后一轮（耗尽轮）的回归失败明细补落盘（1.1：每个定向轮
                # 回归非 passed 时各落一份——循环顶部的提取点覆盖不到它），
                # 随后该轮明细引用随现场即弃入失败档案。最终轮明细同时是
                # reg_form 判定源（零失败面=anomaly，有真实失败面=mapped）。
                final_fail_items, _, detail_rel, _ = _ingest_failure_round(
                    root, reg, cumulative, wt)
                if detail_rel:
                    last_detail_ref = detail_rel
                # 耗尽 targeted_retry_max 轮仍失败 → 现场即弃（selfheal D2
                # 语义逐字沿用）：cleanup **前**把 branch/tip_sha 连同 reason
                # 与最后一轮明细引用写入失败档案（fail_count 预算），随后清理
                # worktree 释放锁——不再保留现场待人工（锁死车道），丢弃的
                # 修复提交由下轮重试重新生成，tip_sha 留作 reflog 追溯。
                # consumed：条目已入档案（离开可选池），链继续推进下一批。
                self._log(
                    "error",
                    (
                        f"code-fix 第 {batch_no} 批回归异常熔断收口（连续 "
                        f"{anomaly_streak} 次未产出可用失败明细，实际执行 "
                        f"{len(attempt_run_ids)}/{retry_max} 轮定向重试）"
                        if breaker_triggered else
                        f"code-fix 第 {batch_no} 批定向重试 {retry_max} 轮耗尽仍失败"
                    )
                    + f"，现场即弃（branch/tip_sha/明细引用入档案，worktree 清理: {wt}）",
                )
                summary2 = _failure_summary(reg)
                tip_sha = _worktree_head(wt)
                branch = _worktree_branch(wt)
                # LLM 拒绝出口在耗尽路径同样生效（code-review item
                # 95a9442e0a55）：本路径提前 return，到不了下方合回路径的产物
                # 行分区/mark_ignored——入档前走与合回路径共用的
                # _apply_llm_reject_exits（首轮 + 各定向轮并集，同款分区），
                # 把 skipped 且标注误报/不值得修的条目先置 ignored 终态（链级
                # 核销计数同口径累加），再从入档集合排除——已终态条目 MUST
                # NOT 随批烧 fail_count 预算/进告警名录（与 merge_back_conflict
                # 路径 pending_ids 排除 ignored 的口径一致）。
                exhaust_ignored, exhaust_ignore_set, _ = _apply_llm_reject_exits(
                    root, wt, [result.run_id, *attempt_run_ids], item_ids
                )
                if exhaust_ignored:
                    self._chain_bump(root, chain_ignored=exhaust_ignored)
                archive_ids = [
                    iid for iid in item_ids if iid not in exhaust_ignore_set
                ]
                # 失败档案只收未终态条目（code-review item c94a1770a477，与
                # _downgrade_deferred / 主路径核销前过滤同口径）：选批到重试
                # 耗尽之间被人工置终态（resolved/in_spec/ignored）的条目不随
                # 批入档、不进回归失败告警名录——fail_count 预算与达上限一次
                # 性告警的名录须与真实失败条目一致；子集为空则跳过入档与告警。
                open_ids = _open_ids_for_archive(root, archive_ids)
                if open_ids:
                    # 告警写盘失败不得劫持 consumed 收尾（code-review item
                    # ff69fd3d36ec，同下方 write_regression_failed_alert 手法）：
                    # record_failed_batch 锁外的触顶/降档告警经 AdminStore 落盘，
                    # OSError 上抛会跳过紧随的 _consumed_progress——经批 worker
                    # 兜底把「链继续推进」改成 halt。
                    try:
                        record_failed_batch(
                            root, open_ids, wt,
                            # "regression_failed_twice" 是历史兼容名（定向重试上线前的
                            # 两次全量回归语义）：存量档案与告警检索依赖此标识，不改名；
                            # 熔断收口取新名 "regression_parse_error_breaker"
                            # （add-codefix-parse-error-breaker 2.2，消费侧无
                            # regression_failed_twice 全等匹配依赖，tasks 2.3 已核）。
                            reason=(
                                "regression_parse_error_breaker" if breaker_triggered
                                else "regression_failed_twice"
                            ), branch=branch, tip_sha=tip_sha,
                            detail_ref=last_detail_ref, logger=self._logger,
                            # 回归终局形态入档（evo-add-codefix-anomaly-redispatch-
                            # budget 1.1）：按最后一轮（耗尽轮）回归判定；重试收敛
                            # 事实快照（批 worker 局部计数的终值）随档留存供审计。
                            reg_form=(
                                REG_FORM_ANOMALY
                                if _is_regression_anomaly(reg, final_fail_items)
                                else REG_FORM_MAPPED
                            ),
                            reg_detail={
                                "anomaly_streak": anomaly_streak,
                                "retry_rounds": len(attempt_run_ids),
                                "breaker_triggered": breaker_triggered,
                            },
                        )
                    except Exception as e:  # noqa: BLE001 — 入档/告警写盘失败只留痕
                        self._log(
                            "warning",
                            f"code-fix 回归耗尽入档案/告警写盘异常"
                            f"（consumed 收尾不受影响）: {e}",
                        )
                    # 告警写盘失败不得劫持 consumed 收尾（code-review item
                    # 2ab1bb5633f0，同 _defer_merge_back 手法）：异常上穿会经
                    # 批 worker 兜底把「链继续推进」改成 halt，本轮剩余批次不跑。
                    try:
                        write_regression_failed_alert(
                            root, open_ids, wt, summary2,
                            branch=branch, tip_sha=tip_sha, logger=self._logger,
                            # 实际执行轮数（add-codefix-parse-error-breaker
                            # 2.3）：耗尽路径 = retry_max（行为不变）；熔断
                            # 路径 < retry_max，按实际执行轮数如实传入。
                            retry_rounds=len(attempt_run_ids),
                        )
                    except Exception as e:  # noqa: BLE001 — 告警失败只留痕
                        self._log(
                            "warning",
                            f"code-fix 回归失败告警写盘异常（收尾不受影响）: {e}",
                        )
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
                # 收口 reason 按熔断标志分流（add-codefix-parse-error-breaker
                # 2.2）：轮数耗尽路径 "regression_failed_twice: <status>" 逐字
                # 不变；熔断路径取 "regression_parse_error_breaker"。
                self._consumed_progress(
                    current=(
                        f"第 {batch_no} 批失败已跳过（"
                        + (
                            f"回归异常熔断（连续 {anomaly_streak} 次 "
                            "未产出可用失败明细）"
                            if breaker_triggered else
                            f"回归 {retry_max} 轮定向重试未通过"
                        )
                        + f"）— 继续后续批次"
                    ),
                    reason=(
                        "regression_parse_error_breaker" if breaker_triggered
                        else "regression_failed_twice"
                    ) + f": {reg.status}",
                )
                return "consumed"

        # 5.8 零有效修复守卫（合回之前）：产物行至少一条 fixed 且分支相对
        # 建树点有提交。merge_back 对「分支已是 HEAD 祖先」返回成功——无此
        # 守卫，全 skipped 的批会以「零改动合并成功 + 回归必过」白洗 resolved。
        # LLM 拒绝出口（2026-09-23）：skipped 且显式标注可忽略原因的条目在
        # 批收尾即置 ignored 终态（不等合回——ignored 与代码变更无关），从
        # 本批后续的失败档案/chain_skipped 集合中排除（已终态，MUST NOT 随批
        # 作废被重试重做）。产物行并集读取/分区/批界过滤/mark_ignored 走与
        # 定向重试耗尽收口共用的 _apply_llm_reject_exits（单源判定口径）。
        ignored, ignore_set, fixed_ids = _apply_llm_reject_exits(
            root, wt, [result.run_id, *attempt_run_ids], item_ids
        )
        # 链级核销计数累加（2.1）：以 mark_ignored 真实命中为准（条目计数与
        # 台账核销一致），rollup 时点读出。
        if ignored:
            self._chain_bump(root, chain_ignored=ignored)
        # 失败登记闭环核销（add-codefix-failure-registration-closeout 1.1）：
        # ignored 终态可能补齐某失败登记的全终态判定，核销点即时检查
        # （fail-open，不阻断批收尾主流程）。
        self._consume_failed_registrations(root)
        pending_ids = [iid for iid in item_ids if iid not in ignore_set]
        # 建树点瞬时失败兜底（code-review item e992bc1af898）：created_sha 为
        # 空串会使提交数判据恒按 0 处理（有效修复批被误判拒合回），先对
        # _worktree_head 做有限重试再判定。
        if not created_sha:
            for _ in range(2):
                time.sleep(0.5)
                created_sha = _worktree_head(wt)
                if created_sha:
                    break
        # 建树点重试耗尽仍为空串（code-review item b0c5cf011d29）：提交数判据
        # 同样不可得，按 None 归入下方 commits is None 的 halt 口径——「git
        # 判据不可得 ≠ 确认零提交」（同 item e992bc1af898 立论），按 0 计入
        # 零有效修复判定会把已提交修复的有效批误判拒合回、弃置成果（改动已
        # 全部提交时 salvage 不触发，整批有效修复被误判）。
        commits = _worktree_commit_count(wt, created_sha) if created_sha else None
        if commits is None:
            # git 判据不可用 ≠ 确认零提交（code-review item e992bc1af898）：
            # 按 no_effective_fix 链内跳过会弃置可能已提交的整批修复成果，
            # 改走 halt 终止链——下轮 full scan 重试同批（现场经
            # cleanup(success=False) 的 recovery legacy 保全）。
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批提交数判据不可用（git 失败），"
                "halt 待下轮 full scan 重试同批",
            )
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._finish("failed", reason="worktree_commit_count_unavailable")
            return "halt"
        if fixed_ids and commits <= 0 and self._salvage_stranded_batch(
            wt, batch_no=batch_no, run_id=retry_run_id or result.run_id
        ):
            # salvage 提交成功 → 分支已有提交，重算提交数后走既有合回裁决路径。
            # 回归已在上方针对 worktree 工作区（含这些未提交改动）执行过，
            # salvage 不改变回归门语义（不改回归门：spec Non-Goal）。
            commits = _worktree_commit_count(wt, created_sha) if created_sha else 1
            if commits is None:
                # salvage 已确认落了新提交，「分支相对建树点有提交」事实成立，
                # 复查瞬时失败不翻转该事实（按 ≥1 计）。
                commits = 1
        if not fixed_ids or commits <= 0:
            if not pending_ids:
                # 全批 skipped 均为可忽略原因：条目已尽置 ignored（终态）、
                # 无代码改动可合回——批按完成收尾（非失败，不烧重试预算）。
                _safe_cleanup(wm, wt, success=True, logger=self._logger)
                self._consumed_progress(
                    current=(
                        f"第 {batch_no} 批完成（误报/不值得修 {ignored} 条已忽略，"
                        f"无需合回）— 继续后续批次"
                    ),
                    reason="",
                )
                return "consumed"
            # 零有效修复拒合回（selfheal：链内跳过而非终止链）——零产物批按
            # halt 终止链，因选批 earliest-first 会永久堵在队列头，违背「单批
            # 失败不堵塞车道」目标；条目入 chain_skipped 随下一链重试（已置
            # ignored 的条目除外——已终态不重试）。
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批零有效修复（fixed={len(fixed_ids)}, "
                f"commits={commits}, ignored={ignored}），拒合回",
            )
            _safe_cleanup(wm, wt, success=False, logger=self._logger)
            self._consumed_progress(
                current=f"第 {batch_no} 批失败已跳过（无有效修复）— 继续后续批次",
                reason="no_effective_fix",
                chain_skip_ids=pending_ids,
            )
            return "consumed"

        # 合回（既有 merge-back 闸门不绕过）→ 核销 fixed 条目 → 清理 worktree
        write_progress(
            root,
            phase="merging",
            reason="",
            current=f"第 {batch_no} 批合回中（{len(items)} 条）",
        )
        merge_info = wm.merge_back(wt)
        if not getattr(merge_info, "success", False):
            # 合回失败分类（fix-codefix-wipgate-defer D1）：先读
            # wip_gate_blocked 标志分派（不解析 error 字符串——脆弱；getattr
            # 缺省 False 对旧类型对象容错）。True=主树 WIP overlap 预检阻断，
            # 可等待自愈的暂态，走 defer 路径零预算；False=真冲突，进入下方
            # 定向救回（救回失败仍保留既有「现场即弃」兜底语义）。
            if bool(getattr(merge_info, "wip_gate_blocked", False)):
                return self._defer_merge_back(
                    wm, wt, ctx, merge_info,
                    fixed_ids=fixed_ids, pending_ids=pending_ids,
                )
            # 合回冲突 → 定向救回（evo-add-codefix-mergeback-conflict-salvage
            # 1.1）：cleanup 前批分支引用全程可用，至多一次 rebase 救回 + 一轮
            # commit 组粒度回收。真冲突判据：``conflict_paths`` 非空（预演闸/
            # 真合并冲突均携带；无该字段的失败——锁/暂存等瞬态——不触发救回，
            # 维持现状语义）。返回 success=True 时落入下方成功核销路径（部分
            # 回收时 fixed_ids 已收窄为回收集条目）。
            if getattr(merge_info, "conflict_paths", None):
                merge_info, fixed_ids = self._salvage_merge_back_conflict(
                    wm, wt, ctx, merge_info,
                    eff_spec=eff_spec, targets=targets,
                    fixed_ids=fixed_ids, pending_ids=pending_ids,
                    created_sha=created_sha,
                )
                if not getattr(merge_info, "success", False):
                    if bool(getattr(merge_info, "wip_gate_blocked", False)):
                        # 救回重走合回命中 WIP 预检：既有 defer 零预算路径
                        # （不计救回失败，task 1.3）。
                        return self._defer_merge_back(
                            wm, wt, ctx, merge_info,
                            fixed_ids=fixed_ids, pending_ids=pending_ids,
                        )
            if not getattr(merge_info, "success", False):
                # 合回冲突（救回未成功）→ 现场即弃（selfheal D2）：cleanup 前把
                # branch/tip_sha 写入失败档案（fail_count 预算），随后清理
                # worktree 释放锁——不再保留现场待人工（原语义锁死车道至 daemon
                # 重启）。consumed：条目已入档案，链继续。
                self._log("error", f"code-fix 第 {batch_no} 批合回冲突，现场即弃（branch/tip_sha 入档案）")
                tip_sha = _worktree_head(wt)
                branch = _worktree_branch(wt)
                # 失败档案只收未终态条目（code-review item c94a1770a477，与
                # _downgrade_deferred / 定向重试耗尽 / 主路径核销前过滤同口径）：
                # 选批到合回之间被并发置 in_spec/resolved 的条目不随批入档——
                # fail_count 预算与达上限一次性告警的名录须与真实失败条目一致；
                # 子集为空则跳过入档（ignored 已在 pending_ids 构造处排除）。
                open_ids = _open_ids_for_archive(root, pending_ids)
                if open_ids:
                    # 告警写盘失败不得劫持 consumed 收尾（code-review item
                    # ff69fd3d36ec，同耗尽收口手法）：异常上穿会跳过紧随的
                    # _consumed_progress，经批 worker 兜底把「链继续推进」改成 halt。
                    try:
                        record_failed_batch(
                            root, open_ids, wt,
                            reason="merge_back_conflict", branch=branch, tip_sha=tip_sha,
                            logger=self._logger,
                        )
                    except Exception as e:  # noqa: BLE001 — 入档/告警写盘失败只留痕
                        self._log(
                            "warning",
                            f"code-fix 合回冲突入档案/告警写盘异常"
                            f"（consumed 收尾不受影响）: {e}",
                        )
                _safe_cleanup(wm, wt, success=False, logger=self._logger)
                self._consumed_progress(
                    current=f"第 {batch_no} 批失败已跳过（合回冲突）— 继续后续批次",
                    reason="merge_back_conflict",
                )
                return "consumed"
        # 核销前过滤（code-review item 65f65b784f2a，与 defer 路径同口径）：
        # mark_resolved 对命中 id 无条件置 resolved、无终态保护，核销方 MUST
        # 先以 read_items 过滤——选批到合回之间被并发置 in_spec/ignored 的条目
        # 跳过（不丢 spec_name 归属），agent 产物带出的批外 id 不核销不计进度。
        batch_set = set(item_ids)
        resolve_candidates = [i for i in fixed_ids if i in batch_set]
        # 台账读有限重试（code-review items 60fe0f4ddc90/6ffe17267ac5，与
        # defer 路径 _retry_one_deferred 同口径）：merge_back 成功后此刻瞬时
        # 读失败若按空集降级，会「已合回却不核销」且随即 cleanup(success=True)
        # 销毁 fixed_ids 对应产物——条目仍 open 会被下链重选，agent 在已含
        # 修复的新 HEAD 上多半零提交，跨链反复空转。短间隔重试 3 次；无候选
        # 核销条目时读结果对核销无影响，跳过重试直走零核销收尾。
        ledger = None
        if resolve_candidates:
            for attempt in range(3):
                try:
                    ledger = read_items(root)
                    break
                except Exception:  # noqa: BLE001 — 重试耗尽走「保留待下链」分支
                    if attempt < 2:
                        time.sleep(0.2 * (attempt + 1))
        if resolve_candidates and ledger is None:
            # 已合回但核销状态未知（与 defer 路径 ledger_read_failed 分支同
            # 款）：MUST NOT 此刻以 success 清理现场——比照 _defer_merge_back
            # 登记延迟台账 + 放锁后按 consumed 收尾，条目随 _deferred_item_ids
            # 退出选批池，下一链边界 _retry_one_deferred 重试核销（merge_back
            # 幂等：分支已是 HEAD 祖先时返回成功，重试无副作用；持续读失败
            # 的极端由既有时间门降级路径兜底）。
            branch = _worktree_branch(wt)
            tip_sha = _worktree_head(wt)
            record_deferred_batch(
                root, pending_ids, fixed_ids, wt,
                branch=branch, tip_sha=tip_sha, last_overlap=[],
            )
            try:
                wm.release_spec_lock("code-review-fix", "code-fix")
            except Exception as e:  # noqa: BLE001 — 放锁失败车道可能死锁，留痕
                self._log("warning", f"code-fix 台账读失败保留现场放锁异常: {e}")
            self._log(
                "warning",
                f"code-fix 第 {batch_no} 批已合回但台账读失败（重试耗尽），"
                "已合回未核销——保留台账条目与 worktree 转延迟台账，待下一链"
                f"边界重试核销（branch={branch}, item_ids={item_ids}）",
            )
            write_progress(
                root,
                phase="merging",
                reason="",
                current=(
                    f"第 {batch_no} 批已合回但台账读失败未核销，"
                    f"保留待下一链边界重试（branch={branch}）"
                ),
                # 批上下文三键清除（defer D2 同款）：现场保留由延迟台账承载，
                # 防读侧按陈旧 run_id 合成条级进度。
                worktree=None,
                run_id=None,
                batch_total=None,
            )
            return "consumed"
        still_open = [
            i for i in resolve_candidates
            if (ledger.get(i) or {}).get("status") == "open"
        ]
        hit = mark_resolved(root, still_open) if still_open else 0
        # 链级核销计数累加（2.1）：以 mark_resolved 真实命中为准。
        if hit:
            self._chain_bump(root, chain_resolved=hit)
        # 失败登记闭环核销（add-codefix-failure-registration-closeout 1.1）：
        # resolved 终态可能补齐某失败登记的全终态判定，核销点即时检查。
        self._consume_failed_registrations(root)
        _safe_cleanup(wm, wt, success=True, logger=self._logger)
        new_done = done + hit
        # 链末批合回即链终局（2.1）：rollup 汇总 + 一行结构化日志，随本写点
        # 落盘并归零链级累积（非末批返回空 dict，不触碰链级字段——链继续）。
        chain_final = (
            self._chain_terminal_fields("chain_last_batch") if is_last_batch else {}
        )
        write_progress(
            root,
            phase="merging",
            done=new_done,
            current=f"第 {batch_no} 批完成（已核销 {hit} 条，累计 {new_done}/{total}）",
            reason="",
            # 批收尾清除批上下文（D2）：worktree 已 cleanup、out 随之不可达，
            # 条级字段让位给批级进度（spec「批收尾后条级字段让位」）。
            worktree=None,
            run_id=None,
            batch_total=None,
            **chain_final,
        )
        self._log(
            "info",
            f"code-fix 第 {batch_no} 批合回成功：resolved {hit}/{len(items)} 条"
            + (f"（另 ignored {ignored} 条）" if ignored else ""),
        )
        return "success"


def _safe_cleanup(wm, wt, success: bool, logger=None) -> None:
    """cleanup 包裹：异常只记日志不炸批 worker（锁泄漏比异常更糟，宁可多试）。"""
    try:
        wm.cleanup(wt, success=success)
    except Exception as e:  # noqa: BLE001
        if logger is not None:
            try:
                logger.warning("code-fix", f"worktree cleanup 失败（{wt}）: {e}")
            except Exception:  # noqa: BLE001 — 日志失败不影响批收尾
                pass


def _failure_summary(reg) -> str:
    """从回归快照提取失败用例摘要（重试 prompt 注入用，截断防爆炸）。"""
    snap = getattr(reg, "snapshot", None) or {}
    failures = snap.get("failures") or []
    lines = []
    for f in failures[:20]:
        if isinstance(f, dict):
            lines.append(
                f"- {f.get('classname', '')}::{f.get('name', '')}: "
                f"{str(f.get('message', ''))[:200]}"
            )
        else:
            lines.append(f"- {str(f)[:200]}")
    head = f"status={getattr(reg, 'status', 'failed')}"
    if not lines:
        return head + "（无失败用例明细）"
    return head + "\n" + "\n".join(lines)
