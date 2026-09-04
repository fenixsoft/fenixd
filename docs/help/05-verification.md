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
    VE->>VE: 逐场景执行/截图
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

验证产物集中在 `.fenix/verify-progress/<spec>/` 下。report.json 记录总体情况（summary：总场景数/通过/失败/警告/错误数）与逐场景明细（scenarios：每个场景的判定、失败信息、截图）；verification-report.md 则以 Markdown 形式汇总缺陷根因。

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
- **文件**：`.fenix/verify-progress/<spec>/report.json`、`verification-report.md`、`screenshots/`（含失败截图）

## 相关文档

- [SPEC 生命周期与状态机](03-lifecycle.md) — verified/bug-found 转移与逃生门
- [调度与治理规则](06-governance.md) — 修复循环三轮熔断
- [文件与数据地图](09-artifacts.md) — verify-progress 目录结构
- [FAQ 与故障排查](10-faq.md) — 验证反复失败怎么办
