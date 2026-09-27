# ADR-074：运行时可变值不落版本库

date: 2026-09-12
status: accepted

## Context

SPEC 的运行时门控值（定时拾取 `start_after`、定时解冻 `frozen_until`）与订阅配置（hooks）需要持久化，候选落点有 `.spec.yaml`（随 spec 目录入库）与 `.fenix/`（gitignored）。spec 目录受 git 管理：运行时频繁变更的值会污染版本库，dashboard 写它还要求配套自动提交链路并制造 merge-back 冲突面。

## Decision

- spec 目录只承载版本化文档；运行时可变值一律不入库，按消费方选既有免提交落点：
  - 调度门控字段（`start_after`/`frozen_until`）存 STATE.md entry（任意键透传，调度器只读 STATE.md）；
  - hook 订阅（全局/spec 级）存 `.fenix/config.yaml` 的 `hooks` 段。
- `.spec.yaml` 只放创建期确定的 spec 身份/模式声明（如 fast-track mode），不放运行时频繁变更的门控值。
- 上述落点免费获得既有失效机制：配置走 30s mtime 热更新，STATE.md 走文件锁原子写 + watcher。

## Consequences

- 运行时值变更零 git 副作用：不弄脏工作区、不触发 merge-back、不需要自动提交。
- spec 归档后 `hooks.specs` 下的条目残留为已知噪音（不执行、不影响匹配），接受。
- 新增运行时门控/订阅类配置时，落点判据照此执行：会被运行期反复改写的值不入库。
