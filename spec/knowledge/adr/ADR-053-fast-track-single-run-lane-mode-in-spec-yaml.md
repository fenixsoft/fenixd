# ADR-053：fast-track 车道——单 run 全包守卫保留，mode 属 spec 定义

date: 2026-09-09
status: accepted

## Context

完整模式中 implementer / planner / verifier 各自重复探索代码库，冷启动开销对简单需求重复支付 3 次且多 run 串行等待。历史教训（mock 验证假阴性放大器、零变更哨、交付物守卫的由来）表明压缩流程时护栏不可省略。

## Decision

- 执行形态：状态机不变，简单需求由单个 run 全包四段（实现 → 场景设计 → 场景验证 → 判定），run 内守卫替代 run 间守卫；拒绝旁路状态机的轻量 lane，拒绝两 run 拆分。
- mode 元数据存 spec 目录 `.spec.yaml`（与 schema/created 同级）：随目录提交、merge-back 安全；不放 STATE.md（gitignore、可被重置）。缺失/非法一律按 full 处理（fail-closed），存量 spec 零迁移；读取为单一纯函数，派发与 dashboard 共用同一读取器避免两处漂移。
- 结果复用既有 run 结果文件机制（增加验证段），不新增文件协议；判定经确定性硬校验兜底：报告结构完整、场景全量执行（设计集与执行集一致、无静默遗漏）、逐场景证据存在性——agent 文本宣称不作为通过依据，与完整模式 verifier 的信任模型一致（见 ADR-042）。
- 超预算升级衔接：mode 改写 full、实现成果以分支形式保留、spec 置 implemented、完整 verifier 流水线接管，升级原因写 error 字段；绝不把已有实现成果丢回 ready 重跑。

## Consequences

- 自验自判的最坏情况仍回到独立 verifier，正确性不依赖 agent 自律；解析失败一律按失败处理（fail-closed），不静默通过。
- 回滚 = 读侧忽略 mode 字段，所有 fast-track 元数据成为惰性数据；完整模式代码路径零改动。
- 复杂度评估在需求对话内完成，不做框架自动打分；mode 是 per-spec 元数据，不新增全局配置开关。
