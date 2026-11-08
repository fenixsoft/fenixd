# ADR-334：初始化产物自举只到 staged 为止且离散路径 add——仓库状态决定权留在用户

date: 2026-11-08
status: accepted

## Context

fenix-init 的 gitignore 模板以 `!` 规则放行 `.fenix/todo.md`/`.fenix/verify.yaml`（入库意图已声明），但 init 写入后从不 git add——「入库意图已声明、文件却未入库」，首轮周期盘点即报 whitelist_untracked major（cloud-phone 首跑 3 条实证）。自举补「入库这最后一环」时存在越权面：自动 commit 会替用户定提交历史与切分；`git add .` 会把骨架生成时项目里已有的用户未跟踪文件一并入库（实证：目标项目内有 scripts/nat_check.py 这类既有散件），替用户做出入库决定。

## Decision

初始化产物自举只到 git index（staged）为止：MUST NOT 自动 commit，提交时机永远留给用户；白名单入库只走离散路径逐文件 `git add`，MUST NOT `git add .`；白名单文件逐文件存在性守卫——init 未播种的文件（如 todo.md，由自省/进化车道后续创建）当期缺席跳过不报错、在场才入库；非 git 仓库降级为提示行不阻断骨架生成。后续任何扩展 init/自举入库面的变更沿用同一边界。

## Consequences

新项目首跑不再产生白名单脱落与框架播种产物散件告警（消除产生源而非压制告警信号）；用户保留提交切分与入库取舍的完整决定权；自举产物以 staged 形态滞留属正常态，不构成「init 忘了提交」缺陷，周期盘点不得将 staged 白名单文件再判为脱落；unborn 分支（零提交史）下自举同样生效，无需先造提交。
