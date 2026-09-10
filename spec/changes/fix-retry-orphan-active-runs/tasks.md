# Tasks: fix-retry-orphan-active-runs

## Deliverables

```yaml
- path: core/agent_runner/runner.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/detail.tsx
  kind: modify
- path: tests/test_retry_orphan_active_runs.py
  kind: new
```

## 1. 写侧：原地重试弃置产物补写 superseded 终态（spec：写侧落终态）

- [ ] 1.1 provider 瞬断通道（`runner.py:2168-2197` 区域）：`transient_retry` 事件 `append_run_line` 之后、`self._wip_checkpoint_before_backoff` 与 `time.sleep(backoff)` 之前，向同一 `{sub_run_id}.jsonl` 追加 `{"type": "superseded", "spec": ..., "provider": ..., "timestamp": ...}`；补写与原 transient_retry 写入共用同一 try/except 容错语义（append 失败不阻断重试）
- [ ] 1.2 artifact-gate 通道（`runner.py:2044-2071` 区域）：同款补写（transient_retry 后、WIP checkpoint 与 sleep 前），字段含 `reason: "artifact_gate"` 的对应语义（superseded 事件可带 reason 字段标注弃置来源通道）
- [ ] 1.3 注释固化不变量：两处补写点注明「superseded 紧跟 transient_retry = 本文件终态，重试在新 sub_run_id 文件继续；daemon 退避窗口内死亡由 interrupted 补写接续（末行仍终态）」；runner.py:1922 附近 sub_run_id 换新注释处交叉引用
- [ ] 1.4 `tests/test_retry_orphan_active_runs.py` 写侧用例：构造瞬断失败触发原地重试路径（mock `_run_claude` 抛 transient 错误、transient_budget 短序列），断言旧产物文件末两行为 `transient_retry` + `superseded`、重试写入新 `-r1` 文件；artifact-gate 通道同款断言（mock 产物硬门失败路径）

## 2. 读侧：superseded 映射 + mtime 陈旧兜底（spec：读侧识别 / stale 兜底）

- [ ] 2.1 `data.py` `_RUN_TERMINAL_STATUS_MAP` 增 `"superseded": "superseded"`；映射注释同步（终态事件类型清单更新，引用本 SPEC）
- [ ] 2.2 `data.py` 增模块常量 `_RUN_STALE_SECONDS = 1800`（注释：退避档上限 120s + 长 turn 余量；不做配置项的理由引 design D2）；`get_runs` status 组装处改判：`classify_run` 结果为 `running`/`empty` 且 `time.time() - stat.st_mtime > _RUN_STALE_SECONDS` → `stale`；`classify_run` 本体保持纯函数不注入 mtime（design D3）
- [ ] 2.3 `data.py` 顶部 `_RUN_TERMINAL_STATUS_MAP` 注释区的「读侧缺类型会把已终结 run 永远判成 running」事故清单追加本变体一行（运行期间重试换文件弃置，interrupted 补写够不到）
- [ ] 2.4 `tests/test_retry_orphan_active_runs.py` 读侧用例（`os.utime` 构造 mtime，勿 sleep）：① 末行 superseded → classify_run 返回 superseded；② 末行 transient_retry + mtime 陈旧（>1800s）→ get_runs 判 stale 且 project_summary active_runs 不计入（用 tmp 夹具项目构造 STATE/runs，参照 tests/test_dashboard_data.py 既有夹具模式）；③ 末行 transient_retry + mtime 新鲜（<1800s，utime 置 now）→ 判 running 且计入 active；④ empty 文件 + 陈旧 mtime → stale；⑤ result 终态文件 + 任意 mtime → done 不受兜底影响

## 3. 前端：时间轴 stale 渲染（spec：无独立 Scenario，design D4）

- [ ] 3.1 `detail.tsx` 时间轴 run 节点 status 判定区（`isRunning` 同区域）增 `st === 'stale'` → dotColor 灰（gray），注释标注「弃置/断尾：原地重试换文件弃置或进程被杀无终态，读侧 mtime 兜底判定」

## 4. 回归与收尾

- [ ] 4.1 真实数据回归：对当前 `.fenix/runs/`（339 文件、21 具 transient_retry 尸体、2 在飞）跑 `get_runs`，断言 21 具全判 stale、活跃数回归 2（允许 ±在飞数波动，断言 ≤ 在飞真实上限而非 23）
- [ ] 4.2 既有测试全绿：tests/test_dashboard_data.py（classify_run/_read_run_lines/活跃统计既有用例）、tests/test_agent_runner_gate.py 及 runner 相关既有用例
- [ ] 4.3 终检：`python3 -m pytest tests/ -x -q` 全量绿；前端 `core/dashboard/static` 下 `npm run build` 无类型错误（stale 分支类型收窄正确）
