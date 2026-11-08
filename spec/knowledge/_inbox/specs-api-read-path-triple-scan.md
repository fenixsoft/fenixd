# /api/specs 读路径：三趟同源扫描与跨项目单锁

## 背景

2026-11-08 SPEC 列表「请求超时（>1s）」排查：表层是前端 request() 超时塌缩 bug（commit be38d1b41 已修，fallback 误落 1s 下界），底层是 /api/specs 服务端 0.66~0.76s 常态延迟——超时塌缩让一直存在的延迟显形。立项 fix-specs-api-latency 治理（commit 1ea2b4c64）。

## 结论

- /api/specs 单次 200 请求对全 spec 扫**三趟**：①表驱动 ETag 通道 `_sig_specs`→`invalidation_signature`（handler 前独立签名）②`SummaryIndex.get()` 取数（逐 spec `_spec_dep_sigs` 比对缓存）③`_json` 发头前复核（`_pending_etag_ctx`，防两趟间隙假 304）。533 specs 基准单趟 0.21-0.23s，三趟合计 ≈0.66s。
- SummaryIndex 实例级单锁盖全部项目，任一项目冷构建（实测 1.875s）期间其余项目读请求串行化，7 项目下实测排队 ~0.3s。
- get() 缓存命中条目的 `idx[name]["sigs"]` 即聚合签名所需全部素材：同趟聚合零额外 stat，不违反 ETag「签名现算禁跨请求 memo」纪律（同趟产物非跨请求 memo）。
- 表驱动通道 304 短路在 handler 之前，无取数可复用；自含协商（`_api_config_get` 先例）后 304/200 双路径均单趟。
- 治理形态：`get_with_signature()` 同趟聚合（与 `invalidation_signature` 同构，一致性守卫测试锚定）+ 按项目分槽锁；`invalidation_signature` 生产路径退役，唯一消费方为守卫测试。

## 证据

- 本地基准（533 specs / 509 归档目录）：cold get 1.875s、hot get 0.209s、invalidation_signature 0.225s、payload ~629KB。
- 生产实测 0.66~0.76s（curl 五连），与三趟之和吻合；dashboard-serve.log 尾部 ConnectionResetError = 前端 1s abort 指纹。
- 溯源：spec/changes/fix-specs-api-latency（design.md D1-D4）；spec/archive/2026-10-07-add-dashboard-paging-and-etag（ETag 通道原设计）。
