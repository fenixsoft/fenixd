# 验证体系

Fenix 的验证不是「跑一遍测试」，而是一套三步流水线加门禁判定。理解这套体系，你才能读懂验证报告、定位伪失败、避免修复循环空转。

## 三步流水线

```mermaid
sequenceDiagram
    participant PM as PM Engine
    participant PLAN as Planner-Plan
    participant VE as VerifyEngine
    participant JUDGE as Planner-Judge

    PM->>PLAN: 阶段1 生成场景计划
    PLAN->>PLAN: 读 verify.yaml 契约
    PLAN->>PLAN: 生成 test_scenarios.json
    PLAN->>PM: 场景清单
    PM->>VE: 阶段2 执行验证
    VE->>VE: prepare（构建）
    VE->>VE: serve（启动被测实例）
    VE->>VE: 注入 BASE_URL
    VE->>VE: 逐场景执行/取证（截图 / 命令输出 / HTTP 响应体）
    VE->>PM: 验证报告
    PM->>JUDGE: 阶段3 门禁判定
    JUDGE->>JUDGE: 应用可达性 + 报告完整性
    JUDGE->>PM: verified / bug-found
```

整条流水线由 PM Engine 串起三个阶段。阶段 1 由 planner-plan 读取 verify.yaml 契约，生成 test_scenarios.json 场景清单；阶段 2 由 VerifyEngine 依次执行 prepare（构建）、serve（启动被测实例）、注入 BASE_URL，再逐场景执行并截图，产出验证报告；阶段 3 由 planner-judge 做门禁判定——先核应用可达性与报告完整性，再给出 verified 或 bug-found 的结论。

## verify.yaml 契约

`<项目根>/.fenix/verify.yaml`（随仓库提交）把「如何构建、如何启动、何时算就绪」变成声明，验证流水线在每轮验证前依次执行：

```yaml
# 可选：构建步骤，保证被服务产物包含最新合并实现
# （先装依赖再构建：package.json 新增依赖时主树 node_modules 会落后一拍）
prepare:
  - run: npm install --no-audit --no-fund
    cwd: core/dashboard/static
  - run: npm run build
    cwd: core/dashboard/static

# 可选：被测实例启动方式（缺省回退 config commands.start）
serve:
  kind: static                  # static=内置静态服务器；command=长驻服务命令
  root: core/dashboard/static

# 可选：就绪探针（缺省探根路径、期望 200、等待 60 秒）
ready:
  url: /#/overview
  expect: 200
  timeout: 60
```

**BASE_URL 铁律**：验证场景的 URL 由框架**全量改写**到本次被测实例地址。无论 planner 生成什么地址，场景一律打「新鲜构建的实例」，从根上杜绝「测到陈旧产物」。

被测实例在哪里构建由 `static_scope` 决定：默认值 `main` 在主树构建并起被测实例；改为 `worktree` 则在专用 serving worktree 内构建服务，与主树完全隔离。

## 多形态验证（web / cli / api）

验证不只有浏览器一种形态。场景按交付物形态选择 `kind`（场景级字段，缺省 `web`），三套 runner 分工：

| kind | 适用交付物 | 场景步骤 | 断言形态 |
|------|------------|----------|----------|
| **web** | 页面 / 交互 / 视觉 | `navigate` / `click` / `type` 等 DOM 步骤 | 元素存在性、交互可用性、内容正确性、布局完整性（Playwright） |
| **cli** | 命令 / 脚本 / 落盘 | `run`（command/cwd/env/stdin/timeout） | `exit_code` / `file_exists` / `output_match` / `file_content` / `json_output` / `dir_contains` |
| **api** | HTTP 端点 | `http_request` / `sse_connect` | `status_code` / `json_path` / `response_header` / `body_contains` / `json_schema` / `latency_under` / `sse_event_*` |

**kind 选择**：页面/交互交付→`web`；HTTP 端点交付→`api`（**不要再用 web 场景 navigate 到端点 `text_contains` 断 JSON 文本凑合**）；命令/脚本交付→`cli`；混合交付按交付物拆分场景、各自 kind，跨 kind 数据先后用 `depends_on` 串接。单场景内不混排步骤类型；关联词表的权威源是 `core/verify_engine/scenarios.py` 的 per-kind 常量。

**分层语义跨 kind 统一**：第 1/3 层断言失败=一定是 Bug；第 4 层（如 `latency_under`）失败=warning 需结合上下文；CLI/API 无第 2 层（交互可用性是 DOM 概念）。

