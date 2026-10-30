## ADDED Requirements

### Requirement: 组织网格需求数量名单派生

组织网格（`GET /api/command-center/org`）响应 `summary` 块 MUST 新增 `specs` 键：当前项目筛选 × 时间窗内的活跃 SPEC 名单，条目形态 `{project, spec}`。派生 MUST 与既有 `spec_count` 同循环、同窗口口径（`parse_state` 活跃 SPEC，created 落窗；`all` 窗沿用 created 缺失/脏值仅全量窗计入的既有规则）；排序按 created 新→旧（created 缺失垫底）。org 响应既有键（含 `summary.spec_count` 数值）语义 MUST 零变动。

#### Scenario: 名单与 spec_count 同窗口口径

- **WHEN** window=7d、项目 fenixd 7 日内创建 3 个活跃 SPEC、另有 1 个更早创建的活跃 SPEC 与 1 个窗内创建后归档的 SPEC
- **THEN** `summary.specs` 恰含 3 条（fenixd 项目、按 created 新→旧），`spec_count` 数值不变仍为窗内计数，org 其余既有键与改动前逐字节等价

#### Scenario: 全部项目视图携带项目维度

- **WHEN** project 缺省（全部团队）且 A、B 项目各有一个名为 `fix-x` 的活跃 SPEC 落窗
- **THEN** `summary.specs` 含 `{project: A, spec: fix-x}` 与 `{project: B, spec: fix-x}` 两条独立条目

### Requirement: spec-runs 轮次聚合

系统 MUST 提供只读端点 `GET /api/command-center/spec-runs?project&spec&window`（`project` 必填=spec 所属项目，寻址语义复用既有 `_command_center_scope` 口径：未知/不存在项目返回 200+error 字典；`project` 或 `spec` 参数缺失/空值同样返回 200+error 字典（同族契约），MUST NOT 回落跨项目聚合；`window` 可选 today/7d/all，缺省 today，非法值防御性回落 today）。响应 MUST 含 `{project, spec, window, lanes}`；`lanes` 为花名册全量出列（零 run 车道也带 `rounds: []`，与 org 卡集合同序同全集：ROSTER 序 + 花名册外观测 lane 殿后；LANE_ALIASES 归并同口径）。轮次收集 MUST 两步：①全史定序——不限窗收集该（车道归并别名后）× 该 spec 的全部 run（扫 live+archive 全量产物，不套 14 日 mtime 粗筛；archived_names 剔除同口径保留），按 started 升序编 `seq`（1=全史最早）；②窗内出列——仅 started ≥ win_start（today/7d）或全史（all）的轮进入响应，按 started 降序输出（最新在前）。每轮条目 MUST 含 `{seq, run_id, started_ts, inflight}`；`inflight` 为 run status ∈ IN_FLIGHT_STATUSES 的读侧判定。started 解析失败的行 MUST 跳过（不硬造轮次、不占 seq）。端点 MUST 纯只读（不新增 POST，遵守本模块既有约定）。

#### Scenario: 全史定序窗内出列

- **WHEN** judge 对 spec-x 全史 5 轮（t1<…<t5）且 window=today 仅 t5 落在今日
- **THEN** judge 的 `rounds` 恰 1 条且为 `{seq: 5, run_id: 第5轮 run, started_ts: t5, inflight: false}`

#### Scenario: 花名册全量出列与别名归并

- **WHEN** 任一项目对 spec-runs 发起查询
- **THEN** `lanes` 含花名册全部车道（零 run 车道 `rounds` 为空数组、zone 标注既有分区），dispute-judge 观测 run 计入 judge 车道、repair 计入 code-fix 车道

#### Scenario: 窗口与归档剔除同口径

- **WHEN** window=all 且某已归档 SPEC 名下存在同名 run、spec-y 的某轮 started 解析失败
- **THEN** 已归档 SPEC 的 run 不出现在任何车道 `rounds` 中；spec-y 该损坏行被跳过且不占用 seq（其余轮 seq 连续）

#### Scenario: 未知项目错误契约

- **WHEN** `project` 指向不存在项目
- **THEN** 返回 200 + `{"error": "project not found", "project": ...}` 字典（与既有五端点同族契约）

#### Scenario: 必填参数缺失错误契约

- **WHEN** `project` 或 `spec` 任一参数缺失/为空值
- **THEN** 返回 200 + error 字典（与未知项目同族契约），MUST NOT 回落为跨项目聚合
