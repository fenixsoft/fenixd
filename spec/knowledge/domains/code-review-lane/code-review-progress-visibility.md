# 审查进度聚合读侧与停滞告警

<!-- knowledge: capability=code-review-progress-visibility rev=1
     sources=spec/archive/2026-09-29-add-code-review-sharded-out -->

code-review 车道的事中可观测层：进度按「主产物 + 全部分片」聚合计算，run 零进度停滞超阈值时框架主动上报人工告警，让零产物从用户肉眼发现变为框架主动上报。

## 规则

- 聚合读取唯一入口：进度读侧（`read_progress`）、收尾 ingest（`_read_code_review_out`）、产物硬门三侧统一经 `core/code_review.read_review_out_rows` 取行；分片发现统一经 `shard_paths`（glob `out-<run_id>-b*.jsonl`，按 N 数值升序）。任何一侧不自写 glob、不另立读取口径。
- 聚合迭代顺序为分片（N 升序）→ 主产物；同 `file` 多行保留先见者（分片是原始产出，主产物是汇总兜底）。空行/不可解析行/非 dict 行过滤掉，不计入也不使读取失败；单来源读取失败跳过该来源不中断整轮；文件缺失是常态而非错误。
- `done` 为聚合后按 `file` 去重的有效行数（`done==total` 语义严格成立，不因重复行虚增）；`total` 为派发时落盘的 manifest 长度（口径不变）。
- `current` 取最后落盘来源（mtime 最晚者，平局取规范序后者——主产物胜出）末行的 `file` 字段，语义是被审文件路径而非分片文件名；末行缺 `file`（坏行）时置 None，不回退 title。
- 主产物缺失（被清理或从未创建）时进度不归零：只要有分片行，`done` 即分片去重行数。
- 进度响应字段形状固定为 `{running, review_id, review_kind, total, done, current}`；`running` 判定沿用 run 产物末行终态 + stale 阈值口径，聚合改动不触碰该判定。
- 停滞告警：run `running` 且聚合 `done==0` 持续超过阈值时，框架产生一条 ESCALATION 人工告警（`signal_type=code_review_stall`，severity major），文案含 run_id、已运行分钟数与聚合 done=0 事实，并归因提示「疑似 async 子代理等待收工模式」，供人工直接判断是否取消。
- 同一 run 的停滞告警去重：经 AdminStore `append_if_absent` 以 `code-review-stall-<run_id>` 为去重键（单次排他锁内查重+追加），单 run 至多一条；run 到达终态（`running=false`）后短路不再触发。
- 阈值经 `admin.code_review.stall_alert_minutes` 配置，缺省 15 分钟；非法值（负数/非整数）回退缺省。设置页 settings 分面 admin 作用域（QualityPanel）提供该键的配置输入，缺省回显 15。

## 关键行为

- 检测函数 `check_progress_stall(project_root, now)` 位于 `core/code_review.py`：复用 `read_progress` 聚合口径，以 manifest `requested_at` 起算已运行时长；由 `core/admin_monitor.py` 的 `_check_code_review_stall` 在既有 admin 周期节拍中调用，不另起线程、不依赖前端轮询（分面未打开也生效）。
- 分片残留不跨 run 误读：分片 glob 以 run_id 为界，上一 run 的分片不进入本 run 的聚合集合。
- 收尾 ingest 侧对聚合行再施加更严的有效性判据（`findings` 须为列表），并以指纹幂等合并重复行，台账不产生重复条目。

## 溯源

- 2026-09-29 add-code-review-sharded-out — 新建：分片直写模式下的三侧聚合消费口径（唯一入口/迭代顺序/file 去重/current 口径/主产物缺失不归零），加事中零进度停滞告警（admin_monitor 节拍检测、run 级去重、阈值配置与设置页输入）。
