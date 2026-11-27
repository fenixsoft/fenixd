# 提案：知识体检待人工项降噪与消费接线

## 背景

知识体检的锚点存活检查（core/knowledge.py check_anchor_references，归档 SPEC 2026-11-16-add-knowledge-anchor-lint-and-prune 交付，落地 commit a520b04e2 2026-11-08）与行数硬顶检查（LINE_CAP=150，core/knowledge_audit.py:81）产出的「待人工」发现在 dsh-plugins 已连续 11 天零消费重报：spec/knowledge/log.md 显示 11-14..11-22 连续 9 天「待人工 3」、11-23/24「待人工 4」，14 轮体检全部「修 0/转写 0」，体检留痕 commit 11-13 起连续 12 天每日一发；立项后噪面继续放大——11-25..11-27 三轮体检「待人工 37/41/38」（2026-11-27 评审探针实测 check_anchor_references 悬空 36 条为当前主因）。

锚点「悬空」中有一子类为检查器语义缺陷（2026-11-27 评审复核探针实测 36 条悬空，构成已较立项时漂移）：判定行 core/knowledge.py:889 用 is_file() 校验路径存在性，而能力页「代码锚点」段合法使用尾斜杠目录级引用——platform-abstraction.md 的 core/platform/、tests/integration/windows/ 与 windows-native-support.md 的 tests/integration/windows/ 三处目录盘上实存（原引示例页 session-advanced-search.md 已不在知识树，同型误报由现役页承接）；同文件 validate_knowledge 对 sources 目录级引用已有 is_dir() 放行（core/knowledge.py:647），锚点检查器缺对称分支。其余 33 条为两类本 SPEC 不覆盖的误报形态：跨仓引用约 25 条（fenix-dsh-dashboard-bridge/ 等兄弟仓路径，本仓根下不存在，见非目标）与概念词形 token 约 8 条（cap/grace/aging、0/1/2、N/A 等被 _ANCHOR_TOKEN_RE（core/knowledge.py:790）误当路径 token）。行数硬顶：判定机制在册且历史实例属实（stray-wip-disposal.md 曾 179>150 破顶，立项前已人工处置、页面已不在知识树），当前知识树最大能力页 112 行、行顶零实例——登记通路仍须建立，供未来破顶实例复用。

消费面：escalated→todo 聚合行→仲裁清单→300s 检查点消费的链路（归档 2026-10-07-evo-add-knowledge-audit-escalation-consumption 建成）只管辖语义初筛升级条目；锚点悬空与行数硬顶两类发现只计数+渲染（core/knowledge_audit.py:1812-1822 与 manual_items :2389-2403），不写 findings 台账、不登记 todo、不进自省输入——发现即终点；报告档位标签「待人工/定向转写」中的「定向转写」亦无实现通路。

## 目标

1. 锚点检查器目录放行：check_anchor_references 对实存目录的尾斜杠 token 不再报「锚点悬空」（is_dir 放行，与 validate_knowledge 口径对齐），消除恒定误报源。
2. 待人工发现接入登记面：两类待人工发现（锚点悬空、行数硬顶）写入项目 .fenix/todo.md 独立前缀跟踪行，沿用既有 upsert_todo_line 替换语义：发现集变化整组替换、发现修复（下轮体检不再报）自动摘除，杜绝陈旧欠账残留。
3. 报告档位标签与实际通路对齐：移除或标注无实现通路的「定向转写」措辞。

## 非目标

- 不改 escalated→仲裁→300s 消费既有链路与 findings 台账结构（归档 2026-10-07 件管辖；在途草稿 evo-add-knowledge-audit-reminder-downfreq 的提醒降频面不相交——原引短哈希 5ae00be13f08 经 git log --all 核不存在，改以目录名引用）。
- 不自动精简超限页面（历史超限页 stray-wip-disposal.md 的精简为人工动作且已处置，本 SPEC 不做知识页内容改写）。
- 不把锚点检查并入 validate_knowledge 硬门（维持归档件 D2「不进硬门、防全树折叠阻塞」设计）。
- 不为跨仓引用（兄弟仓路径）与概念词形 token 两类误报形态增加豁免/白名单机制：其登记行将驻留至人工处置，属本 SPEC 接受的可见噪声；如需降噪另立 SPEC。