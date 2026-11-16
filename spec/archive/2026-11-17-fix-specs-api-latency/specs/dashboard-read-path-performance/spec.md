## ADDED Requirements

### Requirement: SummaryIndex 按项目分槽锁

SummaryIndex 的并发控制按项目 key（`str(proot.resolve())`）分槽：每项目一把 RLock（经 `dict.setdefault` 原子取槽，槽锁数量随项目数线性、删除项目后槽锁残留可接受，不做清理机制）。`get()` / `state_snapshot()` / `invalidation_signature()` 在各自槽锁内执行——同项目内三方法互斥且 RLock 可重入语义保持（如 `invalidation_signature` 内调 `state_snapshot` 为同槽重入）；跨项目读写互不阻塞，任一项目的冷/增量重建不得阻塞其他项目的读请求。共享容器（`_idx`/`_state_sigs`/`_state_snapshot`/`_arch_sigs`/`_arch_snapshot`）各 key 仅被自己的槽读写。

#### Scenario: 跨项目读不互斥

- **WHEN** 项目 A 正在进行冷/增量重建（槽锁被长任务持有），项目 B 的 `/api/specs` 读请求到达
- **THEN** 项目 B 的请求在自身槽锁上立即获锁执行，不被项目 A 阻塞（等待时间与项目 A 的重建时长无关）

#### Scenario: 同项目写读互斥保持

- **WHEN** watcher 对项目 X 执行 `get(proot, cur, state_sig=...)` 增量重算期间，同项目 HTTP 读请求到达
- **THEN** 读请求等待同槽锁（与既有单锁语义一致），不产生并发读写中间态

#### Scenario: 槽锁可重入

- **WHEN** `invalidation_signature(proot)` 在槽锁内调用同项目的 `state_snapshot(proot)`
- **THEN** 同槽 RLock 可重入，调用正常完成（不死锁）

### Requirement: get 取数同趟产出失效签名聚合

`SummaryIndex` 提供 `get_with_signature(proot, specs=None, state_sig=None) -> tuple[list, str | None]`：返回摘要列表与失效签名聚合。签名聚合 MUST 与 `invalidation_signature()` 同构同源（同一 combine 结构：state/arch/runs/逐 spec 依赖签名），且 MUST 零额外 stat——直接复用取数轮已驻留内存的 per-spec 签名（缓存命中条目的存量 `sigs` 与本轮重算条目的新算 `sigs`）。签名与响应体出自同一次扫描（同趟原子）。state/arch 签名组件不可得（stat 失败等）时返回 `(列表, None)`，消费方降级为无条件 200 路径。`get()` 保留为 `get_with_signature()` 的薄包装（仅返回列表），既有消费方（watcher SSE 广播等）调用形态与行为零变化。

#### Scenario: 聚合签名与独立签名等值

- **WHEN** 对同一磁盘状态先后调用 `get_with_signature()` 与 `invalidation_signature()`
- **THEN** 两者返回的签名逐字节等值（守卫测试锚定，防两套 combine 结构漂移）

#### Scenario: 聚合零额外扫描

- **WHEN** `get_with_signature()` 在索引全命中（缓存未失效）状态下执行
- **THEN** 聚合阶段不产生任何新的文件 stat / 目录遍历（签名完全由内存中的本轮签名集拼装）

#### Scenario: watcher 消费形态不变

- **WHEN** watcher 以 `get(proot, cur, state_sig=state_sig)` 调用（SSE 广播路径）
- **THEN** 返回值仍为摘要列表（薄包装），广播行为与改前一致

#### Scenario: 签名组件不可得返回 None

- **WHEN** STATE.md stat 失败（竞态消失等）导致 state 签名组件缺失
- **THEN** `get_with_signature` 返回 `(列表, None)`，摘要列表仍正常产出，签名位为 None
