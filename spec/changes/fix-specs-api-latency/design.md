## Context

`/api/specs?project=X` 单次 200 请求当前对全 spec（533 条 / 509 归档目录）做**三趟**同源扫描：

1. `_dispatch_table` → `_sig_specs` → `SummaryIndex.invalidation_signature()`：handler 前独立签名一趟（state/arch/runs + 全 spec `_spec_dep_sigs` 现算）；
2. handler `_api_specs` → `SummaryIndex.get()`：取数一趟（缓存命中的 spec 逐条比对 `_spec_dep_sigs`，其结果本就存于 `idx[name]["sigs"]`）；
3. `_json` 发头前经 `_pending_etag_ctx` 复核签名一趟（防两趟间隙假 304，item dba2f23f1f9d）。

本地基准（533 specs）：单趟 ~0.21-0.23s → 200 路径合计 ~0.66s（生产实测 0.66~0.76s 吻合）；另有实例级单锁跨 7 项目串行化（冷构建 1.875s 期间其余项目读请求排队，实测贡献 ~0.3s）。2026-11-08 前端超时塌缩事故（`be38d1b41` 已修）使该延迟以「请求超时（>1s）」显形。

知识约束（spec/knowledge/domains/dashboard-platform/）：`dashboard-conditional-get` 的「签名现算禁跨请求 memo」「宁缺 304 不假 304」；`dashboard-read-path-performance` 的增量失效语义；`dashboard-server-paging` 的 page/page_size 入签契约。

## Goals / Non-Goals

- **Goals**：`/api/specs` 200 路径三趟 → 一趟（~0.66s → ~0.21s）；跨项目锁排队消除；304 路径成本持平；304 假签名风险面收窄。
- **Non-Goals**：前端分页接入（独立立项）；`/api/specs/<spec>` 详情路径改造（其签名走 `state_snapshot`，本次仅随分槽锁受益）；响应结构 / ETag 协商语义 / 前端任何改动。

## Decisions

### D1 签名单趟化：`get_with_signature()` 聚合 + handler 自含协商

`SummaryIndex` 新增 `get_with_signature(proot, specs=None, state_sig=None) -> tuple[list, str | None]`：取数完成时**直接复用本轮已驻留内存的 per-spec sigs**（`idx[name]["sigs"]`，缓存命中与重算两路都有）+ 本轮 state/arch/runs 签名，按 `invalidation_signature` 完全同构的结构 combine 聚合——聚合本身零额外 stat（排序 + 哈希，微秒级）。签名与响应体出自同一次扫描，天然原子。

- `get()` 改为薄包装 `return get_with_signature(...)[0]`，watcher（`watcher.py:568` SSE 广播）等既有消费方零改动。
- `_api_specs` 改为**自含响应 handler**（`_api_config_get` 先例）：内部 `get_with_signature` → `_if_none_match_hit(base.py:261)` 内联协商 → 命中 `_write_304(base.py:890)`，未命中 `_json`（附带 ETag 头）。表驱动 `_API_GET_ROUTES` 的 `/api/specs` 条目摘掉第 4 位 sig_fn（4 元组 → 3 元组，摘出 304 通道）。
- **page/page_size 入签不丢**：现 `_sig_specs` 把 `page`/`page_size` 原始 query 值拼稳定串并入 combine（item ba4a1e3c3386，翻页防假 304）；该串拼装逻辑随协商内联搬入 `_api_specs`，与聚合签名组合后作为最终 ETag。
- `invalidation_signature()` 保留，docstring 注明生产路径已退役、唯一消费方为一致性守卫测试（见 D3）。

为什么不是「保留表驱动 + sig_fn 消费 get 缓存」：304 短路发生在 handler 之前（表驱动通道的既有纪律），命中时无 handler 取数可复用，sig_fn 仍须独立一趟——三趟并一趟无法达成；自含 handler 是唯一能同时优化 304/200 两路径的形态。

### D2 分槽锁：按项目 key 的 RLock

`SummaryIndex._lock`（实例级 RLock）→ `self._locks: dict[key, RLock]`，`_lock_for(key)` 以 `dict.setdefault(key, threading.RLock())` 取槽（CPython dict.setdefault GIL 原子，无需元锁，注释说明）。`get` / `state_snapshot` / `invalidation_signature` 的 `with self._lock` 改为 `with self._lock_for(key)`。

- 同项目内三方法仍互斥且 RLock 可重入语义保持（`invalidation_signature` 内调 `state_snapshot` 同槽重入）。
- 跨项目读写互不阻塞；共享 dict（`_idx`/`_state_sigs`/`_arch_sigs` 等）各 key 仅被自己的槽读写，GIL 下 dict 条目级并发安全。
- 类 docstring「锁粒度取舍（8b43aa321467）」段同步改写：当时「分槽收益不抵复杂度」的判断基于项目数少 + 并发轮询有限；现状 7 项目、实测锁排队 ~0.3s、冷构建 1.875s 长尾，翻案有据。

### D3 一致性守卫：两套签名防漂移

`get_with_signature` 聚合与 `invalidation_signature` 是同一失效键集的两次独立实现，存在漂移风险（结构改动只改其一 → 假 304）。守卫测试对同一磁盘状态断言两者逐字节等值；该测试是 `invalidation_signature` 退役后的唯一消费方。

### D4 304 复核语义随单趟化收窄

现状「签名与取数两趟间隙 → 发头前复核丢弃 ETag」针对的是表驱动通道的固有缺陷（两趟独立扫描）；单趟化后该缺陷面不存在，`/api/specs` 摘除复核。**其余表驱动端点复核机制不动**。「宁缺 304 不假 304」保持：`get_with_signature` 在 state/arch 签名组件不可得（stat 失败、解析异常）时返回 `(items, None)`，handler 降级无条件 200 路径（不挂 ETag、不协商），与 `_route_etag` 降级纪律同构。

## Risks / Trade-offs

- **304 命中路径成本结构变化**：现状 = 纯签名一趟（~0.225s，不触碰索引）；改后 = get 一趟（~0.21s，且预热索引缓存）。总量持平略优，副作用是 304 也写索引缓存（对后续 200 有利，非风险）。
- **自含 handler 脱离表驱动 304 纪律**：`dashboard-conditional-get` 既有规则「304 短路在表驱动分派层实现」对 `/api/specs` 不再成立——delta spec 显式 MODIFIED 该 Requirement，以 config 先例背书自含形态合法性。
- **聚合签名与响应体的窗口一致性**：扫描期间的数据写入本就下一轮可见（与现状一致），单趟化不引入新陈旧窗口。
- **分槽后锁数量随项目数线性**：7 项目 = 7 把 RLock，量级可忽略；项目删除后槽锁残留（dict 无清理）——量级同样可忽略，不做清理机制（注释注明）。

## Migration Plan

纯服务端内部改造，无数据迁移、无配置变更、无 API 形状变化。部署即生效（daemon 重启加载新模块）；前端零改动。

## Open Questions

（无——诊断阶段已实测钉死三趟成本与锁排队证据）
