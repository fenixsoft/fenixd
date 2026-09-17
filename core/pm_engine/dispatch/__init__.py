"""core.pm_engine.dispatch — 派发队列/优先级与老化/并发闸/退避/worker（子包门面 + 宿主）。

拆分自原 `core/pm_engine/dispatch.py`（refactor-giant-classes D2），
本 `__init__.py` 同时承担**宿主**与**门面**两职：
- 宿主：`Dispatcher` 类定义于此（组合 B/R/V/F/P/Q 六组 mixin，design D5 约定），
  六组方法原样搬移自各子模块（design D1 表 B）；
- 门面：re-export 全部公开名（类、2 常量），既有 import 路径不变。

同时暴露 `time` 到包命名空间（design D3 time 重绑缝隙）：测试
`patch.object(_dispatch_mod.time, "time", _tick)` 修改的是 time 模块对象
（即本包命名空间的 `time` 属性）的 `time` 属性——各子模块经模块顶部
`import time`（同一模块对象，全进程共享）即可，重绑依旧生效。
"""

# ── 标准库（D3 缝隙：time MUST 暴露在包命名空间供测试重绑） ──

import time  # noqa: F401

# ── 常量定义（design D1：2 常量，门面 re-export） ─────────────────────────────

# ── 派发锁冲突退避（improve-run-lifecycle-governance D5）────────────────────
# 派发 implementer 遇「worktree already active」时不再硬试三连发：按此序列指数
# 退避安排下一次尝试，期间不消耗 _retry_count、不写 retries exhausted（attempt
# 配额只属于任务失败，不属于基础设施冲突）。可配 pm.dispatch_backoff_schedule。
DEFAULT_DISPATCH_BACKOFF_SCHEDULE = (30, 120, 600)

# ── repair 通道轮次上限（add-merge-back-repair-lane D5）────────────────────
# 同一 merge 失败事件链内 repair 最多 2 轮，超限回退 fallback 全新重派。
# 模块常量、**不新增配置键**（规避 dashboard UI 联动义务，design D5）。
MAX_REPAIR_ROUNDS_PER_FAILURE = 2

# ── 子模块（refactor-giant-classes 逐组摘出后在此接入） ──

from core.pm_engine.dispatch import adjudication, backoff, fast_track, queue, repair_lane, rollback  # noqa: F401, E402
from core.pm_engine.dispatch.adjudication import VAdjudicationMixin  # noqa: F401, E402
from core.pm_engine.dispatch.backoff import BBackoffMixin  # noqa: F401, E402
from core.pm_engine.dispatch.fast_track import FFastTrackMixin  # noqa: F401, E402
from core.pm_engine.dispatch.queue import QQQueueMixin  # noqa: F401, E402
from core.pm_engine.dispatch.repair_lane import PRepairLaneMixin  # noqa: F401, E402
from core.pm_engine.dispatch.rollback import RRollbackMixin  # noqa: F401, E402

# ── 宿主类（design D5：组合各组 mixin，Q 组含 __init__，实例化经 MRO 命中） ──


class Dispatcher(
    QQQueueMixin,
    BBackoffMixin,
    RRollbackMixin,
    VAdjudicationMixin,
    FFastTrackMixin,
    PRepairLaneMixin,
):
    """派发队列组件（门面 PMEngine 的组合组件）。

    类为薄门面：全部方法按职责分布在各组 mixin（design D1 分组表），
    本类仅组合各组并保留类级状态。
    """
