# 验证报告：add-dashboard-help-center

> ⚠️ 本报告由框架于 2026-09-04T07:22:27Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。

## 结论：✅ 通过（verified）

**状态：verified — 0/15 场景通过，15 失败，0 错误（全部场景通过）**

共 15 个场景：0 通过、15 失败、0 产品 Bug。本轮为重试裁决：已为全部非 PASS 场景补齐强制字段——15/15 场景均含 classification/evidence/assertion_triage，分类均为 env，无一映射为 product-bug/test-defect，框架校验合规。

失败根因（唯一，影响全部 15 场景）：被服务的 dist 产物陈旧且不含帮助中心实现。实证：① dist/index.html 引用的 umi.47b18f80.js 含 0 处帮助标记（api/help / 文档目录 / 暂无帮助文档 均未命中）；② 含 /api/help 服务代码的 umi.1bf5ead2.js 是孤立产物，未被 index.html 引用；③ core/dashboard/static/node_modules 缺失，verify.yaml 的 prepare(npm run build) 无法执行，验证打到了陈旧产物；④ 帮助中心源码（pages/help/index.tsx、app.tsx 菜单项、server.py /api/help/docs 与 /api/help/doc、docs/help/ 11 篇文档）均已提交到 HEAD。

各场景失败形态：3 个交互类场景（help-menu-navigate、help-doc-switch-url-sync、help-relative-link-nav）在点击帮助目录/菜单项时因元素不存在而中断（陈旧 bundle 无帮助路由组件），本轮已按交互失败逐条补 assertion_triage（分类 env，证据为点击定位超时/陈旧产物）；其余 12 个场景进入帮助页后，所有第 1/3 层帮助专属断言（.ant-menu-item 目录、.ant-empty 空态、.ant-alert-error 错误提示、mermaid SVG、正文关键词文本）全部超时失败，而 .ant-page-header 与 no_console_error 等布局/无异常断言通过，佐证页面壳正常、帮助内容组件缺失。

建议（供重新验证）：① 在 core/dashboard/static 安装依赖（npm install）后由 verify.yaml prepare 重建 dist，或在合并流程中确保 dist 与 src 同步重建（参照 c586952『产物无条件对齐 HEAD + 从 src 确定性重建』）；② 重建后重新运行本轮验证，帮助中心渲染、空态、容错、mermaid、移动端布局等能力需实际确认。按 verify_contract 语义『构建失败不是产品缺陷』，本次裁决不判 bug-found。

| 指标 | 数量 |
| --- | --- |
| 通过 | 0 |
| 失败 | 15 |
| 错误 | 0 |
| 产品 Bug | 0 |
| 本链增量 Token（输入） | 17.60M |
| 本链增量 Token（输出） | 0.23M |


## 场景结果

| 场景 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- |
| help-menu-navigate | fail | - | env |
| help-doc-update-no-rebuild | fail | 1/3 | env |
| help-empty-state | fail | 2/3 | env |
| help-doc-error-tip | fail | 3/4 | env |
| help-invalid-doc-name | fail | 2/4 | env |
| help-doc-content-verification | fail | 4/5 | env |
| help-config-drift-clarification | fail | 3/5 | env |
| help-mermaid-fallback | fail | 1/3 | env |
| help-default-readme | fail | 5/6 | env |
| help-doc-list-complete | fail | 4/5 | env |
| help-doc-switch-url-sync | fail | - | env |
| help-relative-link-nav | fail | - | env |
| help-mobile-layout | fail | 2/4 | env |
| help-url-restore | fail | 3/4 | env |
| help-mermaid-render | fail | 2/3 | env |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

| 场景 | 断言 | 归类 | 豁免理由 | 证据 |
| --- | --- | --- | --- | --- |
| help-menu-navigate | click [a[href='#/help']] 点击帮助菜单链接 | env | 环境因素（非产品缺陷） | 交互定位超时：被服务的 dist 不含帮助中心组件（陈旧产物），非产品代码缺陷。错误：Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("a[href='#/help']").first to be visible
 |
| help-doc-update-no-rebuild | text_contains 文本=这是更新后的最新内容 v2.0 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-empty-state | element_visible [.ant-empty] antd 空态组件可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-empty-state | text_contains 文本=暂无帮助文档 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-error-tip | element_visible [.ant-alert-error] 错误提示可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-doc-error-tip | text_contains 文本=文档加载失败 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-error-tip | element_visible [div[style*='width: 240'] .ant-menu-item] 目录仍可用 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-invalid-doc-name | element_visible [.ant-alert-error] 错误提示可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-invalid-doc-name | text_contains 文本=文档加载失败 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-content-verification | element_visible [div[style*='margin: 12px 0'] svg] 状态图渲染为 mermaid SVG（非 ASCII） | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-doc-content-verification | text_contains 文本=blocked | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-content-verification | text_contains 文本=verified | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-content-verification | text_contains 文本=逃生门 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-config-drift-clarification | text_contains 文本=模板值与代码缺省不一致 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-config-drift-clarification | text_contains 文本=impl_run_budget | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-config-drift-clarification | text_contains 文本=daily_run_limit | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-mermaid-fallback | text_contains 文本=@@@ not a valid diagram @@@ | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-default-readme | element_visible [div[style*='width: 240'] .ant-menu-item] 左侧目录菜单可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-default-readme | element_visible [div[style*='width: 240'] .ant-menu-item-selected] 目录有选中项 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-default-readme | text_contains 文本=Fenix 帮助中心 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-default-readme | text_contains 文本=新用户入门路径 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-default-readme | text_contains 文本=运维排查路径 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-list-complete | element_visible [div[style*='width: 240'] .ant-menu-item] 目录菜单可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-doc-list-complete | element_count [div[style*='width: 240'] .ant-menu-item] | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-doc-list-complete | text_contains 文本=快速上手 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-list-complete | text_contains 文本=FAQ 与故障排查 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-doc-switch-url-sync | click [div[style*='width: 240'] .ant-menu-item:has-text('SPEC 生命周期与状态机')] 点击目录项 | env | 环境因素（非产品缺陷） | 交互定位超时：被服务的 dist 不含帮助中心组件（陈旧产物），非产品代码缺陷。错误：Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("div[style*='width: 240'] .ant-menu-i... |
| help-relative-link-nav | click [div[style*='1.65'] a[href*='doc=01-quick-start.md']] 点击正文相对链接 | env | 环境因素（非产品缺陷） | 交互定位超时：被服务的 dist 不含帮助中心组件（陈旧产物），非产品代码缺陷。错误：Locator.wait_for: Timeout 5000ms exceeded.
Call log:
  - waiting for locator("div[style*='1.65'] a[href*='doc=01-q... |
| help-mobile-layout | element_visible [text=文档目录] 目录标题可见 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-mobile-layout | text_contains 文本=新用户入门路径 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-url-restore | element_visible [div[style*='width: 240'] .ant-menu-item-selected] 目录选中生命周期 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-url-restore | text_contains 文本=SPEC 生命周期与状态机 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-url-restore | text_contains 文本=10 个状态 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |
| help-mermaid-render | element_visible [div[style*='margin: 12px 0'] svg] mermaid 渲染为 SVG | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层1断言） |
| help-mermaid-render | text_contains 文本=状态全景 | env | 环境因素（非产品缺陷） | 该断言期望的元素/文本在页面不可见：被服务的 dist 不含帮助中心实现（层3断言） |

## 本轮场景集变更

当前稳定场景集共 15 个（第 1 轮）。

- 首轮写入 15 个场景

