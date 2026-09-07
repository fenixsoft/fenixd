"""core/pm_engine — 项目管理引擎包（refactor-core-packages）。

由单文件 pm_engine.py 重组为「门面 + 职责组件」结构（design D2）：

- engine.py   PMEngine 门面：事件编排/派发/收尾/报告留此，组装组件，
              为测试引用的私有方法保留一行委托（design D3 规则 4）
- family.py   FamilyGovernor：fix 家族治理（阶段 4）
- budget.py   ImplBudget：实现尝试总预算（阶段 4）
- verification.py VerificationPipeline：三阶段+legacy 验证/冻结/合同（阶段 5）
- dispatch.py  Dispatcher：队列/优先级/老化/退避/_process_queue（阶段 6）
- recovery.py  RecoveryWatch：恢复观察注册/复查/持久化（阶段 6）
- reporting.py ReportBuilder：项目报告/日报/pushable specs（阶段 6）
- （后续阶段：verification / dispatch / recovery / reporting 渐次就位）

对外 API 兼容保证（spec core-package-structure「外部 API 零变化」）：
`fenixd.py` 的 `from core.pm_engine import PMEngine`、测试的模块属性补丁缝
（core.pm_engine.subprocess 等）全部保持可用。
"""

# ── verified→done 门禁任务缺口结论的结构化标记 ─────────────────────
# 门禁 _task_completion_blocker 因未完成数字任务拦截时，以此前缀写入
# STATE error 字段；恢复巡检 check_blockers 据此前缀识别「待人工裁决」
# 而非执行 auto-recover；门禁放行时清除既有此前缀 error（人工补勾感知）。
# 写侧（门禁）与读侧（恢复巡检、门禁自清除）共用此常量，杜绝字面量漂移。
# 置于 `.engine` import 之前：engine.py 顶层以 `from core.pm_engine import
# TASK_GAP_ERROR_PREFIX` 直接引用，避免模块初始化顺序的循环依赖。
TASK_GAP_ERROR_PREFIX = "task-gap:"

from .engine import PMEngine  # noqa: F401,E402
from .engine import *  # noqa: F401,F403,E402
