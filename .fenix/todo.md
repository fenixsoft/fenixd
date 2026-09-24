## 待办（人工登记 2026-09-24）

- [ ] code-review run 取消（cancel）终态不做产物抢救落账：2026-09-24 run code-review-1790230628 取消后 inserted=0/shards=0，101 文件 45 条发现留在 out 文件需手工 `_read_code_review_out`+`upsert_findings` 补账；error 路径有抢救（1b83c1c1）而 cancel 路径没有，应统一收场抢救。
- [ ] code-review 主车道 ocr scan 网络僵死无护栏：opencodereview scan（101 文件并发 4）2h20m 仅 49s CPU（0.5%，纯网络等待），agent 轮询等待且被处决后「重试重启 scan」而非按提示词「ocr 不可达降级继续」收口，最终靠人工 cancel 脱困；应对 scan 加 CPU/时长心跳判据 + 不可达降级收口（与 ocr 车道心跳方案 prio4 同族）。
