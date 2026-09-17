# 疑点清单：giant-classes 重构（只记录不修）

> 本文件记录拆分三个巨型类过程中发现的潜在问题、设计缺陷和待决事项。
> 所有条目均来自静态分析和代码阅读，**不做任何修改**——记录供后续 spec 参考。
> 更新日期：2026-09-17

## 1. worktree_manager.py 疑点

### 1.1 `_detect_wip_overlap` 日志级别与阻断语义

- **位置**：`WorktreeManager._detect_wip_overlap`（第 2213 行）
- **现状**：WIP 重叠预检结果仅记录 WARNING 日志，返回空/非空列表但不阻断 merge-back
- **疑点**：调用方（`merge_back_from_branch`）把重叠清单挂到 `MergeConflictInfo.wip_overlap`，但调度层是否真正消费并处理？如果调用方忽略返回值，此预检就变成无谓的性能开销（每次 merge 前都执行两个 subprocess）
- **建议**：确认调度层是否读取 `wip_overlap` 并做决策；若只是日志，考虑降级为 debug 级别

### 1.2 `_list_dirty_tracked_files` porcelain 格式解析

- **位置**：`WorktreeManager._list_dirty_tracked_files`（第 3045 行）
- **现状**：porcelain v1 格式 `XY ` 前缀判定，`X`/`Y` 任一非空格即脏；`??` 跳过
- **疑点**：
  1. rename 操作产生 `R  old -> new`，当前把 `old` 和 `new` 都加入列表——但 `old` 可能已不存在（物理删除），导致 `git merge-tree` 时出现"文件不在工作区"的意外
  2. `line[2]` 被注释掉的历史（2026-09-02 修）显示曾误查 `line[2]`（空格分隔符），修复后只查 `[0]`/`[1]`——但 porcelain v1 规范 `line[0]`/`line[1]` 之后第 3 个字符固定为空格，`line[3:]` 才是路径——当前代码 `line[3:]` 正确，但边界 case：路径含空格时 `strip()` 可能截断路径
- **建议**：添加 rename 双侧去重测试，验证含空格路径的解析正确性

### 1.3 `_resolve_ignored_modify_delete_conflicts` 中 check-ignore 可靠性

- **位置**：`WorktreeManager._resolve_ignored_modify_delete_conflicts`（第 3241 行）
- **现状**：先 `git rm --cached` 移出索引，再 `check-ignore -q` 校验
- **疑点**：注释明确指出"unmerged 条目会被视为 tracked 而误报"——所以先 rm 再 check-ignore 是对的。但如果 `git rm --cached` 失败（如文件已被锁），后续 check-ignore 永远返回"未被忽略"，触发 abort——是否应该更优雅地处理 rm 失败？
- **建议**：当前逻辑保守（abort 是安全降级），可接受；未来若遇到误 abort 再优化

### 1.4 `_run_dist_build` fallback 逻辑的测试覆盖

- **位置**：`WorktreeManager._run_dist_build`（第 2775 行）
- **现状**：有契约时走 `run_prepare_steps`；无契约时 fallback 到 `npm run build`；无 `package.json` 时返回 False
- **疑点**：fallback 路径依赖 `DASHBOARD_STATIC_ROOT / package.json` 硬编码路径——如果 static 目录结构变化（如 v3/dist），fallback 可能静默失败
- **建议**：考虑支持多级 fallback 或至少记录更详细的诊断信息

### 1.5 类级状态 `_rehearsal_probe_done`/`_rehearsal_supported` 的并发安全

- **位置**：`WorktreeManager` 类属性（第 2263-2295 行）
- **现状**：多实例共享的类级缓存（一次探测，进程内永久生效），用于 `git merge-tree --write-tree` 可用性判断
- **疑点**：多线程环境下，两个线程同时探测时可能重复执行（无锁），但探测结果相同所以是幂等的——无功能问题，但有轻微性能浪费
- **建议**：可接受现状；若追求极致，可用 `threading.Lock` + double-check

---

## 2. dispatch.py 疑点

### 2.1 零变更成功哨的阈值硬编码

- **位置**：`Dispatcher._run_agent_worker` 零变更哨（第 887-968 行）
- **现状**：连续 3 次零变更 → blocked 交人工；阈值 `3` 硬编码
- **疑点**：此阈值无配置通道（不同于 `pm.dispatch_backoff_schedule`），不同项目可能需要不同容忍度
- **建议**：添加 `pm.zero_change_block_threshold` 配置项，默认 3

### 2.2 `_rollback_failed_dispatch` 的 backoff 时长硬编码

- **位置**：`Dispatcher._rollback_failed_dispatch`（第 1640 行）
- **现状**：`backoff_until = int(datetime.now(...).timestamp()) + 300`（5 分钟）
- **疑点**：此 5 分钟 backoff 无配置通道，与 `pm.dispatch_backoff_schedule` 独立
- **建议**：若未来需要调优，应提取为 `pm.rollback_backoff_seconds` 配置项

