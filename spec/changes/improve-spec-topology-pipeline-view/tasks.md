## Deliverables

```yaml
- path: core/agent_runner/run_files.py
  kind: modify
- path: core/logger.py
  kind: modify
- path: core/dashboard/data/log_index.py
  kind: modify
- path: core/dashboard/data/topology.py
  kind: modify
- path: core/dashboard/static/src/pages/projects/topology/PipelineView.tsx
  kind: modify
- path: tests/test_run_id_spec_review_attribution.py
  kind: new
- path: tests/test_topology_derivation.py
  kind: modify
- path: tests/test_dashboard_log_index.py
  kind: modify
- path: tests/test_logger_event_size_cap.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 数据链路修复（后端单源）

- [x] 1.1 `core/agent_runner/run_files.py` 的 `run_spec_part` 追加 spec-review uuid
      段剥除：仅当 agent 前缀为 `spec-review-` 时，对时间戳剥离后的 spec 名匹配
      `^(.*)-[0-9a-f]{6}$` 且剥后非空才生效；`spec-review-add-collab-graph-bigscreen-8e869d-1792938331`
      → `add-collab-graph-bigscreen`，`fix-fix-<spec>-<ts>` / `impl-<spec>-<ts>-a2` /
      `planner-plan-<spec>-<ts>` / spec 名以 9-10 位数字结尾样本的返回值与修复前逐例一致
- [x] 1.2 新增 `tests/test_run_id_spec_review_attribution.py`：spec-review 形态
      （含多段 attempt/transient 后缀组合）剥离断言 + 非 spec-review 形态快照零回归
      （含 9-10 位数字保护、fix 家族递归前缀、`-a<n>`/`-r<n>` 链）
- [x] 1.3 `core/logger.py` 序列化出口加单事件体积上限：常量 `LOG_EVENT_MAX_BYTES`
      （256*1024），序列化超限时 context 替换为
      `{"truncated": true, "orig_bytes": <n>, "context_keys": [...]}` 后重新序列化，
      message/level/timestamp/component 原样保留；不超限路径逐字节不变
- [x] 1.4 新增 `tests/test_logger_event_size_cap.py`：巨型 context（>256KB）截断后
      单行 ≤ 上限且为合法 JSONL、含 truncated 标记与 message 完整；正常事件序列化
      结果与截断逻辑接入前逐字节一致
- [x] 1.5 `core/dashboard/data/log_index.py` 读侧防御：`_first_ts` 块内探测遇无行界
      超长内容（块字节内无 `\n`）时自块起点向后越过超长行、从下一行界（向后
      扫描到的首个 `\n`）之后探测（同 `_next_line_start` 续读法）；窗口读取遇长度
      > 常量 `LOG_LINE_SKIP_THRESHOLD`（128*1024）的行以 seek 越过继续读后续行，
      超长行内容不读入内存；`.truncated` 语义不变
- [x] 1.6 扩展 `tests/test_dashboard_log_index.py`：构造首行 6.6MB 巨型行的日志
      fixture——created 锚点在巨型行后时窗口含锚点后可解析事件；单请求读取字节数
      有界（不以窗口上限整读巨型行）；常规日志（无超长行）窗口起点/终点/截断标记
      与既有行为一致

## 2. 拓扑派生增强（topology.py）

- [x] 2.1 `core/dashboard/data/topology.py` handoff 时序链构建处改为单一串行判定：
      画边当且仅当 `prev.end ≤ cur.start 且 prev.start < cur.start`（终点缺失取
      start）；时间重叠或同刻启动（含双零时长退化）一律跳过；串行贴邻照画；
      attempt 链 retry 边与 dispatch 边不受影响
- [x] 2.2 派生层 dispatch 归位锚点：为每个 run 首节点计算可选字段
      `dispatch_anchor`——started 落在 transitions 相邻转移时刻区间 `[t_i, t_{i+1})`
      时取 `tr:<i+1>`（转移节点按既有 verify 节点同款 `<kind>:<序号>` 风格编号），
      无 transitions/时刻缺失时不下发该字段（前端回退 pm 主节点）；既有 edges
      端点不改写
- [x] 2.3 扩展 `tests/test_topology_derivation.py`：同刻启动（impl 与 planner-plan
      同 started）无边断言、串行 judge 链保留 handoff 断言、dispatch_anchor 区间
      归位与回退断言；使用临时目录 fixture（不读主树 `.fenix/`）

## 3. 前端管线视图（PipelineView.tsx）

- [x] 3.1 纵轴真实时间布局：时间域取全部可定位节点时刻 min/max（跨度 < 60s 按
      60s 兜底），`y` 线性映射，contentH = max(节点数 × 行高, 跨度线性最小高度)，
      同列重叠节点贪心行错开（泳道 assignRows 思路迁移），容器纵向滚动保留横向滚动；
      左侧时间刻度列（复用协作时序 TICK_STEPS_S 档位与 fmtTick 文案格式）
- [x] 3.2 PMEngine 生命周期节点链：transitions 逐条渲染小节点（`→<目标状态>` +
      时刻），链纵坐标走同一时间域；dispatch 边自 `dispatch_anchor` 指向的转移
      节点出发（字段缺省回退 pm 主节点）
- [x] 3.3 降级与防护：无可定位时刻节点（user/pm 空时刻）锚定 t0 行；transitions
      为空不渲染链；归档骨架 SPEC（零 run 节点）不出现 NaN 坐标、不抛错
- [x] 3.4 前端类型检查与构建通过（`core/dashboard/static` 下 tsc 无新增错误、
      umi build 成功重建 dist 产物），既有交互不回归：悬浮卡、发光脉冲、状态着色、
      fix 角标、点击下钻、跨视图 selectedId 联动

## 4. 集成验收

- [x] 4.1 端到端派生断言（临时目录 fixture 复刻实测样本形态：首行巨型行日志 +
      spec-review uuid 形态 run_id 产物 + 转移日志行 + 同刻启动的 impl/planner-plan）：
      `derive_topology` 返回含 spec-review 节点（stage=demand）、transitions 非空、
      不存在 impl→planner-plan handoff 边、run 首节点带 dispatch_anchor
- [x] 4.2 相关测试全量通过：`tests/test_run_id_spec_review_attribution.py`、
      `tests/test_topology_derivation.py`、`tests/test_dashboard_log_index.py`、
      `tests/test_logger_event_size_cap.py` 及受影响既有测试（test_dashboard_data.py
      等 run_spec_part 消费方）无新增失败
