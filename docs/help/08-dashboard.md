# Dashboard 使用指南

Fenix Web Dashboard（`http://localhost:8787`）是跨项目的可视化监控与运维入口。日常查看进度、处理告警、调整配置都可以在这里完成，本章按五个页面逐一讲解。

## 启动

```bash
/fenix-dashboard
```

命令会输出可直接粘贴到浏览器的访问 URL。Dashboard 进程是独立的长驻服务，由 `/fenix-dashboard` 启动或复用已有实例；目标端口被占用时由旧 dashboard 实例自动接管，不会出现两个实例抢端口。

## 侧边栏菜单

| 菜单 | 路径 | 用途 |
|------|------|------|
| 概览 | `/overview` | 跨项目状态统计、任务进度、问题、活跃运行 |
| 项目 | `/projects` | 项目列表与各项目聚合摘要 |
| 设置 | `/settings` | 配置管理、验证契约、token 预算面板 |
| 运维 | `/activities` | Administrator 活动时间线 + 人工告警处置 |
| 帮助 | `/help` | 帮助文档中心（本文档集） |

## 五页逐面板

### 概览页（/overview）

概览页是打开频率最高的一页，回答「现在整体怎么样」。它聚合跨项目的 SPEC 总数与按状态分类的计数、任务完成率（task_done/task_total）、各项目的问题计数（阻塞/告警），以及正在进行的 Agent run 列表（按类型分组）。

### 项目列表页（/projects）

项目页列出所有已注册项目，每张卡片展示 daemon 健康状态、SPEC 数、状态分布、任务进度、验证场景数与项目简介。项目级操作也集中在这里：启停 daemon（start/stop）、安装托管（install-hosting）、软删除（delete）、重新生成简介。

#### 托管态徽标与「安装托管」

每张卡片的 daemon 状态徽标按托管态三态渲染（数据字段 `daemon` + `hosting`，来自 `/api/projects` 与 `/api/overview`）：

| 显示 | 托管态（hosting） | 含义 |
|------|-------------------|------|
| `运行中` | `managed` | daemon 受 supervisor 托管，restart_request / 审批推送等文件信号有消费方 |
| `运行中·未托管` | `unmanaged` | 裸 daemon——进程在跑但无 supervisor，文件信号无人消费（存量项目典型状态） |
| `未运行` | `stopped` | daemon 未运行 |

`unmanaged` 项目的操作菜单会多出「安装托管」项：一键执行「停止裸 daemon → 经 supervisor 启动」，使其转入 `managed`（对已托管项目幂等返回、不重启）。`unmanaged` 项目上的「重启」与「审批推送」操作会被拒绝并提示先安装托管——写文件信号前必须确认有消费者，避免信号永久滞留锁死该项目后续全部审批推送。

#### 项目详情页分面（/projects/:name）

点进项目卡片进入详情页，顶部 Tabs 分四个分面：「SPEC 开发」（默认，SPEC 列表与状态操作）/「代码审查」（code-review 问题台账 + 手动触发，见前文）/「测试回归」/「Claude Code 会话」。各分面 active 门控：仅在选中时拉取数据，未选中零请求。

「测试回归」分面（`GET /api/regression/result`）按最近一次全量回归快照 `.fenix/regression/last-run.json` 渲染三态：
- **全绿（passed）**：概览卡片展示测试路径（`cmd`）、用例总数、通过数、执行时间（本地时区）、总耗时；若存在长耗时用例（单用例耗时 > `verify.yaml` 的 `regression.long_test_threshold_seconds`，缺省 8s）仍在其下展示长耗时用例表；
- **存在失败/错误/超时/长耗时**：概览之下渲染结果表格，逐条列出异常用例（用例名 / 文件:行 / 耗时 / 分类——失败 / 错误 / 超时 / 长耗时），超时用例附中止原因；
- **未执行（never_run）/ 结果不可解析（parse_error）**：展示引导态（「尚未执行过全量回归」/「结果不可解析 + 原因」），不报错、不显示空表。

分面不承载周期开关（归设置页「质量」页签），提供「立即执行全量回归」按钮（`POST /api/regression/run`，写 `.fenix/regression_request.json` 信号由 daemon 主循环消费，不在 HTTP 线程内同步跑——回归可运行 1800s）。运行中态以服务端快照的 `running` 字段为准（marker 新鲜度判定），跨刷新不丢失。

### SPEC 详情页（/projects/:name/:spec）

详情页上半部分是 SPEC 元数据：状态、优先级、创建/更新时间、分支与 error。文档区提供五个页签：需求背景（proposal）、详细设计（design）、任务清单（tasks）、验证报告、测试场景清单。

详情行工具条集中了针对单个 SPEC 的运维操作：设置优先级（1-9，P1 最高）、冻结/解冻（人工冻结为 blocked + 标记，解冻恢复）、清除错误（在线清除 error 字段并写回 STATE.md）、归档（终态 SPEC 目录移入 archive）、删除（软删除，剔除 STATE.md 条目并把目录移入 archive），以及呼叫 Admin（手动唤起 Administrator，写 admin_invoke_request.json）。

