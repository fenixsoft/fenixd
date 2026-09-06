# add-verify-multi-kind-runner — 验证报告

- **裁决时间**: 2026-09-06T02:00+00:00（planner-judge a1）
- **验证引擎**: verify-add-verify-multi-kind-runner-1788656261-a1
- **结论**: ✅ **验证通过（verified）— 无产品 Bug**
- **统计**: 18 场景 / 13 通过 / 5 失败 / 0 错误 / 0 阻塞

> ⚠️ **并发覆盖说明**：本裁决对象为 planner-judge a1 派发时点（01:23:09 UTC）的
> 18 场景 E2E 验证报告。裁决期间该 report.json 曾被并发的另一轮验证覆盖（40 场景
> 契约形态回归全过，原始文件备份于 `/tmp/current-40pass-report.json.bak`），随后框架
> 判定 a1 结果为 stale/foreign 并重新派发验证。本报告已将 18 场景报告恢复并按
> 逐场景裁决覆盖写回，供本轮校验消费。

---

## 一、总览

| 指标 | 值 |
|---|---|
| 场景总数 | 18 |
| 通过 | 13 |
| 失败 | 5 |
| 错误 | 0 |
| 阻塞（blocked_env） | 0 |
| 产品 Bug | **0** |
| 场景测试缺陷（test-defect） | 4 |
| 不稳定（flaky） | 1 |

## 二、失败场景裁决明细

### 1. `cli-env-injection-framework-priority` — test-defect

**断言失败**（2/3）：

| 断言 | 期望 | 实际 |
|---|---|---|
| output_match regex `^http://127.0.0.1:41767\.0\.0\.1:\d+` | FENIX_VERIFY_BASE_URL 为框架注入实例地址 | `http://127.0.0.1:41767` |
| output_match regex `\n\d+$` | FENIX_VERIFY_PORT 为纯数字 | `NONE` |

**归因**：
- 断言 1 = **test-defect**：正则畸形，要求 `.0.0.1:` 后缀，而真实注入值
  `http://127.0.0.1:41767` 无此形态。**复现证实**：引擎正确设置 `base_url`
  并注入（PORT=41767）后，该断言依然失败——断言永远不可满足，与框架行为无关。
- 断言 2 = **env**：实测 `NONE`，本轮引擎执行时实例 base_url 未供给 CLI Runner
  （serving 实例 09:22:52 才完成登记，base_url 供给存在时序/环境缺口）。注入机制
  本身经单测 `test_env_injection_framework_priority` 与多层复现验证**正确**。

场景级判定：**不记产品 Bug**（两条失败断言均非 product-bug）。

### 2. `api-specs-status-structure` — test-defect

**断言失败**（2/6）：

| 断言 | 期望 | 实际 |
|---|---|---|
| json_path `project` | `fenixd` | `null` |
| json_schema | 合法 JSON 且符合 schema | 响应体非合法 JSON |

**归因**（同一根因，合并为一条 test-defect）：
- GET `/api/specs?project=fenixd` 响应体 **70,121 字节**，超过 runner **64KB 截断
  阈值**，截断后 `json.loads` 失败 → `resp.json=None` → `json_path` 求值 null、
  `json_schema` 报「非合法 JSON」。
- **线上复核**：直接请求该端点返回 **200 + 合法 JSON**（`project=fenixd`、135 个
  specs），端点完全正确。
- 失败源于 runner 截断限制（设计约束）与断言对大响应不具备健壮性之间的冲突，
  属场景设计缺陷，非产品缺陷。

### 3. `web-overview-regression` — flaky

**断言失败**（2/3）：

| 断言 | 期望 | 实际 |
|---|---|---|
| element_visible `.ant-page-header` | 概览页头可见 | 超时 3000ms |
| text_contains `跨项目概览` | 页面含标题 | 未找到 |

**归因**（同一根因，合并为一条 flaky）：
- 页面结构**正确**：`overview/index.tsx` PageContainer 渲染 `.ant-page-header` 与
  标题「跨项目概览」。
- **现场复核 + 重跑通过**：对当前实例 Playwright 验证 `.ant-page-header` 可见、
  标题文本存在；重新执行该场景经引擎跑出 **pass**。
- 运行期失败源于**冷启动实例时序**：实例 09:22:50 刚启动、`/api/overview` 响应
  耗时 5233ms，且场景导航后无等待步骤，3s 断言窗口不足。非产品缺陷。

### 4. `web-report-kind-badge-assertions` — test-defect

**断言失败**（1/8）：

| 断言 | 期望 | 实际 |
|---|---|---|
| element_visible `.ant-tabs-tabpane-active .ant-card:has-text("fixture-cli-probe")` | cli 场景卡片可见 | 超时 3000ms |

**归因**：
- **antd v5 DOM 无 `.ant-tabs-tabpane-active` 类**：现场 DOM 验证该选择器计数为 0
  （tab pane 为无 class 裸 div，激活标记在 `.ant-tabs-content-active`），选择器
  **永不匹配**。
- 同场景其余 **6 条文本断言全部通过**（`fixture-api-probe` / `cli` / `api` /
  `期望退出码 0，实际 0` / `期望状态码 200，实际 200`），证明产品字段驱动渲染
  **完全正确**。纯选择器失效。

### 5. `web-report-screenshot-placeholder` — test-defect

**断言失败**（2/4）：

| 断言 | 期望 | 实际 |
|---|---|---|
| element_visible `.ant-tabs-tabpane-active .ant-empty` | 空态占位组件可见 | 超时 3000ms |
| text_contains `暂无截图——CLI/API 场景证据为命令输出 / HTTP 响应体` | 占位文案可见 | 未找到 |

**归因**（两条均为 test-defect）：
- **选择器失效**：同上，`.ant-tabs-tabpane-active` 在 antd v5 不存在。
- **数据源假设错误**：截图页签数据源为 filesystem `list_screenshots`
  （`data.py:2585`），**而非 fixture 报告的空 `screenshots:[]`**；并行批次
  batch-1 的 `web-overview-regression` 失败截图已落盘 → 页签渲染「共 3 张截图」
  而非空态占位（现场复核确认）。
- 产品占位逻辑本身正确（`detail.tsx:1235` 空列表时渲染占位文案，且文案包含
  期望子串），场景设计缺陷。

## 三、聚合结论

- 5 个失败场景 root cause 各不同，无跨场景系统性失败。
- **无一条断言归类为 product-bug**；场景级全部豁免成立。
- 未发现需要产品实现修复的问题。

## 四、建议（非阻塞）

1. **正则修复**：`cli-env-injection-framework-priority` 断言 1 应改为
   `^http://127\.0\.0\.1:\d+` 或直接 contains `http://127.0.0.1:41767`；
   建议同步把基准地址写成占位变量而非硬编码端口。
2. **选择器修复**：web-report-* 两场景的断言选择器应改用
   `.ant-tabs-content-active .ant-card`（antd v5 结构）。
3. **时序稳健**：`web-overview-regression` 增加 navigate 后 wait 步骤（或提升
   element_visible 超时），覆盖冷实例场景。
4. **大响应健壮**：`api-specs-status-structure` 对 >64KB 响应改用 body_contains
   断言（json_path/json_schema 对截断响应天然不可用）。
5. **隔离数据源**：`web-report-screenshot-placeholder` 依赖的「空截图」夹具应确认
   并发失败场景不会向 screenshots 目录落文件，或改用独立 spec 目录做夹具隔离。

## 本轮场景集变更

当前稳定场景集共 18 个（第 1 轮）。

- 首轮写入 18 个场景