### 2.3 私有回引 `_pm._X` 耦合过深

- **位置**：全文件 130 处 `self._pm._X` 调用
- **现状**：Dispatcher 组件访问 PMEngine 的 52 个私有成员（design D5 已登记）
- **疑点**：
  1. 私有回引使得 Dispatcher 无法独立测试（需要构造完整 PMEngine mock）
  2. 跨组件修改 PMEngine 私有签名时，Dispatcher 会静默编译失败（Python 动态属性无静态检查）
  3. 当前只消解高频 5 个（design D5），其余 47 个留待后续 spec——但若后续 spec 不执行，技术债将持续积累
- **建议**：本轮只登记清单（1.7 任务），消解工作量确实太大，可接受分期

### 2.4 `_dispatch_backoffed` staticmethod 的生产类直调

- **位置**：`Dispatcher._dispatch_backoffed`（第 1468 行）
- **现状**：被 `admin_monitor.py` 直接调用（design D3 D3 已登记）
- **疑点**：static 方法意味着没有 `self`，但方法体访问 `self._pm`——实际是非 static，依赖实例状态
- **建议**：方法签名与实际用法不一致（名为 static 实为实例方法），可能造成混淆；但调用方正确，功能无影响

### 2.5 `_handle_dispatch_lock_conflict` 退避序列的边界

- **位置**：`Dispatcher._handle_dispatch_lock_conflict`（第 81 行）
- **现状**：序列耗尽仍持锁 → 发 `dispatch_stalled` 信号上报，spec 保持 ready
- **疑点**：上报后 spec 保持 ready 但不再重试——是否需要自动降级到 blocked？当前依赖人工介入
- **建议**：可接受现状（人为干预更安全），但可考虑增加自动标记 blocked 的阈值

---

## 3. server.py 疑点

### 3.1 `_handle_api_post` 33 分支路由链的维护成本

- **位置**：`DashboardHandler._handle_api_post`（第 849-1061 行）
- **现状**：33 个 `elif path ==` / `elif path.endswith` 分支，每个对应一个端点
- **疑点**：
  1. 新增端点时容易遗漏注册（无编译时检查）
  2. `endswith` 陷阱顺序（project lifecycle 必须在 describe 之后）靠注释维护，新人易踩坑
  3. 此问题将在本 SPEC 的阶段 3（4.5 任务）解决——表驱动 + 按资源委派
- **建议**：**本疑点将在重构中解决**，无需额外动作

### 3.2 `find_free_port` 的端口范围硬编码

- **位置**：`find_free_port`（第 171 行）
- **现状**：`max_attempts=50`，从 `start` 开始线性探测
- **疑点**：端口范围 `start` 由调用方传入（默认 8787），`max_attempts` 无配置通道；50 次探测可能不够（高并发场景）
- **建议**：可接受现状（dashboard 只绑定 127.0.0.1，冲突概率低）

### 3.3 `ALLOWED_IMAGE_EXT` 与类耦合不足

- **位置**：`ALLOWED_IMAGE_EXT`（第 80 行）
- **现状**：模块级常量，被 `_serve_screenshot` 使用
- **疑点**：若截图扩展名白名单需要更新（如新增 .avif），需修改常量——这是运维决策还是开发决策？无配置通道
- **建议**：可接受现状（白名单较小且稳定）

### 3.4 `SSEClientPollInterval` 与心跳间隔的解耦

- **位置**：`SSE_CLIENT_POLL_INTERVAL`（第 94 行）与 SSE 心跳间隔（25s，硬编码在 `_sse_send` 中）
- **现状**：轮询间隔 1.0s 独立于心跳间隔 25s
- **疑点**：轮询间隔决定"释放连接槽位"的响应速度，心跳决定"保持连接"的频率——两者无依赖关系，但命名易混淆（都叫 interval）
- **建议**：可接受现状（注释已说明）

### 3.5 `MAX_SSE_CONNECTIONS` 与 `MAX_SERVER_THREADS` 的关系

- **位置**：`MAX_SSE_CONNECTIONS=32`、`MAX_SERVER_THREADS=64`
- **现状**：SSE 连接数 ≤ 服务器线程数，但无强制约束
- **疑点**：若 SSE 连接数超过线程数，新 HTTP 请求可能被阻塞——但实际 SSE 连接占用线程时间短（非长阻塞），可接受
- **建议**：可接受现状

---

## 4. 跨文件疑点

### 4.1 三个巨型类无循环依赖（已验证）

- **结论**：三个文件均无反向 import，零环
- **风险**：拆分后子模块可能引入新环（design D6 已防护）

### 4.2 `bin/gen-route-map.py` 的隐性消费

