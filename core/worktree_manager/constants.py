"""constants.py — worktree_manager 包级常量单源（code-review abf55539cf18）。

原定义于包 `__init__.py` 常量区。拆为独立模块的原因：dist_conflicts /
legacy_registry / lifecycle / locks / mergeback 等子模块在模块顶部执行
``from core.worktree_manager import <常量>`` 时，包 `__init__` 尚在初始化
（半成品模块），常量可用性完全依赖「常量定义先于子模块导入」这一隐式顺序
——实为被定义顺序化解的循环导入。子模块改从本模块导入后该顺序约束消除；
`__init__.py` 仍 re-export 全部常量，既有 `from core.worktree_manager import X`
导入路径不变。本模块 MUST NOT 导入包内其他模块（保持零依赖，可在包初始化
任意阶段安全加载）。
"""

# ── 锁治理（improve-run-lifecycle-governance D4）─────────────────────────────
# 锁是内存集合 _spec_locks，daemon 重启即丢失；同时 attempt/resume 的孤儿子进程
# 却可能在进程表中继续存活。两类场景都以「真实进程表」为唯一真相：
#   - 在册锁扫描不到匹配进程、且对应 run 流文件停止增长超过该窗口 → 陈锁，回收
#   - 无在册锁但进程表存在指向该 spec worktree 的存活进程 → 视为仍持锁
STALE_LOCK_IDLE_SECONDS = 120
# 恢复重派遗产宽限期（add-recovery-legacy-check D2）：跟随孤儿清扫周期的同族常量，
# 不引入独立定时器。遗产注册后若后继 run 迟迟未 merge（如全链冷却），宽限期超时由
# 清扫器兜底回收。与 STALE_LOCK_IDLE_SECONDS 同族，语义上即「孤儿清扫一轮能扫到的
# 最大陈态窗口」，遗产在此窗口内保留、超时即视为无人收编而回收。
LEGACY_GRACE_SECONDS = STALE_LOCK_IDLE_SECONDS
# has_active_worktree 在派发热路径被高频调用，pgrep 每次数十毫秒；对同一 spec
# 的进程表扫描做短缓存，避免派发风暴。缓存窗口内的进程消失/出现误差可接受。
PROCESS_SCAN_CACHE_SECONDS = 5.0
# pre-dispatch autostash 条目的消息前缀（fix-autostash-orphans）：周期巡检按此
# 识别「框架自己 stash 的条目」——人工手工 stash 的条目不带此前缀，永不自动回收。
AUTOSTASH_MSG_PREFIX = "fenix: pre-dispatch autostash"
# merge-back 前 WIP 重叠闸门收纳条目的消息前缀（evo-merge-back-wip-overlap-gate
# D1）：MUST NOT 包含 AUTOSTASH_MSG_PREFIX 子串——reclaim_stale_autostash 以
# 子串匹配栈顶并 pop（stash_guard.py），复用同前缀会让「故意保留待人工找回」的
# 闸门条目被 60s 巡检抢走并沿用丢弃策略，去向记录随即失真。
WIP_GATE_STASH_PREFIX = "fenix: wip-overlap gate stash"

# acquire 侧陈锁存活清扫的锁龄判据上限（fix-worktree-lock-release-degrade-gate
# D3 判据②）：锁龄超过该值即「派发窗口已过」。与 agent_runner adaptive backoff
# early give-up 预算封顶缺省值同源（runner.
# ACQUIRE_BACKOFF_BUDGET_CAP_DEFAULT_SECONDS = 1200.0）；worktree_manager 无配置
# 访问通道（镜像常量，零依赖约束见本模块 docstring），配置覆盖项
# （worktree.acquire_backoff_max_budget_seconds）不在此生效——两侧口径演进须同步。
STALE_LOCK_SWEEP_LOCK_AGE_CAP_SECONDS = 1200.0

# dashboard 静态根（相对项目根）：构建产物目录（dist/、v3/dist/ 等层级变体）
# 都在其下。产物冲突判定按目录层次容错——写死单一路径前缀会在主树重命名产物
# 目录（如 v3/dist→dist，add-dashboard-incremental-data 事故）后，把冲突
# rename 双胞胎的旧路径误判为语义冲突，自愈静默跳过。
DASHBOARD_STATIC_ROOT = "core/dashboard/static/"

# ── worktree 可用性三态（interrupt-recovery-preserve D5）────────────────────
# is_available 的返回值：以 git 为真相（git worktree list + rev-parse --verify），
# 不信任内存表（daemon 重启即失）。recovery 保留判定、resume 派发、复用认领
# 三条链路共用同一查询，禁止各链路自行拼装目录/分支判断。
WT_AVAILABLE = "available"  # 分支可解析 + 目录在场 + git worktree 注册有效 → 原地可用
WT_REBUILDABLE = "rebuildable"  # 分支可解析但目录缺失/未注册 → 可在既有分支上重建
WT_UNAVAILABLE = "unavailable"  # 分支不可解析（已并入/已清扫/typo）→ 不可用，调用方降级
