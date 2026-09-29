## Context

2026-09-29 实测（Playwright tracing + curl）：dashboard 传输浪费的主因是「无差别 2s refresh 心跳 × 无上限全量载荷 × 无协商缓存」三者乘积。历史 SPEC 已做过两轮相关治理：`add-dashboard-incremental-data`（摘要索引 + SSE 驱动 + gzip）与 `fix-dashboard-read-path-performance`（计算侧增量缓存）——本轮补齐**传输侧**：条件请求（304）与服务端分页。

约束：
- 单进程 `ThreadingHTTPServer`，无多 worker 缓存一致性问题；routes 为 `_json(返回值)` 包裹式适配（`self._error` 直写会双重写响应，见 alert_routes 注记）。
- 响应走 keep-alive，304 空体的 Content-Length 处理必须与现有 `_json` 路径一致，否则污染连接。
- 前端请求层是自研 `request()` 薄封装（`services/dashboard.ts`），无 react-query 等缓存库。

## Goals / Non-Goals

**Goals**
- 数据未变时传输归零（304）；数据变化时只传请求页（分页）。
- 全部改动向后兼容：缺省参数/无 ETag 的调用方行为零变化。

**Non-Goals**
- 不改 SSE 心跳频率与 watcher 扫描机制（心跳保留，成本由 304 兜住）。
- 不给 `/api/alerts`、`/api/config` 做分页（告警闭环视图需全量语义；config 天然小）。
- 不引入前端全局缓存库，请求层 ETag 缓存用模块级 Map。

## Decisions

### D1. ETag = 数据源签名哈希，非响应体哈希

对响应体做哈希（强一致）每次都要先序列化，304 省传输不省计算。改为对**数据源文件**做 `(mtime_ns, size)` 签名组合哈希：数据层新增 `data_signature(proot) -> str` 与 `data_signature_all(projects) -> str`；签名未变 → 响应必与上次相同（数据源不变则读路径输出确定）。签名计算本身按 `(path, mtime_ns, size)` 缓存键 memo（与 `_RUN_TASK_CACHE` 同模式），同一签名窗口内重复请求零扫描成本。

*放弃的替代*：响应体 MD5——序列化成本与 200 路径相同，违背「304 路径不序列化」目标。

### D2. 304 在 route 适配层实现，helper 注入而非改签名

base.py 的 JSON 适配函数增加 ETag 分派：route 返回值不变；适配层按 route 注册表附带的签名函数（或 route 返回 `(payload, sig)` 二元组——取侵入更小的前者）计算 ETag，与请求 `If-None-Match` 比对，命中则写 304 + `ETag` 头 + 空体并结束。304 响应必须与 `_json` 同一写出路径（Content-Length: 0），防 keep-alive 污染。

### D3. 分页在合并排序后切片，置顶先于分页

`admin-activities` 现有「未处理置顶 → created 倒序」在 `get_admin_activities` 归并层完成；分页切片必须发生在**合并排序之后**，保证任意页内容 ≡ 全量响应的对应区段（Scenario 可断言逐条一致）。specs 路由同理在现有排序输出上切片。

### D4. 前端请求层 ETag 缓存 + 304 透传复用

`request()` 内维护 `Map<url, {etag, data}>`：发起时带 `If-None-Match`，收到 304 则返回缓存数据（对调用方透明，接口不变形）；收到 200 则更新缓存。activities 页翻页改为显式 `page` 参数（进 URL，天然成为缓存键的一部分）；SSE 触发的 `load()` 重拉当前页。

### D5. refresh 心跳收窄只改项目详情页一处

项目详情页（`projects/detail.tsx`）的心跳 handler 从「全量重拉」改为「条件校准」——由于 D4 已让条件请求对调用方透明，此项实际是确认 detail 页心跳路径走 `request()` 封装即可命中 304，剩余改动是去掉心跳内绕过缓存的直连 fetch（若存在）。聚合页（overview/activities）零改动。

## Risks / Trade-offs

- **[mtime 粒度] 同秒内先写后读可能漏检变化** → 签名含 `size`，写回字节数不同的场景可检；同字节数同 mtime_ns 窗口的漏检窗口 ≤1 心跳周期（2s），下一心跳自愈。可接受（现状心跳本身就是最终一致）。
- **[304 + 分页叠加] 同 URL 不同参数的 ETag 独立** → 缓存键含完整 query，页与页互不干扰。
- **[老标签页]** 长驻标签页的内存 ETag 缓存随数据源数量线性（KB 级），无界风险忽略。

## Migration Plan

1. 后端先行：签名函数 + 304 helper + 分页参数（全部向后兼容，单独合入即可发布）。
2. 前端跟进：请求层 ETag 缓存 → activities 翻页接 API → detail 页心跳确认。
3. dist 重建提交（验证链读主树 dist）。

## Open Questions

（无——模式/契约已在 proposal 与 specs 钉死）