**CLI/API 特异规则**：
- cli **非零退出码不判步骤失败**（错误路径测试的正常预期），由 `exit_code` 断言仲裁；`run` 步骤自动注入 `FENIX_VERIFY_BASE_URL` / `FENIX_VERIFY_PORT`（框架值优先）。
- api 用 `as` 命名响应、断言 `response` 字段引用（缺省最近一次）；`http_request` / `sse_connect` 的 URL origin 由框架全量改写（路径保留）。
- 证据形态为命令输出 / HTTP 响应体（**无截图属合法形态**），同样 64KB 截断纪律；CLI/API 场景报告的 `screenshots` / `visual_results` 恒为空列表。

**纯 CLI 交付不需要 serve**：契约形态由场景集自动反推——纯 `cli` 场景集跳过 serve/ready（不回退 `commands.start`），含 web/api 场景则 serve（或 `commands.start` 兜底）必须有效，缺失时验收报错打回 plan。

## 场景冻结与跨轮复用

验证场景（`test_scenarios.json`）由 planner **只设计一次**，验收通过即冻结，写入 `.fenix/verify-progress/<spec>/test_scenarios.json`。**此后无论重入验证多少次（打回重验、修复轮、重试），都直接复用冻结场景，绝不重新出题**——planner 单轮设计成本在小时级/千万 token 级，只应支付一次；更重要的是「同一把尺子量到底」：修复是否有效，衡量的始终是同一组标准。

冻结集的变更只有两条通道：

1. **admin 裁决**：冻结文件损坏、或修复新增了可交互元素导致覆盖缺口时，框架不自动重排，而是升级「场景计划争议」呼叫 admin 处置（扩展场景 / 声明纯展示）；
2. **人工重置**：删除冻结文件即批准重新出题（下一轮验证走完整 planner 设计流程）。

## verdict 四分类与证据链

门禁判定 `verified` 前的证据分四类：

| 类别 | 含义 | 流向 |
|------|------|------|
| **pass** | 场景全部通过 | → verified → done |
| **fail + 报告完整** | 场景失败且验证报告有证据 | → bug-found（修复循环） |
| **blocked-env** | 环境不可达/构建失败（非产品缺陷） | → 不判 bug-found，回 testing 重派新 attempt |
| **inconclusive** | 证据不足（mock/SSE 环境疑云） | → 不产生 verdict 信号，人工检查 |

> 关键防伪机制：**构建失败/环境不可达绝不判 bug-found**，防止「验证没能发生」被当成「验证发现了缺陷」→ 派生伪 fix → 修复级联空烧 token。

## 验证报告与修复循环

验证产物集中在 `.fenix/verify-progress/<spec>/` 下。report.json 记录总体情况（summary：总场景数/通过/失败/警告/错误数）与逐场景明细（scenarios：每个场景的 kind/判定/失败信息/证据——web 为截图，CLI/API 为命令输出与 HTTP 响应体）；verification-report.md 则以 Markdown 形式汇总缺陷根因。

验证失败后 SPEC 进入 `bug-found`，派生 fix 分支修复再重新验证。修复循环有三轮熔断：同一缺陷连续 3 轮验证失败即自动 blocked 转人工，防止在修不好的缺陷上无限烧钱。

## 伪失败防线

伪失败是验证链最大的 token 浪费源，Fenix 为此设了五道防线：

| 防线 | 说明 |
|------|------|
| 应用可达性门禁 | 应用不可达且场景全失败 → 不判 verified（防止陈旧产物骗过） |
| 报告完整性门禁 | 报告缺失/场景结果缺失 → 阻止推进 bug-found |
| blocked-env 不判 bug | 构建/环境问题不触发修复级联 |
| BASE_URL 重写 | 场景永远打新鲜实例 |
| 就绪探针 | 实例可用后才开始跑场景 |

## 验证结果在哪看

- **Dashboard**：SPEC 详情页的「验证报告」页签
- **CLI**：`/fenix-process <spec-name>` → 验证报告
- **文件**：`.fenix/verify-progress/<spec>/report.json`、`verification-report.md`、`screenshots/`（web 失败截图；CLI/API 证据在报告断言明细）

## 相关文档

- [SPEC 生命周期与状态机](03-lifecycle.md) — verified/bug-found 转移与逃生门
- [调度与治理规则](06-governance.md) — 修复循环三轮熔断
- [文件与数据地图](09-artifacts.md) — verify-progress 目录结构
- [FAQ 与故障排查](10-faq.md) — 验证反复失败怎么办
