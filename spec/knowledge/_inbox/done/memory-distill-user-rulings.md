# memory 存量蒸馏：用户定调与设计原则（规则级决策）

## 背景

auto-memory 存量中用户明确拍板的决策与验收口径——它们约束后续设计方向，但多为
对话中的口头定调，未进任何 SPEC 正文。适合折叠进 self-evolution / admin-ops /
docs-help 域的用户意图类能力页（或按主题就近折叠）。

## 结论（用户定调，按主题）

### 交互与立项流程

- 创意/设计类需求先走 brainstorming 出设计文档定稿（落
  `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`），再转 fenix-new 立项交给
  框架实现，**不进 writing-plans**（10-25 实证工作流）。
- SPEC 的数值/分支歧义以实现满足 `specs/<capability>/spec.md` 的 Scenario 块为准，
  全量 verifier 校验场景而非正文措辞——Scenario 优过正文。
- 立项时 tasks.md 任务行写路径要平铺直书（字面全路径或 basename 出现在 `- [ ]`
  起始行）：声明 lint 的孤儿判定只匹配任务起始行文本，花括号展开/续行写法会被判
  孤儿声明（2026-11-04 立项实例）。
- 不对 fenixd 做任何项目级特殊处理：项目级提示词/配置等能力 fenixd 与普通项目
  一视同仁（09-05 定调）。
- 凡新增 fenixd 配置项的需求，SPEC 必须同步包含 Dashboard 设置界面的编辑能力，
  不允许只落 config.yaml（反馈约束）。
- 验证场景按变更影响面裁剪子集的方案被否（09-10）：收益与机制成本倒挂——PASS
  场景不花钱、花钱的取证场景裁不掉。

### 运行节律与告警

- 扫描节律（10-19 定调）：扫描 run_at 01:00→00:00（提前消顺延）、夜间静默窗 off
  （断窗防御已关，复发即删行恢复）、白天暂停夜间一次性修复。
- 429 解耦定调（10-06）：代码审查触发时点保持 01:00，仅解耦配置键（缺省回退自省
  run_at）+ 窗口水位归审查车道自身（`code_review_state.last_run_at`）；回归车道
  同槽位问题记录在案另行立项（非目标）。
- 人工告警降噪原则：自动兜底/自愈类机制默认静默 + 日志，只有「自动处置失败、
  需要人工裁决」的终态才发人工告警；告警写入按 severity 分流
  （critical/major 进人工队列，warning/minor 写入即自动 handled）；token 预算
  80%/100% 双档均 warning 不发 critical。
- `admin.escalation_cooldown_minutes` 缺省 15→60（09-07 定调，一键多用：孤儿宽限/
  信号节流）。
- 移动端越界治理（09-25 定调）：禁止宽度微调，必须改布局（换行/改卡片/切单列），
  PC 端零影响。
- dashboard 内容区留白治理（11-04）：留白单源=ProLayout token
  paddingInlinePageContainerContent（theme.ts `dshLayoutToken`），token 值 0 会被
  `getLayoutDesignToken ||40` 吞掉、靠尾部 spread 生效；去边框页级作用域
  （Modal/脱壳页豁免）；前端改动免重启，rebuild 后必须 reload（hash 路由 goto
  不重载文档）。
- code-fix 修复进度验收口径：「可以不推进 100%，但不能没有显示」——准备期空档
  两次被感知为卡死，可见性优先于进度精度；进度条撒谎比分母跳动更伤（链 total
  用活口径）。

### 自省与自进化

- 每日自省条目质量标准：足够清晰让**未参与当日工作的新 agent 可以据此直接提出
  SPEC**（证据+建议，零追问）；条目自带「调查评估」字段（只读核查、3-6 句、
  组织顺序固定、核实不了写「未核实」禁编造）。
- **禁止自动创建 SPEC**：todo.md 仅供阅读，spec 立项判定权必须保留给用户——
  自动化回顾的产出与用户决策权严格分离（与 fenix-approve 人工闸门哲学一致）。
- 自省调度第三版=自然日触发+增量窗口（09-08 定调，取代 24h 滚动窗口——滚动窗口
  与每晚 run_at 意图冲突有漂移缺陷）。
- 改 daemon 正在派发的代码前，先冻结相关 spec + 重启杀 agent 再动手；修完 bug 后
  验证/除错人工接手，**不自动恢复派发**（09-01 指示）。

### 主题性架构决策

- 多 harness 架构：以进程边界为唯一接缝（SpawnSpec 进、归一化事件出），换 harness
  收窄为「实现 adapter + 部署注册」；dsh 为目标 harness。
- 自进化立项两硬约束：①跨项目视角只有 Dashboard registry 有、agent 执行能力只在
  daemon 侧——「跨项目触发」与「agent 执行」必须拆开，宿主=框架自身 daemon；
  ②未注册 SPEC 在本框架不是合法状态——evo 草稿全程留 gitignored
  `.fenix/evolution/drafts/`，接受时才「复制→仅 git add 该目录→commit→add_spec」
  四步连做。
- knowledge truth source 只装当前生效业务规则、归档 SPEC 承担历史职责、两者溯源
  链接互指（09-27 定调，openspec 平铺方案被否）。
- dist 不入库（09-04 决策）：交付件从 src 构建，merge-back 后框架自动重建
  （`_rebuild_dist_after_merge`），实现 agent 不 `git add dist`。
- evo spec 名带 `-<6hex>` 后缀=撞名重复立项信号：两条不同条目推导出同 spec 名时
  第二条加后缀且不去重，同一需求会被起草/实现两遍——见后缀先查是否与同前缀 spec
  内容全等，哪份生效看合并先后与冲突消解取向。

## 证据

- 源记忆：fenixd-brainstorm-then-fenix-new-workflow、fenixd-spec-scenario-over-prose、
  fenixd-no-self-project-special-casing、fenix-new-config-needs-dashboard-ui、
  fenixd-scan-schedule-0000-quiet-window-off、fenixd-429-spike-decouple-and-alert-selfheal-specs-filed、
  fenixd-alert-noise-preferences、fenixd-escalation-cooldown-default-60、
  fenixd-mobile-overflow-layout-first-fix、fenixd-pagecontainer-flat-chrome-token、
  fenixd-codefix-startup-stage-visibility-spec-filed、fenixd-daily-self-review-intent、
  fenixd-self-review-schedule-natural-day、fenixd-freeze-family（用户偏好段）、
  fenixd-multi-harness-dsh-design-and-env、fenixd-evo-draft-family、
  fenixd-knowledge-atlas-specs-filed、fenixd-scenario-subset-pruning-evaluated-rejected、
  fenixd-codefix-progress-denominator-and-background-freeze、fenixd-evo-draft-family（6hex 段）。
