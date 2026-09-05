# Design: add-verify-multi-kind-runner

## Context

验证链现状以 web 为唯一形态：场景验收硬性要求 `navigate` 绝对 URL 步骤（`core/verify_engine/scenarios.py` validate()）；18 种断言全部基于 Playwright DOM 四层库（`assertions.py`）；引擎无条件启动浏览器并驱动页面（`engine.py`，642 行）；契约 serve 仅 static/command 两种「起 HTTP 服务」形态。纯 CLI spec 在验收门即被整体拒绝；API 验证靠 web 场景 GET 端点 `text_contains` 断 JSON 文本凑合（`mock_api` 断流假阴性放大器已实证）。

关键既有资产（本设计尽量复用而非另起）：
- 裁决链 `verdict_check.py` 只依赖 `assertion_results` 的 `pass`/`layer`/`classification` 字段——对断言来源不敏感，天然可承载新词表
- `_determine_scenario_status` 的「1-3 层 fail / 4 层 warning」规则由 `pass`+`layer` 字段驱动，跨 kind 通用
- 契约 `verify.yaml` 的 prepare 段已具备「字符串=shell / 列表=argv」的命令解析约定，CLI 词表直接复用
- `depends_on` 拓扑排序、并行信号量、进度写盘、报告 schema 均与 web 假设无关

## Goals / Non-Goals

**Goals**
- 纯 CLI、纯 API、混合（web+api+cli）三类 spec 均有完整验证通路
- 延续「第 1-3 层断言失败=一定是 Bug」确定性承诺与逐断言归因（triage）粒度
- 存量 web 项目/场景/报告/冻结集零迁移
- 引擎结构化为 Runner 插件，未来新形态只加 Runner

**Non-Goals**
- 不做脚本逃生舱（场景声明自由脚本+判读）——破坏确定性不变量，YAGNI
- 不做单场景内跨 kind 步骤混排——用场景拆分 + `depends_on` 表达
- 不新增契约字段/配置键（与「新增配置项必须带 Dashboard 界面」规则无冲突）
- v1 不做 CLI blocked-env 降级探针、不做 API mock 上游服务器
- SSE 步骤（`sse_connect`）为 API 词表一部分，实现复杂度高时允许降为 fast-follow 单独交付

## Decisions

### D1: Runner 插件化而非引擎内 kind 分支（方案 B）

抽 Runner 接口（`kind`/`validate`/`setup`/`execute`/`teardown`/`probe_env`），三个实现独立模块；engine 瘦身为纯调度（验收门收集、拓扑分批+信号量、结果组装、状态判定、进度、报告、环境门骨架）。

- **备选 A（单引擎 if/else 分支）被否**：engine.py 已 642 行；浏览器健康检查/截图取证等 web 专属逻辑会散进通用路径；PMEngine 显式委托门面漏改分支的事故模式（改共享返回形状全库 grep 调用点教训）在分支堆里更易重演
- **备选 C（per-kind 独立管线+报告合并）被否**：调度/进度/报告/门禁复制三份，合并点新造，过度设计
- Runner 按场景集实际出现的 kind **lazy setup/teardown**：纯 CLI/API 轮次不启动浏览器（现状无条件拉 Playwright，纯 CLI spec 会白挂 headless Chrome）

### D2: kind 是场景级字段，混合 spec = 场景集混排

`TestScenario.kind ∈ {web, cli, api}` 缺省 web。调度器不认识 kind（查注册表分派），混合 spec 零特殊化；跨 kind 流程用现有 `depends_on`（打同一个 fresh 实例，状态经被测应用传递，不需要场景间数据管道）。

- 备选（spec 级 kind 声明）被否：fenixd 自身就是「dashboard 页面 + 端点」混合项目，spec 级声明会把混合 spec 逼成两个 spec 或引出场景组概念

### D3: 三套词表共用分层语义，断言结果契约不变

CLI/API 断言沿用第 1 层（存在性/状态）/第 3 层（内容）/第 4 层（启发式阈值，如 `latency_under`）语义，`ASSERTION_LAYERS` 按 kind 稀疏。CLI/API 无第 2 层（交互可用性是 DOM 概念）。断言结果仍是带 `pass`/`layer` 的 dict——裁决链、报告、dashboard 全部按字段驱动，零 kind 分支。