- **位置**：`bin/gen-route-map.py`（design D4 已详述）
- **现状**：文本扫描 `server.py` 的 `path == "/api/..."` 字面量
- **疑点**：本 SPEC 阶段 3（4.6 任务）将同步修改扫描源，否则 route-map 静默退化
- **建议**：**必须**在阶段 3 完成时验证 `tests/test_planner_route_map.py` 通过

### 4.3 characterization tests 的局限性

- **位置**：`tests/test_characterization_giant_classes.py`
- **现状**：33 个测试覆盖盲区方法，但基于 mock subprocess
- **疑点**：mock 可能遗漏真实 git 行为的边缘情况（如 git 版本差异、并发冲突）
- **建议**：这些是 characterization tests（锁定当前行为），不是 exhaustive 测试——重构后行为等价即可，无需追求 100% 覆盖

---

## 5. 重构执行相关疑点

### 5.1 mixin 模式 vs 模块函数注入

- **现状**：design D5 允许 mixin 或模块函数注入，未明确选择
- **疑点**：mixin 模式下 `self.<method>` 跨组调用自然保留，但 MRO 需精心设计（资源组须排在 `BaseHTTPRequestHandler` 之前）；模块函数注入更清晰但需修改所有调用点
- **建议**：实现阶段按组内互调密度决定——worktree/dispatch 组内互调密集，倾向 mixin；server 的 H0-H10 较独立，可用模块函数

### 5.2 patch 缝隙保持的测试验证

- **现状**：design D3 登记了 patch 缝隙清单，但未有专项测试
- **疑点**：重构后如果子模块的 import 路径变化，patch 字符串路径可能失效——需要专项验证
- **建议**：阶段 4（5.2 任务）逐项运行 patch 缝隙测试文件

### 5.3 characterization tests 的基线记录

- **现状**：`test_characterization_giant_classes.py` 记录了当前行为
- **疑点**：这些测试的"基线"是 mock 行为，不是真实 git 行为——如果重构后 mock 路径变化，测试可能误通过
- **建议**：测试通过即可（mock 路径锁定在 `core.worktree_manager.subprocess.run` 等，与 design D3 一致）

---

## 附：疑点统计（最终态，2026-09-18 阶段 4 更新）

| 类 | 疑点数 | 本轮解决 | 待后续 spec |
|---|---|---|---|
| worktree_manager | 5 | 0 | 5（纯功能/覆盖盲区，与结构重构无关） |
| dispatch | 5 | 0 | 5（2.3 私有回引余量见 contract-inventory D5 清单） |
| server | 5 | 2（3.1 endswith 顺序陷阱由 4.5 表驱动保留；4.2 route-map 由 4.6 三条 MUST 同步） | 3（功能类） |
| 跨文件/重构 | 3 | 3（4.1 无环验证 D6；4.2 route-map 同步；5.1 mixin 模式落地） | 0 |
| **合计** | **18** | **5** | **13** |

本 SPEC 收尾确认（阶段 4）：
- **4.1 无环**：D6 静态 import 扫描确认 worktree_manager / dispatch / dashboard(含 routes/ 子包) 包件间零新环，server 子路由无 `core.dashboard.data` 反向依赖（5.3 任务）；
- **4.2 route-map**：4.6 已同步 `scan_server_routes`（扫描 `routes/base.py` 三张表驱动路由表 + 文本 fallback）、方法归属启发式（由表名显式声明）、自检 grep 源（同文件集合）；`tests/test_planner_route_map.py` 全绿，含 `TestRepoCoverageRegression::test_repo_api_entries_not_reduced`；
- **5.1 mixin 模式**：worktree/dispatch/server 全部采用 mixin（各组方法经宿主实例 `self.<method>` 跨组协作，D5 约定落地）；server 资源组 mixin 在 MRO 中排列于 `BaseHTTPRequestHandler` 之前；
- **5.2 patch 缝隙**：D3 清单逐项运行——worktree `subprocess.run`/`time.time` patch 目标、dispatch `time` 重绑、`Dispatcher._dispatch_backoffed` 类直调、server `start_daemon`/`stop_daemon` 字符串路径 patch 与常量 monkeypatch 均经对应宿主命名空间延迟解析，专项测试文件全绿；
- **端点集合**：4.8 枚举重构前后 (path, method) 集合，GET 20 / POST 33 / DELETE 2 完全相等，55 = 55；
- **回归**：5.1 有界全量 `bin/run_full_suite.py --baseline` 与基线比对，当前失败 ⊆ 基线失败集（+本次修复前发现的 settings_routes 遗漏 import 已修复后清零），无本次引入回归。

所有疑点均不阻塞重构执行（本 SPEC 只做结构搬移，不改行为）。后续 spec 可按优先级处理：
- **高优**：2.1（零变更阈值可配置）、2.3（私有回引消解剩余清单）、3.3（SSEClientPollInterval/心跳解耦）
- **中优**：1.2（rename 去重测试）、1.4（dist build fallback 测试覆盖）
- **低优**：其余疑点（功能无影响，可延后）
