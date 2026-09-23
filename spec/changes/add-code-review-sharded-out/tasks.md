## Deliverables

```yaml
- path: core/code_review.py
  kind: modify
- path: core/agent_runner/maintenance_runs.py
  kind: modify
- path: core/agent_runner/result_gate.py
  kind: modify
- path: core/admin_monitor.py
  kind: modify
- path: core/dashboard/data/config_admin.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: agents/code-review.md
  kind: modify
- path: tests/test_code_review.py
  kind: modify
```

## 1. 读侧聚合工具与进度（core/code_review.py）

- [ ] 1.1 新增 `shard_paths(project_root, run_id) -> list[Path]`：glob `.fenix/code-review/out-<run_id>-b*.jsonl`，按批次 N 数值升序返回；新增聚合读取工具（迭代顺序分片 N 升序→主产物，逐行 json.loads 过滤空行/不可解析行，按 `file` 去重保留先见行）供三消费侧共用
- [ ] 1.2 `read_progress` 改造：`done` 为主产物与全部分片按 file 去重后的文件数；`current` 取 mtime 最晚来源末行的 `file`/`title`；主产物缺失而分片有行时 `done` MUST NOT 归零；响应字段形状不变
- [ ] 1.3 新增 `check_progress_stall(project_root, now) -> dict | None`：`read_progress` 聚合口径 `running=true` 且 `done==0` 且运行时长（自 manifest `requested_at`）超阈值时返回 `{run_id, minutes}`，否则 None；阈值读 `admin.code_review.stall_alert_minutes`（缺省 15，缺失/非法/非正整数回退 15）

## 2. 收尾 ingest 与产物硬门聚合（maintenance_runs / result_gate）

- [ ] 2.1 `_read_code_review_out`（maintenance_runs.py:1106）升级为聚合读取：消费 `shard_paths` 分片 + 主产物，按 file 去重后返回行列表；单分片解析失败不中断整轮（跳过该分片并在 error 上下文注明）
- [ ] 2.2 `_check_repo_code_review_artifact`（result_gate.py）存在性校验改聚合口径：主产物与分片合计 ≥1 有效行即通过，全缺失/全零行判失败；error 文案更新为「主产物与分片合计零有效行」描述并点名 run_id
- [ ] 2.3 收尾完成日志与 `code-review 手动审查完成` INFO 行补充分片计入数（如 `shards=3`），便于取证

## 3. 事中停滞告警接线（admin_monitor / 配置 / 设置页）

- [ ] 3.1 `core/admin_monitor.py` 周期节拍内调用 `check_progress_stall`：命中则经 AdminAlertStore 写人工告警，文案含 run_id、已运行分钟数、聚合 done=0 事实与「疑似子代理等待收工模式」归因提示；去重键 `code-review-stall-<run_id>`（单 run 至多一条）
- [ ] 3.2 `.fenix/config.template.yaml` 的 `admin.code_review` 注释段新增 `stall_alert_minutes` 说明（缺省 15、语义、非法回退）；`core/dashboard/data/config_admin.py` 键白名单同步放行该子键
- [ ] 3.3 settings 分面 `QualityPanel.tsx` 新增 `stall_alert_minutes` 数字输入（分钟粒度、正整数校验、保存走既有 config 写路径），并完成前端构建产物重建（`npm run build`）

## 4. 提示词契约（agents/code-review.md）

- [ ] 4.1 落盘纪律段新增「禁 async 等待收工」条款：收到 launched 元数据后 MUST 轮询分片文件行数推进审查，MUST NOT 以等待批次完成通知为由输出收工词（注明非交互模式 turn 结束即丢结果的机制原因）
- [ ] 4.2 新增子代理分片直写义务：派发子代理的 prompt MUST 含该批分片路径 `out-<run_id>-b<N>.jsonl`、逐文件一行 JSON 结构与「审完立即落分片」要求；主 agent MUST NOT 亲自重复审已派发文件、MUST NOT 重写分片已落盘批次

## 5. 回归测试（tests/test_code_review.py）

- [ ] 5.1 `shard_paths` 与聚合读取用例：分片 N 升序、空行/坏行过滤、file 去重保留先见、主产物缺失分片兜底
- [ ] 5.2 `read_progress` 聚合用例：分片 17+9 → done=26 running=true；主产物缺失不归零；响应字段形状与旧版一致
- [ ] 5.3 硬门聚合用例：仅分片有行 → 放行；主产物+分片全缺失 → 判失败且 error 含聚合口径描述
- [ ] 5.4 `check_progress_stall` 用例：零进度超 15 分钟返回结构、正常推进返回 None、非法阈值回退缺省、终态 run 短路
