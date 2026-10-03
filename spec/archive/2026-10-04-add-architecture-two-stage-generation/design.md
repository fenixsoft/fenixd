## Context

架构图页签（`architecture_routes.py`）当前以单体 `claude -p` 一次完成「读代码取证 + 产出 archify 图」，在 fenixd 与 fenix-desktop 双项目实测全部 1800s 超时。取证定案（2026-09-26）：

- bigmodel 网关对「大上下文 × 长输出」请求存在静默丢弃（TCP ESTAB、收发队列全零、转录零事件、进程 I/O 零变化），CLI 应用层无请求级超时只能无限等；
- 单体 spawn 形态把危险请求密集化：SKILL.md 全文（实测 16396 字节 ≈ 16KB）内嵌首条 prompt、Explore 子代理取证报告（11KB+）全文回灌主 agent、主 agent 单轮生成完整候选 JSON——三轮挂点全部落在主 agent 大上下文轮；
- 旁证：子代理小上下文请求几十次零挂；本机手工复用现成报告 + 分段小步写盘全程零挂。

`API_TIMEOUT_MS=600000` + `CLAUDE_CODE_MAX_RETRIES=2` 已通过项目级 `.claude/settings.json` 注入（治「挂死」不治「必挂」），作为纵深保留。

## Goals / Non-Goals

**Goals:**
- 生成管线中 LLM 的每轮请求都落在「小上下文 × 短输出」安全区，双项目页签一键生成稳定出图
- 阶段2 失败重试免重做探索（evidence 磁盘持久 + HEAD 指纹复用），降低重试成本
- 产物权威判定链、单飞锁、进程组击杀、重启残留合成等既有治理全部保留

**Non-Goals:**
- 不改前端（`stage` 键后端先行，前端细分文案后行）
- 不改 vendored archify 包本身
- 不做跨 refresh 的 evidence TTL / 定时失效（HEAD 一致即有效，语义最简）
- 不做 daemon 侧阶段2 自动重试（用户再点刷新即触发 HEAD 命中跳段，等效达成）

## Decisions

1. **两段式 + 磁盘交接**：阶段1 探索 run（prompt ~1KB，不注入 SKILL.md，写 evidence.md，marker `ARCHIFY_EVIDENCE_DONE`）→ 阶段2 出图 run（prompt ~2KB，SKILL.md/evidence 均绝对路径引用，分段小步写候选 JSON）→ 既有 `_judge_artifact` 判定。磁盘是唯一交接面，evidence 天然持久。
2. **HEAD 指纹复用**：evidence.md 头部记录 repo HEAD sha + 时间戳；refresh 时 evidence 存在且 HEAD 一致则跳过阶段1。HEAD 变化自动重探索，图不陈旧；不引入 TTL。
3. **超时拆分**：总 1800s 不变，阶段1 ≤720s、阶段2 ≤1080s；进程组击杀范式沿用；error 文案区分阶段（可诊断性）。
4. **阶段判定链**：阶段1 以「returncode==0 且 evidence 非空」为准（不信 claude 自述）；阶段2 判定行为与现状完全一致。
5. **status `stage` 键**：`exploring` / `authoring` / null，向后兼容存量六键契约（读侧容忍缺键/多键）。
6. **prompt 纪律条目**：阶段2 prompt 显式要求候选 JSON 先写骨架再逐段 Edit 补全、禁单次巨量 Write；取证/中间观察落盘不靠上下文携带。
7. **测试分阶段假 spawn**：fake spawn 按 prompt 内容区分（含 `ARCHIFY_EVIDENCE_DONE` 即阶段1），沿用测试隔离双陷阱配方（cmd[0] 分发 + 布防门控）。

## Risks / Trade-offs

- **阶段2 agent 不守分段纪律**（一次大 Write）：无法机械强制，靠产物硬门兜底——超时击杀 + failed 可重试（HEAD 命中，重试成本低），风险可接受。
- **evidence 质量决定图质量**：阶段1 探索不足 → 图偏离真实架构。缓解：阶段1 prompt 明确四项取证维度（组件/主链路/外部依赖/信任边界）+ 阶段2 prompt 允许补充少量定向查证。
- **两段编排复杂度**：线程体从一次 communicate 变两次，失败形态组合增多（2×超时/非零退出/判定失败）。缓解：每段独立 try/killpg/finish，error 文案带阶段前缀。
- **evidence.md 位于 gitignored 的 `.fenix/`**：属运行时文件，不入库、不进 Deliverables 声明段。