**冻结**操作会立即终止该 SPEC 名下所有在跑的 agent（包括评审、实现、验证、修复等），现场经 WIP checkpoint 保全；解冻后若保留分支有未合并提交，自动在保留分支上 resume 续做（无需从零重做）。**删除**操作会先停止该 SPEC 的所有在跑 agent 并等待终态，终态齐备后才移入归档目录；有在跑 agent 时为异步受理（API 返回 `stopping: N`，前端提示「已受理，正在停止 N 个进行中的 agent」，spec 行在完成后消失），daemon 未托管时返回 409 拒绝。

详情页还有「Hook」页签（「失败截图」页签之后），分三个区块：「生效中的 Hooks」合并展示全局 hooks 与该 SPEC 的 spec 级 hooks（来源列标注「全局/本 spec」，含启停状态）；「本 spec 的 Hooks」对该 SPEC 的专属订阅做增删改与启停，表单为订阅事件多选 + 动作下拉 + 按动作类型显隐的参数（Webhook URL / Shell 命令 / 提交信息模板 / 超时秒数 / 目标 tmux 会话）；「最近执行」展示该 SPEC 的 hook 审计尾部（时间/动作/结果/耗时/摘要，失败可见错误详情）。事件与动作的完整语义见[配置参考](09-config.md#hooks)。

### 设置页（/settings）

设置页承担配置管理职责：分项目读写受管配置键（llm / agents.models / gates.approve_mode）；查看与编辑 verify.yaml 验证契约；查看/调整 token 预算与消耗；以及管理提示词：查看通用层 agents/ 提示词、编辑项目级附加提示词。「Hook」面板管理当前项目的全局 hooks（对所有 SPEC 生效），表单结构同 SPEC 详情页的 Hook 页签，并展示跨 SPEC 的最近执行记录。

「质量」页签（内部 key `quality`，位于「验证」之后）承载代码质量门与周期性审查/回归设置，三张卡片。第一张（既有）：单个开关「收尾代码质量审查」（`verify.impl_code_review`，键路径不变）。开启后实现者在全部 tasks.md 任务完成、提交之后、写结果文件之前调用 ocr（`bin/ocr_review.py`）审查本次改动；环境未安装 ocr 时自动按 unavailable 降级跳过。该开关原置于「验证」页签，独立成页后验证页不再承载它（避免双入口）。第二张（`admin.code_review.enabled`，2026-09-19 从项目页「代码审查」分面迁来）：开关「周期性代码审查」——配置项归设置页统一管理，项目页分面只保留结果展示与手动触发。开启后与每日自省同周期派发 code-review agent，审查产品代码质量，问题入台账供项目页「代码审查」分面消费。第三张（`admin.regression.enabled`，add-test-regression-tab）：开关「周期性全量回归」——开启后与每日自省同周期自动执行一次全量回归（需项目 `.fenix/verify.yaml` 配置 `regression` 段），结果落到 `.fenix/regression/last-run.json`，供项目页「测试回归」分面展示；同一自然日防重；与 implementer 收尾的全量套件互斥（主机级锁）。手动触发（项目页「立即执行全量回归」）不受本开关约束。长耗时用例阈值来自 `verify.yaml` 的 `regression.long_test_threshold_seconds`（缺省 8 秒），属项目测试体系声明，在项目页「验证」面板的 `verify.yaml` 编辑入口中调整，本卡片不提供第二个写入路径。

开关下方另有三项运行参数设置（add-impl-code-review-tuning，键 `verify.impl_code_review_timeout_sec` / `verify.impl_code_review_concurrency` / `verify.impl_code_review_effort`，缺省 600 / 2 / `low`）：
- **审查超时（秒）**：ocr LLM 单请求超时，写入 run 级 ocr provider 配置（`custom_providers.fenix-impl.timeout_sec`），**确定性生效**——不配置时 ocr 走其内置 300s 默认，实测 8 路并发 + 300s 会撞穿首字节等待导致大面积文件级 timeout。数字输入，须正整数，单位「秒」。
- **审查并发**：ocr 并发子任务上限（`--concurrency`）。实测 8 路并发同时打同一 provider 网关会把首字节延迟放大到撞穿超时线，降到 2 以吞吐换稳定。数字输入，须正整数。
- **审查力度**：ocr 审查力度预设（`--effort`），下拉 `low` / `medium` / `high`。`low` 更快更省但 recall 偏低（ocr precision 优先的刻意取舍），`medium` 为 ocr 官方默认，`high` 深度审查。

**注意软约束**：`--concurrency` 与 `--effort` 经**提示词命令示例承载**（无持久化配置键 / 与并发同走单一通道），实现者须照抄提示词中的命令串才生效——这两项不像超时那样是硬性生效开关，若实现者改写命令形态即可能不生效；配置值只是框架注入的「建议值」。超时则写入 run 级配置、确定性生效。三项缺省值均比 ocr 官方默认（300s / 8 / `medium`）更保守：宁慢勿废，用户可随时上调。

页签顶部有一行 open-code-review 环境状态（`GET /api/quality/ocr-status`，按 `shutil.which("ocr")` 探测，与 `bin/ocr_review.py` 的 PATH 解析同源）：已安装时显示版本号并放行开关；未安装时显示橙色提示 + 「一键安装」按钮，**开关置灰不可用**（避免开启一个运行期必然降级跳过的开关）。点「一键安装」调用 `POST /api/quality/ocr-install`，后端执行 `npm install -g @alibaba-group/open-code-review`（固定字面量，无用户输入拼接，不做提权）——成功后重新探测并解锁开关，失败（如权限不足 EACCES）返回 400 并把 npm 报错末尾透出，用户可自行 `sudo npm install -g @alibaba-group/open-code-review` 安装后刷新页面。**后端不拦「未安装时保存 `impl_code_review: true`」**：存量已勾选的配置不应因环境探测而保存失败，运行期降级语义保持不变。

「自进化」页签（原「自愈」改名，内部 key `self-evolution`）下自上而下两张卡片，页签内容最下方为**唯一**的右对齐「保存」按钮——点击后一次提交同时写回两节配置（`stale_code_selfheal` + 用户级作用域下的 `self_evolution`）；两张卡片内均不自带保存按钮：
1. **代码陈旧自愈**（既有 `stale_code_selfheal` 面板，配置键/缺省值/控件全部不变）：`enabled` 开关（缺省开启）与 `idle_confirm_seconds` 连续空闲确认秒数（缺省 120），附语义说明——陈旧状态 + 启用 + 托管 + 连续空闲达到阈值后 daemon touch `.fenix/restart_request` 触发优雅重启；未托管项目不自愈、仅维持陈旧告警。保存经页签底部唯一按钮，非法值（非布尔 / 非正整数秒数）被后端拒绝返回可读错误。
2. **建议改进项**（新增 `SuggestedImprovementsPanel`）：标题「建议改进项」位于卡片外（与第一张卡片同构），其下为功能注解；卡片内为全局配置控件——「允许框架自改进」开关（`self_evolution.auto_accept`，缺省关闭，开关与名称同行不换行）与「每轮分析条目上限」数字输入（1..200，缺省 20，独占一行、后缀单位「条」），两者下方各有功能注解。用户级作用域可保存（写用户级配置）；项目级作用域下两项置只读并提示「全局键，请在用户级作用域修改」，此时底部保存按钮仅提交项目级可写的 `stale_code_selfheal`。配置表单之外另有全局动作按钮「清理所有项目自省内容」（实心红底白字告警样式，项目级作用域下禁用）：二次确认后调用 `POST /api/evolution/clear-todo`，把所有已发现项目的 `.fenix/todo.md` 截断为空文件（保留文件本体），只清这一份自省文本——下方条目列表读的是 `items.jsonl`，不受影响；也不代各项目提交 git，清空结果由下一次每日自省一并提交。无 `todo.md` 的项目计入「跳过」，单个项目失败不中断其余，完成后提示「已清空 N / 跳过 M / 失败 K 个」。其下为跨项目建议改进项表格，列序：项目 / 日期 / 类别 / 问题 / 评估结论 / 状态 / 操作，默认按入库时间倒序；状态中文映射：待决策 / 不需要立项 / 草稿生成失败 / 已同意 / 已自动接受 / 已拒绝 / 接受失败。操作列「更多」下拉提供查看分析结论 / 查看 SPEC 草稿 / 同意 / 拒绝（拒绝为危险项），同意与拒绝均需二次确认弹窗；「查看分析结论」在抽屉中渲染评估结论全文（含三项判定与证据）；「查看 SPEC 草稿」可切换 proposal / design / tasks / spec 四类文档。移动端表格横向滚动 + 操作列固定右侧（不做卡片式降级）。

### 运维记录页（/activities）

运维记录页是告警处置的工作台。自动运维视图展示 Administrator 的活动时间线（处置记录与结果标签）；人工告警视图列出未处理的升级告警并提供「标记已处理」操作。页面顶部的横幅汇总跨项目未处理告警总数，每条告警都带有信号类型、严重度、证据与建议。

## 帮助页自身用法

「帮助」菜单（运维之下）进入本文档中心。桌面端左侧是文档目录（选中高亮），右侧为 Markdown 正文；移动端（<768px）正文置顶，通过顶部「文档目录」按钮打开抽屉切换。URL 采用 `#/help?doc=<name>` 形式，可以直链到具体文档，刷新或分享都不会丢失；目录点击与正文内相对链接均可完成页内切换。

## 安全边界

Dashboard 仅绑定 `127.0.0.1`，不对公网开放；同时它没有鉴权机制，因此不要把端口暴露到公网或不可信的内网网络。所有 API 均有防穿越校验与错误容错，不会因异常数据而 500。

## 相关文档

- [帮助中心首页](README.md) — 返回本帮助中心
- [核心概念与架构](02-concepts.md) — 多项目机制
- [配置参考](09-config.md) — Dashboard 设置页与配置键映射
