# ADR-326：Restart=on-failure 配 supervisor 有意退出退出码协议

date: 2026-11-04
status: accepted

## Context

systemd 承载托管链后需选重启策略。`Restart=always` 会结构性架空 supervisor 熔断：熔断退出后 systemd 拉起新 pid、新 pid 清熔断标记、再次熔断——「再拉→再熔断」循环伴随每轮 critical 告警风暴，熔断「停止自动重试、恢复交人工」的语义实质改变（always+StartLimit 兜底的替代方案同样被否）。systemd 需要一个能区分「有意退出」与「崩溃」的机器判据。

## Decision

两类 unit 均 `Restart=on-failure`，项目 unit 以 `SuccessExitStatus=75` 声明 supervisor 有意放弃的专用码，配 `StartLimitIntervalSec`/`StartLimitBurst` 作 crash-loop 最后兜底。supervisor 四条有意退出路径落实退出码协议：停机信号收尾与 `.fenix/stop` 旗标在场退出 → 0；熔断退出（supervisor_fused）与兜底收尸/收编超限放弃看护 → 75。0 与 75 不被 systemd 拉回（恢复一律人工）；其余一切退出形态（SIGKILL、异常非零）一律拉回，含 dashboard 进程单独崩溃。dashboard 无熔断/放弃看护语义，不适用退出码协议。后续新增 supervisor 有意退出路径必须归入 0 或 75 并同步 unit 模板。

## Consequences

- 熔断后 unit inactive（非 failed）、告警仅一条、无拉回风暴；解熔断与恢复保持人工链路（compileall 核验配方不变）。
- 干净退出码的意外路径（如 bug 导致 exit 0）不被拉回——与 tmux 承载时代等价，非回归；on-failure+StartLimit 覆盖 crash 主面。
- supervisor 退出码成为 systemd 拉回判定的对外契约：改动退出码语义或新增退出路径须同步 unit 模板与 `SuccessExitStatus`。
