# 验证裁决稳定性（judge-rerun-stability）

## 需求

### R1 judge 重跑上限
- 系统对同一 spec 的 planner-judge 重跑次数计数（按 verdict 序列）。
- 当连续两轮 judge verdict 完全一致（含 status 与失败场景清单）时，判定 verdict 已稳定，后续验证轮直接复用最近一次结果，不新起 judge run。
- 单 spec 窗口内 judge run 总数有硬上限（如 5 次），超出后进入人工裁决通道。

### R2 verified 一次性放行
- verify-progress/<spec>/.fenix-run-result.json 落盘 status=verified 后，pm_engine 的 legacy 与新验证两条路径均不得再将该 spec 判定为 blocked/bug-found/unknown-status。
- 唯一例外：场景集或实现 commit 变化（spec 戳变化）时失效，重新验证。

### R3 可观测性
- STATE.md 新增 judge_rerun_count 字段；run 收尾时记录本次是否复用缓存 verdict。

## 验收标准
- 场景：add-web-ui 类误判链重放时，verified 落盘后 0 次额外 judge/verify run。
- 单元测试：verdict 稳定缓存判定、verified 放行后 legacy 覆盖被拒绝。