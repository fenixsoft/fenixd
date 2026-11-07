# 知识真相源
> 最后更新：2026-11-07 22:03 UTC+8

本项目知识按**能力域**组织：域内一能力一页，只装当前生效的业务规则；
历史演变见各页「溯源」段与 `spec/archive/`。能力页由存量回填批次逐步产出，
各域导航页先行登记能力条目（能力页落盘后升级为链接）。

## 能力域

| 能力域 | 简介 | 能力数量 | 更新时间 |
| --- | --- | --- | --- |
| [project-management](domains/project-management/_domain.md) | 项目的发现接入、描述信息与生命周期控制（daemon 启停 systemctl 双轨/软删除）。含项目初始化骨架播种与针对 SPEC 的冻结/删除停止语义。 | 8 | 2026-11-05 04:11 |
| [planning-generation](domains/planning-generation/_domain.md) | SPEC 的原生生成链路：从需求澄清到 proposal/design/tasks 成文。planner 出题阶段的产物硬门、契约情报与性能治理同属此域。 | 6 | 2026-10-03 04:59 |
| [ui-prototyping](domains/ui-prototyping/_domain.md) | 界面原型确认环：SPEC 起草阶段用「真组件、假数据」的高保真原型对齐界面意图，浏览器批注迭代至批准入库。批准后以双通道契约约束后续 AI 实现与评审（原型纯视觉参照、无约束力），原型控制台 vendor DEV 警告非缺陷判读。 | 3 | 2026-11-07 21:53 |
| [spec-lifecycle](domains/spec-lifecycle/_domain.md) | SPEC 全生命周期：起草评审门（spec-review）与驳回恢复、晋升（含中文标题晋升硬门）/手工激活/定时解冻调度、并发治理与内容完整性门。归档链（手工/自动归档、归档态迁移与自动提交）与 fast-track 模式选择、状态机模型、立项与成文定调、SPEC 中文标题（display name）也在此域。 | 26 | 2026-11-06 20:15 |
| [dispatch-scheduling](domains/dispatch-scheduling/_domain.md) | SPEC 并发槽位与优先级调度、队列老化、依赖唤醒与兜底恢复。即时唤醒信号与事件投递完整性、秒挂冷却派发门控也在此域。 | 9 | 2026-10-30 23:11 |
| [implementer-lane](domains/implementer-lane/_domain.md) | 实现车道的任务协议与交付物门禁：tasks.md 进度同步/回写、验收偏差申报、结果文件契约与自检、回归委托。交付物声明与归属仲裁（声明分诊/争议治理/搬迁回写）、WIP 检查点与任务产物归属也在此域。 | 28 | 2026-11-04 17:07 |
| [verify-pipeline](domains/verify-pipeline/_domain.md) | 验证管线全链：runner 引擎与场景生命周期、验证环境预检与依赖供给、serve 范围矩阵与实例回收。场景冻结/打捞/schema 单源、多形态场景模型（web/cli/api）与资源互斥、视觉基线与并行回退、验证报告门与证据分级留存也在此域。 | 59 | 2026-11-04 17:07 |
| [verdict-adjudication](domains/verdict-adjudication/_domain.md) | 验证裁决与证据：裁决产物的产生与门检、证据分类与归因可信度、裁决结果与失败语义。查重与重合成、缓存复验、env 类失败的豁免握手与场景修订处置出口、judge 场景修复写回受理门，以及裁决在 Dashboard 的可见性。 | 27 | 2026-11-03 20:35 |
| [code-review-lane](domains/code-review-lane/_domain.md) | 周期性代码审查车道：注册/调度（夜间静默窗跨窗顺延）、scope 两档、分片直写落盘、进度聚合与停滞看门狗。审查发现台账与质量分面（快照核销/三态分派）、发现转修复 SPEC 生成、全仓审查并发约束与限流终局续跑。实现期收尾 ocr 审查（异步车道 + join 门）及其配置调优。 | 19 | 2026-11-04 16:55 |
| [code-fix-lane](domains/code-fix-lane/_domain.md) | 缺陷修复车道：两路激活与批循环编排、批内并行处置（orchestrator 派子代理、单写者落盘、三级兜底）、批收尾回归门与失败明细映射。回归异常熔断与零失败面收口、修复批自愈重试预算分档、合回冲突定向救回、夜间静默窗投递守卫、审查发现分级修复节奏与轻微缺陷快车道。 | 27 | 2026-11-04 17:07 |
| [agent-runtime](domains/agent-runtime/_domain.md) | Agent 进程托管与信号处理、非交互运行契约、提示词文件化。run 产物留存、超时与轮次上限生命周期、提示词层效率治理。 | 17 | 2026-11-04 17:07 |
| [harness-integration](domains/harness-integration/_domain.md) | 多 harness 接入：以进程边界为唯一接缝（SpawnSpec 进、归一化事件出），把「换 harness」收窄为「实现 adapter + 部署注册」。HarnessAdapter 协议与 claude 字节级平移、fenix-dsh Bundle 与 DshAdapter 事件投影、切换治理。run jsonl 以 claude stream-json 形状为唯一 canon；dashboard 自由会话与 CLAUDE_PID watchdog 为显式豁免面。 | 6 | 2026-11-05 20:50 |
| [run-resilience](domains/run-resilience/_domain.md) | 运行守护与失败韧性：超时监督与挂死判别、失败分类与错误归因降噪、失败计数与预算分档。运行清扫、重派循环治理、诚实退出收敛、状态写原子性与幂等、孤儿态探测、CLI 重试退避与环境阻塞止损。 | 30 | 2026-11-04 16:30 |
| [recovery-continuity](domains/recovery-continuity/_domain.md) | 中断恢复与续做：daemon 中断、停机与重启后的完整恢复链——现场保全、保留分支续做、存活核验、遗留处置。恢复监视告警、取消保持恢复与验证断点。 | 14 | 2026-11-04 09:33 |
| [worktree-vc](domains/worktree-vc/_domain.md) | 实现工作树的隔离、播种、回读与卫生：spec 锁终态释放与陈锁清扫、已合并分支宽限期自动回收、分支基线解析单源口径。实现分支合回主树与推送的全生命周期纪律；主树 WIP 占用归因单源、周期盘点与滞留升级、untracked 散件自动认领、白名单文件脱落巡检。 | 30 | 2026-11-06 18:06 |
| [daemon-runtime](domains/daemon-runtime/_domain.md) | daemon 进程生命周期、单例与托管链、启动序列与排水语义。托管链 systemd 承载层（unit 安装、on-failure 重启策略与 supervisor 退出码协议、EnvironmentFile 环境承载）同属此域。结构化日志单事件读写治理。宿主环境已知脆弱面登记。 | 16 | 2026-11-06 18:13 |
| [provider-models](domains/provider-models/_domain.md) | LLM provider 注册表与角色模型分配、候选链与 failover、瞬断治理与熔断。计费配置、分级配置与设置界面的配置体系、Provider 手动健康检测。 | 19 | 2026-11-04 16:30 |
| [cost-observability](domains/cost-observability/_domain.md) | run 成本采集与本地计价、预算与费控治理。延迟/进度/耗时观测、run 记录流呈现可读性与产物保留策略。 | 14 | 2026-11-04 16:30 |
| [dashboard-frontend](domains/dashboard-frontend/_domain.md) | 跨项目仪表盘前端：项目/规格列表与详情页签、时间轴与活动记录、主题与布局改进。v2/v3 页面族（总览/项目列表/规格详情/配置/告警活动/设置）、大屏拓扑与指挥中心台面、全站统一标题栏与页头退役、嵌入挂载与 harness 品牌投影、内容区留白与边框治理、帮助/设置页文档级滚动统一、dsh 面板桥「项目」菜单行折叠开关、v2 商业化界面域（Bento 磁贴工作台六页桌面+移动双形态，例外域并存）、设置功能全表面命名「配置」避让 dsh 官方「设置」、antd 表格限高滚动与 sticky 纪律（台账磁贴不限高、「5 行封顶」落 dsh web 侧栏）与侧栏子菜单限高滚动、布局 chrome 底色 soft 染色统一（顶栏玻璃保留、菜单实底）、一般域 Bento 视觉对齐（overview 台账磁贴、projects 表格与 spec 详情/settings/指挥中心卡框、跨域镜像不引用、磁贴圆角全站 12px）、v2 六页标题栏经 titleBar 槽位并入统一控件（移动行壳位并入顶栏、副标题移动端隐藏）与 v2 白底变体三档（overview/projects 满宽 30px、help 仅白底）、v2 项目详情页六分面页签/状态筛选单源/分页对齐现产、v2 帮助正文标题去重（正文 H1 唯一）、SPEC 列表与 v2 SPEC 表名称列中文副标题、SPEC 列表整行点击进详情与 SPEC 详情标题栏中文标题下方行（贴排、两列结构标签簇随块居中、移动端只显标题与返回箭头隐藏）、SPEC 列表移动端卡片流与筛选编排改版（<768px 磁贴卡流七行层级、状态 chips 黑底白字、筛选底部 Drawer、加载更多分页与内容区背景白底单源）、dsh 设置 UI 壳层契约与设置停靠插件（settings 弹窗壳结构与稳定钩子面、useModalLayer 语义边界、停靠页面化三规）、dsh web 连接基线与重连环判读（浏览器 API 基线双门槛、低版本恒「重新连接中」症状签名、tcpdump 取证）、dsh web 对话框宽表横向滚动治理（wide/fill 分流、bleed 公式无下限缺陷、全宽覆盖须同步列宽变量、margin 夹紧、哈希类失配回退、活站验证配方）、v2 运维页页面级规则独立成页（v2-ops-page：三页签 `?tab=` 预选、五项统计标题栏副标题、三路失败隔离、移动端忌卡中卡与去嵌套磁贴直接行呈现）、顶栏动作区 min-width 棘轮锁独立成页（global.less 单源恒零化勿删、SPA 切页残留锁宽挤压标题签名与排查定式）。 | 54 | 2026-11-07 22:03 |
| [dashboard-platform](domains/dashboard-platform/_domain.md) | 跨项目 Web 仪表盘的服务端与平台层：独立服务进程、实例生命周期（unit 承载接管豁免与承载形态双轨重启协议）、增量数据管线、实时会话、前端壳层基建。按需生成类任务、协作拓扑派生与跨项目聚合端点、指挥中心聚合。 | 25 | 2026-11-06 18:13 |
| [mobile-adaptation](domains/mobile-adaptation/_domain.md) | dashboard 前端在窄屏视口（<768px）下的适配规则：断点统一、信息密度、触控目标、渐进披露与越界布局优先。 | 8 | 2026-11-07 21:43 |
| [admin-ops](domains/admin-ops/_domain.md) | Administrator 自愈 agent、健康监视与异常探测、处置留痕与运维记录视图、维护型工作登记台账。人工裁决选择题、告警生命周期与自解释叙事、请求型信号前置探测闭环、孤儿处置生效核查收敛。升级处置链（Admin→Arbiter→人工）的路由配额与链痕协调、链上处置台账即时闭合与 choice 链上执行、可观测配置、Arbiter 自主裁决车道。 | 34 | 2026-11-05 18:19 |
| [self-evolution](domains/self-evolution/_domain.md) | 每日定时自省与聚合口径、框架自进化车道（条目复核与 SPEC 起草立项）、产物契约校验与部分接受、架构师 agent。陈旧代码自愈及其冷却保护、关键路径陈旧预检、todo.md 写路径防护、arbiter 立项通道退役注记。 | 18 | 2026-11-04 17:07 |
| [test-engineering](domains/test-engineering/_domain.md) | 测试套件自身的结构、隔离与守卫。全量回归的声明、执行与展示。 | 14 | 2026-11-04 16:11 |
| [codebase-structure](domains/codebase-structure/_domain.md) | core 后端代码的结构组织与结构类重构纪律：包分层、门面转发契约、巨型类与超长函数拆分。 | 4 | 2026-10-03 04:59 |
| [time-semantics](domains/time-semantics/_domain.md) | 全链时间语义：时间原语单源、时区分层约定（存储 aware UTC / 渲染本地）、naive 时间戳唯一解读策略。静态守卫防回潮与存量调用点迁移稳态。 | 2 | 2026-11-04 15:55 |
| [docs-help](domains/docs-help/_domain.md) | 面向人类的框架使用文档体系：`docs/help/` 文档集的内容契约。Dashboard 帮助中心功能与保障机制专章。 | 5 | 2026-11-07 21:43 |
| [knowledge-atlas](domains/knowledge-atlas/_domain.md) | 知识真相源（`spec/knowledge/`）子系统：目录契约、归档蒸馏管线与 `_inbox/` 候选区回填管道、ADR 决策索引、项目知识页签与配置开关等机制能力。存量回填、周期体检、Graphify 关系图等维护车道，以及六车道与交互会话的 index-first 消费纪律；真相源只装当前生效业务规则，归档 SPEC 承担历史职责，两者以溯源链接互指。 | 13 | 2026-11-06 17:49 |
| [build-gates](domains/build-gates/_domain.md) | 仓库构建层面的前置把关：交叉编译检查等编译级门禁，在提交前与实现 run 收工自证前拦截构建类缺陷。 | 1 | 2026-10-12 08:31 |

