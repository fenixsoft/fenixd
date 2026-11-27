# 提案：知识体检待人工项降噪与消费接线

## 背景

知识体检的锚点存活检查（core/knowledge.py check_anchor_references，归档 SPEC 2026-11-16-add-knowledge-anchor-lint-and-prune 交付，落地 commit a520b04e2 2026-11-08）与行数硬顶检查（LINE_CAP=150，core/knowledge_audit.py:81）产出的「待人工」发现在 dsh-plugins 已连续 11 天零消费重报：spec/knowledge/log.md 显示 11-14..11-22 连续 9 天「待人工 3」、11-23/24「待人工 4」，14 轮体检全部「修 0/转写 0」，体检留痕 commit 11-13 起连续 12 天每日一发。

其中 3 条锚点「悬空」为检查器语义缺陷：判定行 core/knowledge.py:827 用 is_file() 校验路径存在性，而能力页「代码锚点」段合法使用尾斜杠目录级引用（session-advanced-search.md 第 69/72 行的 src/client/、src/host/、tests/ 三个目录盘上实存）；同文件 validate_knowledge 第 597 行对目录级 index 链接已有 is_dir() 放行，锚点检查器缺对称分支。第 4 项 stray-wip-disposal.md 179>150 行硬顶属实（27 提交自 23 行涨至 179 行，11-22 第 28 度回写破顶）。

消费面：escalated→todo 聚合行→仲裁清单→300s 检查点消费的链路（归档 2026-10-07-evo-add-knowledge-audit-escalation-consumption 建成）只管辖语义初筛升级条目；锚点悬空与行数硬顶两类发现只计数+渲染（core/knowledge_audit.py:1812-1822 与 manual_items :2389-2403），不写 findings 台账、不登记 todo、不进自省输入——发现即终点；报告档位标签「待人工/定向转写」中的「定向转写」亦无实现通路。

## 目标

1. 锚点检查器目录放行：check_anchor_references 对实存目录的尾斜杠 token 不再报「锚点悬空」（is_dir 放行，与 validate_knowledge 口径对齐），消除恒定误报源。
2. 待人工发现接入登记面：两类待人工发现（锚点悬空、行数硬顶）写入项目 .fenix/todo.md 独立前缀跟踪行，沿用既有 upsert_todo_line 替换语义：发现集变化整组替换、发现修复（下轮体检不再报）自动摘除，杜绝陈旧欠账残留。
3. 报告档位标签与实际通路对齐：移除或标注无实现通路的「定向转写」措辞。

## 非目标

- 不改 escalated→仲裁→300s 消费既有链路与 findings 台账结构（归档 2026-10-07 件管辖；在途草稿 5ae00be13f08 的提醒降频面不相交）。
- 不自动精简超限页面（stray-wip-disposal.md 精简为人工动作，本 SPEC 不做知识页内容改写）。
- 不把锚点检查并入 validate_knowledge 硬门（维持归档件 D2「不进硬门、防全树折叠阻塞」设计）。