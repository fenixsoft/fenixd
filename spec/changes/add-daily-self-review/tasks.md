## Deliverables

```yaml
- path: core/self_review.py
  kind: new
- path: core/admin_monitor.py
  kind: modify
- path: core/agent_runner/runner.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/self-review.md
  kind: new
- path: core/config.py
  kind: modify
- path: core/dashboard/data.py
  kind: modify
- path: core/dashboard/static/src/pages/settings/index.tsx
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/SelfReviewPanel.tsx
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: modify
- path: tests/test_daily_self_review.py
  kind: new
- path: .fenix/config.yaml
  kind: reference
```

## 1 配置与调度（admin.self_review）

- [x] 1.1 config.py：解析 `admin.self_review` 段（enabled 缺省 false、run_at 缺省 22:00、read_todo 缺省 false），护栏校验（run_at 须合法 HH:MM；非法值打 ERROR 并回退缺省），接入既有热更新重载路径
- [x] 1.2 新建 core/self_review.py：调度判定（巡检轮询内检查 enabled && 本地时间 ≥ run_at && last_run_date < 今天）、状态文件 `.fenix/self_review_state.json`（last_run_date，同目录锁风格）、防重复与启动补跑
- [x] 1.3 admin_monitor.py 巡检循环挂接 self_review 调度检查点（不新增线程/定时器）
- [x] 1.4 单测：定时触发/同日防重复/23:30 启动补跑/enabled=false 全链路零动作

## 2 自省 run 与 todo.md 产物

- [x] 2.1 runner.py：新增 self-review run 类型（run_id 前缀 `review-<date>`，不走 spec 维度预算，token 归账到 cost-observability 独立类目，超时走 run_timeout_seconds 全局默认）
- [x] 2.2 prompt_builder.py + agents/self-review.md：自省 prompt 模板（文件化体系，缺失 fail-fast）——注入当日数据摘要（STATE 终态分布/runs 成败与秒挂超时丢弃计数/admin 告警与处置/日志 ERROR 聚合四源）+ read_todo=true 时注入 todo.md 全文；模板明确「仅产出回顾、禁止创建 SPEC 或派发」与条目质量标准（证据+建议、新 agent 可直接起草 SPEC）
- [x] 2.3 self_review.py 产物写入：markdown 追加项目根 todo.md（`## YYYY-MM-DD` 分节 + 浪费/失误/可改进三小节），文件不存在则创建；写入后 `git add` 限定 todo.md 单文件 commit + push，失败降级 WARNING
- [x] 2.4 失败处理：自省 run 失败/超时记 admin WARNING 告警（含原因），当日不重试，次日自然重试
- [x] 2.5 单测：首次创建/追加不覆盖/read_todo 开关注入与不注入/自省后 openspec 与 STATE 零新增（禁止自动建 spec）/commit 仅含 todo.md

## 3 Dashboard 设置页

- [x] 3.1 data.py：`admin.self_review` 三键的读写端点（沿用既有设置面板 API 模式，含后端 HH:MM 校验）
- [x] 3.2 SelfReviewPanel.tsx：enabled/read_todo 开关控件 + run_at 时间输入（前端 HH:MM 校验），挂入 v3 设置页；非法输入双端拒绝
- [x] 3.3 v3 dist 重建提交（含新设置面板）
- [x] 3.4 单测：端点读写往返、非法 run_at 拒绝

## 4 回归与验收

- [x] 4.1 全量回归：tests/ 既有套件全绿（重点关注 admin_monitor、config 热更新、runner 相关）
- [x] 4.2 真实环境验收：配置 run_at 为近未来时间实测一次完整自省（run 触发 → todo.md 追加 → 自动 commit → 设置页三键修改热更新生效）
