<!-- knowledge: capability=spec-detail-bento-skin rev=1
     sources=spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md -->

# SPEC 详情页 Bento 皮肤

现产 SPEC 详情页（`/projects/:name/:spec`）的 Bento 视觉皮肤层：顶栈五卡磁贴化、任务清单与质量门禁行渲染镜像 v2 形态、时间轴节点磁贴化；只动呈现层，页面内容与交互契约零改动，数据语义色不随视觉换轨。

## 规则

- **顶栈五卡 Bento 皮肤**：项目信息、任务清单、质量门禁、验证进度、验证结论五张顶栈卡挂 global.less 单源覆写类 `.spec-bento-card`（白磁贴发丝边 + 12 圆角 + 软阴影；同特异性规则靠后置覆写页级去边框/去阴影规则）；卡内内容与交互零改动。
- **页签区不入 bento**：页签区包裹卡不挂 bento 皮肤（tab 菜单避免卡套卡）；包裹卡卡体 padding 归零（`.spec-detail-card > .ant-card-body { padding: 0 }`）——隐形包裹卡「去边框」不消内边距，默认 24px 内边距会使页签内容比上方 bento 卡左右各多缩进一圈，对齐问题查卡体不查边框；窄屏 12px 收紧规则特异性更高，不受波及。
- **任务清单行渲染=镜像 v2 TaskCard**：分组行为三阶灰摘要「标题 · done/total」；条目行为完成蓝底勾选块（`.ov-task-check`，镜像 `.v2-task-check`）或未完成指示器 + mono 编号（链接蓝）+ mono 描述，行间发丝线分隔（`.ov-mono` 镜像 `.v2-mono`）。未完成指示器为空心方框（`.ov-task-empty`，15×15 radius 4 与勾选块同几何）系用户指令偏离镜像源（v2 原形空心圆），不应对齐回圆。v2 的 8 行折叠渐进披露未采纳——本页内容保持原版全显；run 线索与空态 testid（run-progress-hint 等）原样保留。
- **质量门禁行渲染对齐任务清单**：勾选块/空心方框指示器 + 发丝线行分隔 + 13px 文本块；状态数据语义保留（failed 红 / pending·unknown 灰的 gateTextColor、状态后缀、detail 文案）；antd Checkbox 在本页退役（import 移除）。
- **时间轴节点=独立磁贴**：SpecTimeline 卡体改 Bento 形态（发丝边 + 12 圆角 + 软阴影 + 纯白底）；urgent（失败 run/门禁拒绝）警示描边与红软底保留——数据语义色不随视觉换轨。任务进度列计数「xx/xx · 百分比」与左侧阶段名同款（12px 三阶灰常规字重，不走 v2 深色半粗形态）。

## 溯源

- 2026-11-06 overview-ledger-bento-align-1106（spec/knowledge/_inbox/done/overview-ledger-bento-align-1106.md） — 新建本页：spec 详情页 Bento 化（内容保持原版）——顶栈五卡 .spec-bento-card 皮肤、页签区退出 bento 与包裹卡卡体 padding 归零、任务清单行渲染镜像 v2 TaskCard（空心方框为用户指令偏离）、质量门禁行渲染对齐任务清单（antd Checkbox 退役）、时间轴节点磁贴化（urgent 语义色保留）
