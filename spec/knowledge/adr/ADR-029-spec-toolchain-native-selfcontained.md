# ADR-029：SPEC 工具链原生自包含，schema vendored 随库分发

date: 2026-09-02
status: accepted

## Context

SPEC 生成依赖外部 npm CLI（openspec 全局包）与外部 skills 驱动，其输出文案指向交互式 apply 流程，与 fenix 自动实现链不符；框架实际只用到其三个命令（new/status/instructions），却承担了外部工具链的安装与漂移成本。运行时安装外部包在自托管环境不可靠。

## Decision

- SPEC 生成以原生 Python 重实现（core 模块 + bin CLI），移除 npm CLI 与外部 skill 依赖；仅用标准库 + 既有 PyYAML，零新增依赖。
- spec-driven schema 与模板 vendored 随库分发（作为数据文件而非硬编码进 Python，便于与上游 diff）；不维护上游版本兼容，升级即整体替换 vendored 目录。
- `spec/changes/<name>/` 布局、artifact 文件名与 `.spec.yaml` 保持不变——框架核心（状态机、dashboard、watcher）硬依赖此契约。
- 归档同设原生命令 + skill；skill 输出文案对齐自动实现流程，不再出现外部工具的交互式指引。
- 正确性标准 = 生成的 artifacts 可被框架核心消费，CLI 输出 JSON 结构对齐原工具以降低 agent 理解成本。

## Consequences

- 框架自包含、一键安装，SPEC 阶段零外部进程调用；与上游 schema 的漂移以 vendored 副本为准，fenix 生成结果稳定。
- 外部工具自身的卸载/保留归其自管理，fenix 只是不再依赖；与 ADR-008/ADR-033 同属「vendored 而非运行时安装」的依赖策略。
