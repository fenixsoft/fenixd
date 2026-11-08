## Why

`/api/specs` 服务端延迟已常态化在 0.66~0.76s（本地基准：热 get 0.209s + ETag 签名 0.225s，冷构建 1.875s；规模 533 specs / 509 归档目录 / 7 项目）。构成有三：ETag 签名与 `SummaryIndex.get()` 各自对全 spec 现算一遍同源依赖签名（10-15 热修 `f75a32966` 时已登记的「同源重复支付」遗留）；实例级单锁覆盖全部项目，任一项目重建期间其余项目读请求被串行化（生产比本地热路径多出的 ~0.3s 即锁排队）。2026-11-08 前端超时塌缩事故（`be38d1b41` 已修）让该延迟以「请求超时（>1s）」形式显形，用户体验直接受损。

## What Changes

- `/api/specs` 单请求的失效签名计算由两趟合并为一趟：`SummaryIndex.get()` 取数时顺带产出与 `invalidation_signature` 同构的签名哈希，ETag 通道（`_sig_specs`）消费该同趟签名，不再独立预扫描全 spec。单请求固定成本 ~0.43s → ~0.21s。
- `SummaryIndex` 实例级单锁改为按项目分槽锁（per-project RLock）：跨项目读写互不阻塞，同项目内 get/state_snapshot/invalidation_signature 仍互斥（保持既有写读正确性）。
- 304 防假签名语义随单趟化调整：签名与响应体出自同一次扫描（原子性增强），「发头前第三趟复核」对 `/api/specs` 不再必要，其余端点不受影响。
- 不改动：前端（零改动）、`/api/specs` 响应结构与 ETag 协商语义、SummaryIndex 增量失效语义、服务端分页契约。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `dashboard-conditional-get`: `/api/specs` 的 ETag 签名供给方式从「handler 前独立一趟 `invalidation_signature` + 发头前复核」改为「`get()` 取数同趟产出聚合签名」；签名/数据两趟间隙防护语义被同趟原子性替代。
- `dashboard-read-path-performance`: `SummaryIndex` 并发模型从实例级单锁改为按项目分槽锁；`get()` 产出自带失效签名聚合（与 `invalidation_signature` 同构同源），供条件请求通道复用。

## Impact

- 代码：`core/dashboard/data/summary.py`（get 签名聚合 + 分槽锁）、`core/dashboard/routes/spec_routes.py`（`_api_specs` 改自含响应 handler）、`core/dashboard/routes/base.py`（路由表摘 sig_fn + `_get_specs` 适配器去 `_json` 包装）、`core/dashboard/watcher.py`（零改动——`get()` 薄包装形态下 SSE 广播消费形态不变）。
- 行为影响面：`/api/specs`（列表 + ETag）、SSE 广播路径（watcher 经同一 get）；`/api/specs/<spec>` 详情签名走 `state_snapshot`（分槽后同项目语义不变）。
- 测试：`tests/test_dashboard_index.py`（SummaryIndex 并发/聚合）与 `tests/test_dashboard_api.py`（ETag/304 回归）需扩展（分槽互斥性、同趟签名与 `invalidation_signature` 一致性、304 不假签名回归），另新增 `tests/test_specs_api_perf_guard.py` 性能守卫。
- 性能预期：热路径 ~0.43s → ~0.21s；跨项目排队（实测 ~0.3s）消除；冷构建长尾不再阻塞其他项目读请求。