CLI 特异执行语义（与 web「失败即中断」唯一的分歧点）：
- 非零退出码**不判步骤失败**（错误路径测试的正常预期），由 `exit_code` 断言仲裁
- 超时=步骤失败（hang 本身是要抓的缺陷）且杀进程组（防孤儿子进程）
- 信号死亡/argv 二进制不存在=`error`（不进 product-bug 管道）

API 响应捕获：步骤 `as` 命名、断言 `response` 字段引用（缺省最近一次），支撑多请求流（create→get→delete）。

### D4: 契约形态按场景集反推，零新增字段

serve/ready 必要性由本轮场景集 kind 组成反推：纯 cli 全省（不回退 commands.start，`_ensure_app_reachable` 短路）；含 web/api 必须（缺失=验收错误打回）；混合照常起。BASE_URL 铁律扩展：`http_request`/`sse_connect` URL origin 全量改写（与 navigate 同规则，不引入第二套 URL 规则）；CLI `run` 自动注入 `FENIX_VERIFY_BASE_URL`/`FENIX_VERIFY_PORT` 且框架值优先（stale 地址事故同一防护逻辑）。

- 备选（契约显式声明 kind/mode）被否：serve 存在性是项目级决策（项目可能同时有 CLI spec 和 web spec），场景集反推已给出确定性行为且错误消息明确，无需新字段

### D5: 词表权威源单一，prompt 只做摘要

planner 模板标注权威源为 `scenarios.py` VALID 常量（防 parse_bugs 枚举漂移、tasks.md 格式漂移同类双源事故）；API 场景 URL 验收与 navigate 同规则（绝对 URL）。

### D6: 渐进落地，PR1 等价重构先行

PR1 抽接口+WebRunner 归位（现有测试全绿+Dashboard fixture 配方回归）→ PR2 ApiRunner（serve/ready/BASE_URL 复用度最高，先治 API 凑合验证老坑）→ PR3 CliRunner（新增无 serve 契约形态）。每步独立可验、独立回滚。

## Risks / Trade-offs

- [PR1 等价重构回归面大（触及全部现有 web 验证路径）] → 全量现有验证测试 + Dashboard fixture 验证配方（假项目+伪造 jsonl+watcher SSE）双回归；PR1 不含任何行为变更，diff 审查聚焦「搬运不改写」
- [SSE 步骤实现复杂度（流式收集/超时边界）] → 允许降为 fast-follow；降级不阻塞其余能力
- [CLI 超时=fail 可能误伤慢环境] → v1 接受（hang 属高频真缺陷）；超时值由场景声明控制，planner 指导写宽裕值
- [httpx/jsonschema 新依赖] → httpx 为 ApiRunner 硬依赖；jsonschema 缺失时 `json_schema` 断言在验收期报错打回（不静默跳过）
- [prompt 双落点漂移] → agents/*.md 改动遵循既有约定：先 merge main + merge-tree 自证零冲突
- [非零退出不判失败与 web「失败即中断」语义分叉] → 属刻意设计（错误路径测试），写进 Runner 模块文档与 planner 词表摘要两处

## Migration Plan

三 PR 渐进合入，每步可独立回滚。存量项目/场景/报告/冻结集零迁移：kind 缺省 web、scenarios.json 可选字段、报告空列表兼容。无数据迁移。回滚 = revert 对应 PR，存量路径行为不受影响。

## Open Questions

- `sse_connect` 的断言证据形态（窗口内事件截断上限、事件匹配的 actual 呈现）在 PR2 实现时定，原则同 64KB 截断纪律
- ApiRunner 的 client 级连接池参数（并发上限/keepalive）v1 用 httpx 默认值，观察到瓶颈再暴露配置
- `.fenix` 链接隔离边界（add-planner-efficiency 出题 planner 2026-09-05 实证发现）：worktree 作用域下验证实例的 `.fenix` 链接主树运行态，CLI 场景的 `file_content`/`json_output` 若断言 `.fenix/` 下路径（日志/config），读写实际落在主树——读断言无害，涉及写路径的 CLI 场景需在 planner 指导中标注此边界；根治需「验证实例独立 .fenix」的契约扩展，不在本 spec 范围
- 「serve 起完整 daemon」形态：backend 生命周期型交付物（如 agent_runner 的 run 结束摘要写入）需要验证环境内含 daemon 进程才能端到端验证；当前 serve 仅 dashboard-only 实例。CLI/API 词表可覆盖「确定性触发通道 + 文件断言」部分，生命周期部分留给后续契约扩展