## 决策记录

- [ADR 索引](adr/index.md) — 跨 SPEC 架构级决策（编号、状态、一句话摘要）

## 记忆回填（存量蒸馏）

交互会话的隐性知识层（Claude Code auto-memory，仓外
`~/.claude/projects/-root-fenixd/memory/`，250 文件存量）经候选区回流真相源：
2026-11-04 完成存量蒸馏预筛，投递 6 条合集入 `spec/knowledge/_inbox/`
（运维取证手册 / 诊断噪音签名 / agent 提示词与测试规则 / 用户定调 / 开放缺口 /
未走 SPEC 已落地规则，git:c5076028e）。各条由蒸馏轮折叠进相应能力页
（piggyback），折叠轨迹见 `log.md` 与各能力页「溯源」段；折叠完成后更新本节
入库状态。

入库状态（2026-11-04 17:07）：「agent 提示词与测试规则」「诊断噪音签名」
「开放缺口」「运维取证手册」「未走 SPEC 已落地规则」「用户定调」已折叠入库（第一条 spread 至
agent-runtime / test-engineering / worktree-vc / implementer-lane / daemon-runtime
五域七页；第二条 spread 至 run-resilience / provider-models / cost-observability /
self-evolution / verify-pipeline / worktree-vc / time-semantics / test-engineering /
dashboard-frontend 九域十页；第三条 spread 至 daemon-runtime / worktree-vc /
knowledge-atlas / spec-lifecycle / test-engineering 五域六页，含新建
host-env-hazards 页；第四条 spread 至 run-resilience / cost-observability /
daemon-runtime / project-management / spec-lifecycle / worktree-vc /
provider-models / dashboard-platform / verify-pipeline 九域十五页，存量规则
已被前三条覆盖的部分不重复折叠；第五条 spread 至 code-fix-lane /
code-review-lane / dashboard-platform 三域五页，其「治理判定」段各项经核对
已见诸既有能力页不重复折叠；第六条 spread 至 spec-lifecycle / mobile-adaptation /
dashboard-frontend / agent-runtime / project-management / self-evolution /
implementer-lane / worktree-vc / code-fix-lane / verify-pipeline 十域十页，含新建
spec-authoring-conventions / mobile-overflow-layout-first / page-container-chrome
三页；自省条目标准与调查评估纪律、自省调度自然日语义、429 解耦、
escalation_cooldown 缺省、告警降噪分级与 token 预算档位、多 harness 进程边界
接缝、真相源只装当前规则、evo 草稿四步连做与立项两硬约束、禁止自动创建 SPEC
等定调经核对已见诸既有能力页不重复折叠）；另有
command-center-light-embed-migration 已折叠入库（2026-11-04 17:37，spread 至
dashboard-frontend 一域一页：command-center-console-ui 整页改写为三屏嵌入形态）；
distill-econnreset-misattrib-recover-sweep-race 已折叠入库（2026-11-04 17:46，spread 至
knowledge-atlas / daemon-runtime / dashboard-frontend 三域三页，含新建
run-visual-agent-labels 页）；bridge-projects-row-toggle-1105 已折叠入库
（2026-11-05 18:14，spread 至 dashboard-frontend 一域一页：新建
dsh-bridge-projects-section 页）；embed-titlebar-frosted-glass 已折叠入库
（2026-11-05 18:27，spread 至 dashboard-frontend 一域两页：
unified-page-title-bar 行壳位改写双档形态并新增 embed 档毛玻璃固定标题带规则、
dashboard-embed-mount 嵌入态标题行形态句随迁）；
settings-help-document-scroll-unify 已折叠入库（2026-11-05 20:37，spread 至
dashboard-frontend / docs-help 两域五页：新建 document-scroll-unify 页、
unified-page-title-bar 定高偏移口径改写（settings/help FRAME_OFFSET 条目消失、
对象收敛项目详情页框与指挥中心）、page-container-chrome 新增 children 容器
padding-block-end 归零规则、v3-settings-page 与 help-center 布局句随迁）；
settings-menu-renamed-config-1105 已折叠入库（2026-11-05 20:45，spread 至
dashboard-frontend 一域一页：v3-settings-page 新增全表面命名规则——统一「配置」
避让 dsh 官方「设置」、四处标签同步面、路由/深链/条目 id 不改名、
docs/help 措辞残余登记）；systemd-hosted-daemon-path-missing-local-bin 已折叠入库
（2026-11-05 20:50，spread 至 daemon-runtime / harness-integration 两域三页：
systemd-hosting 环境承载规则改写——env 文件必须真实落盘与最小集
PATH/HOME/USER/LOGNAME/IS_SANDBOX=1、denylist 语义边界（IS_SANDBOX 属捕获侧
误伤面）、host-env-hazards 新增 spawn 层失败三查判读、agent-harness-adapter
新增 claude spawn env 恒注入 IS_SANDBOX=1 兜底规则）；
antd-table-scroll-maxheight-sticky-th-1106 已折叠入库（2026-11-06 16:51，
spread 至 dashboard-frontend 一域一页：新建 project-ledger-bounded-scroll
页——台账磁贴桌面约 5 行封顶、限高层钉 .ant-table-content、sticky 钉
thead>tr 白底铺 tr、827px 真实行高校准口径、v2/ov 两域镜像同改与
pageChrome 守卫、几何证据验证配方）；chrome-soft-solid-titlebar-1106 已折叠入库
（2026-11-06 16:55，spread 至 dashboard-frontend 一域两页：新建
layout-chrome-tinting 页——顶栏毛玻璃只换 rgb 通道双档与 colorBgScrollHeader
必随配、菜单侧栏 soft 实底平涂一体、三处边框同取 colorSplit、soft 染色族
守卫；unified-page-title-bar 玻璃守卫表述改钉族通道一致与透明度 <1）；
distill-batch-fold-tax-and-artifact-no-content-1106 已折叠入库（2026-11-06
17:04，spread 至 knowledge-atlas 一域两页：knowledge-inbox-pipeline 新增
折叠耗时税语义（每条完整子 run 2–8 分钟、与当轮蒸馏串行、批次耗时随积压
线性膨胀、空折叠夹具同价）与编年账权威口径（run 自写 fold 行可能重复、
事实对账以 git 提交为准）、knowledge-distill-pipeline 新增批耗时口径
（单 SPEC 基准约 10 分钟、长批由折叠税主导）与 run 观测面缺口登记
（事件流只记 started/heartbeat/round/result、result 行无改动文件清单、
产出取证走 git log）及 _inbox 常驻 untracked 条目触发基线 WARNING 的
已知误报面）；overview-ledger-bento-align-1106 已折叠入库（2026-11-06
17:11，spread 至 dashboard-frontend 一域八页：dashboard-overview 项目清单
改台账表格磁贴（ProjectTable 双形态、行为契约不随视觉切换、统计卡 Bento
皮肤与移动 2×2、运行态 Radio 黑底白字、数字列居中）、dashboard-spec-table
DevTab 桌面表格 v2 重绘非替换（操作列三点+「文档」并入菜单首项、行内容
v2 形态、类型过滤与归档切换 Radio 组）、v2-commercial-ui 磁贴圆角改 12px
通用条款与跨域镜像不引用纪律与筛选形态分叉、v3-settings-page 全量卡
Bento 边框（灰底准例仅此一页）、command-center-console-ui 五类卡片框
Bento 形态、page-container-chrome 页面内容区间距条款（15px + 呼吸带
16px）、quality-gates-progress 门禁行渲染形态随迁，含新建
spec-detail-bento-skin 页）；v2-overview-titlebar-white-variant-1106 已折叠入库
（2026-11-06 17:24，spread 至 dashboard-frontend 一域三页：
unified-page-title-bar 行壳位收敛 embed 单档（移动端标题并入 ProLayout 顶栏、
副标题移动端隐藏）并新增 v2 六页 titleBar 槽位并入条款、v2-commercial-ui
新增白底变体三档与标题栏并入与运行态筛选胶囊语言与移动等宽钳制条款、
v2-overview-page 整页改写 Bento 工作台现状（史前统计块/项目卡/SSE 重拉规则
废除））；v2-projects-page-parity-1106 已折叠入库（2026-11-06
17:35，spread 至 dashboard-frontend 一域两页：新建 v2-project-detail-page
——白底满宽 projects 变体页级形态、标题 titleBar 槽位声明形态（back 回
/v2/overview、项目名、共 N SPEC · M 活跃 TitleBarNum）、状态筛选
LIST_STATUSES 全 11 态单源与 antd 256px 虚拟滚动非缺陷口径、分页
20/showSizeChanger/showTotal 与移动卡片流不分页、页签六分面复用现产组件
（project+active 门控按需加载、PlaceholderPane 退役）与选中态内存态不引入
URL tab 契约；v2-commercial-ui 项目详情关键行为行改写（标题带→统一标题栏、
四页签→六分面）与 v2TitleBarGuard 剥注释扫描习语登记）；v2-titlebar-slot-white-dedupe-1106
已折叠入库（2026-11-06 17:42，spread 至 dashboard-frontend 一域一页：
v2-commercial-ui 帮助关键行为行改写——白底 variant="white" 与「帮助中心 ·
N 篇文档」titleBar 声明落行、新增正文标题去重条款（DocPane 不渲染自动
doc.title、后端 title 本从 markdown 首个一级标题解析、正文 H1 唯一、slug
锚点不受影响、守卫钉死）、移动帮助行「目录」按钮改经 filters 槽位落顶栏；
本条余项（titleBar 槽位挂法、白底变体族、副标题移动端隐藏、剥注释守卫习语）
经核对已由前两条入库条目覆盖不重复折叠）；antd-table-scroll-maxheight-sticky-th-1106 更新版（17:43 条目，16:51 首折版本的台账限高落地被撤销）已折叠入库（2026-11-06 17:54，spread 至 dashboard-frontend 一域四页：project-ledger-bounded-scroll 整页覆盖重写——台账磁贴不限高定案、antd 限高/sticky 实测纪律留存；新建 sidebar-submenu-bounded-scroll——独立侧栏子菜单 5 项封顶 200px 与定制滚动条及 overlay 引擎量宽判据；dsh-bridge-projects-section 增补分区 5 行封顶 182px、滚动条定制与官方 Workspaces 列表同款；dashboard-overview 台账细则句改不限高口径）；mergeback-consumer-rehearsed-repair-gap-1106 已折叠入库（2026-11-06 18:06，spread 至 worktree-vc 一域两页：merge-rehearsal 新增直通 repair 接线边界条款——同型接线仅存于实现主路径 merge-back 站点、周期消费者 merge-only 重试路径未接线为已登记框架缺口；wip-defer-merge-retry 新增语义冲突形态条款——消费者失败路径清标志走真失败通道可落指纹熔断/降级复位清锚点、接线前 admin 人工 SOP 覆盖（定点收编+手工 merge+镜像 _finalize_merge_success 清账）与补接线方向复用 _direct_rehearsed_to_repair）；push-restart-unit-absent-tmux-stale-1106 已折叠入库（2026-11-06 18:13，spread 至 dashboard-platform / daemon-runtime 两域三页：dashboard-push-restart 新增 tmux 托管兜底形态盲态规则——unit 缺席静默跳过使 pushed 重启对 tmux 常驻实例永不可达且无审计留痕、两向收口方向（补装 unit / unit 缺席分支加 tmux 探测+respawn+审计）；dashboard-instance-lifecycle 重启协议改写为承载形态双轨——unit 缺席时 tmux 轨 `respawn-window -k` 为实测有效路径、验证三件套第三件改 API 读侧新字段有值、陈旧进程判读一般化（读侧字段恒旧+全新进程对照+ps -o lstart 对比合入时间）；host-env-hazards 新增 dashboard unit 缺席 tmux 兜底常驻环境实态登记与收口销账义务）；
dsh-settings-dock-plugin-1107 已折叠入库（2026-11-07 21:32，spread 至
dashboard-frontend 一域一页：新建 dsh-settings-ui-contract 页——dsh 0.2.0-rc.2
设置弹窗壳结构与 settings.section 插槽、稳定钩子面（data-shortcut-modal/
sidebarCol/把手收缩态卸载/rightbar/`<hash>_section`）、useModalLayer 只管文档级
Esc+焦点圈不拦指针与 aria-modal 不可翻转（closeTopModal 消费）、侧栏宽度 JS
驱动无 CSS 变量与收缩态 56px 窄轨与触发按钮幂等开无 toggle、停靠页面化三规
（overlay 放行后子面板 pointer-events:auto 取回、测量锚选全形态在场元素把手只当
兜底、capture 阶段合成 Esc 收页+触发按钮 stopPropagation toggle 代管））；
dsh-web-stale-asset-reconnect-loop-1107 已折叠入库（2026-11-07 21:36，spread 至
dashboard-frontend 一域一页：新建 dsh-web-connection-baseline 页——dsh web 连接
基线与「重新连接中」重连环判读（浏览器 API 基线双门槛 Promise.withResolvers/
AbortSignal.any 与各内核版本线、低版本症状签名 101 正常零业务帧与 close(4000)
退避回环、close 4000 为下游症状非病灶、健康握手对照、服务端/cookie/frp 排除面、
console 优先与 tcpdump 取证纪律、无能力探测开放缺口登记））；
dsh-web-wide-table-horizontal-scrollbar-1107 已折叠入库（2026-11-07 21:40，
spread 至 dashboard-frontend 一域一页：新建 dsh-web-wide-table-scrollbar
页——wide/fill 分流与对称出血公式机制链（无下限缺陷、未报上游插件侧补偿）、
全宽覆盖列宽变量同步义务与溢出传播链、退化路径 margin 夹紧与变量作用域纪律、
哈希类失配自动回退官方布局、变量探针/样式表归属/活站假设验证配方与干净态
终验口径）；mobile-ui-fixes-1107 已折叠入库（2026-11-07 21:43，spread 至
dashboard-frontend / docs-help / mobile-adaptation 三域七页：dashboard-spec-table
移动内容区背景色改白（SPEC_LIST_MOBILE_BG 单源值 #E3E3E3→#ffffff、灰底衬托
退役）、command-center-console-ui 新增移动端双过滤落内容区首行（槽位不注册、
项目 Select flex:1 + 时间窗定宽 100）、unified-page-title-bar 过滤项条款补
移动端 filters 槽位单一定点定式（上移标题栏一律走槽位、不在内容区手画按钮行）、
v3-settings-page 新增标题栏作用域控件移动端瘦身（标签不渲染、Select 移动档
130）、help-center 移动端目录按钮迁 filters 槽位抽屉化、mobile-detail-header-density
顶栏与富标题载体对齐现行契约（旧顶栏纯品牌/行壳位表述废除）、mobile-adaptation
新建 mobile-regression-actions-stacking（回归页签概览三按钮移动端纵排）；
ops-mobile-nested-bento-removal-1107 已折叠入库（2026-11-07 21:53，spread 至
dashboard-frontend / ui-prototyping 两域三页：新建 v2-ops-page——v2 运维页页面级规则
（三页签处置链缺省与 ?tab= 仅认 auto/alert 预选、五项统计入 titleBar subtitle、
处置链四块观测与人工队列、自动运维记录真实端点 /api/admin-activities 服务端
分页 15/页、告警裁决与已解决折叠区、Promise.allSettled 失败隔离、移动端去嵌套
磁贴直接行呈现、分隔线 V2_SPLIT/V2_HAIRLINE 保色、V2AlertRow 与 overview 共用
行 prop 分支纪律 overview 零变化）；v2-commercial-ui 新增移动端忌卡中卡条款与
双形态分支共用组件 prop 分支纪律、原型真相源条款登记 m-ops.html 2026-11-07 r2
重绘版、运维关键行为两行改写（四项统计条→五项统计副标题、自愈记录占位→真实
端点三页签）；prototype-annotation-loop 新增控制台噪音判读条款——vendor React
DEV「数组 key」警告为非缺陷信号、生产构建无 DEV React、排查先对照旧版原型勿据
其返工）；prolayout-header-actions-minwidth-ratchet 已折叠入库（2026-11-07
22:03，spread 至 dashboard-frontend 一域一页：新建
prolayout-header-actions-minwidth-ratchet 页——顶栏动作区 min-width 棘轮自锁
（pro-layout ActionsContent ResizeObserver 实测回写、锁宽后观测元素同步撑宽
只升不降）、触发链与症状签名（filters 槽宽组件 SPA 残留、390px 标题竖排挤压、
直连加载正常）、global.less 单源恒零化两行勿删、顶栏挂宽组件零额外处理、
分态复现与逐元素量宽排查定式）。
