# 快车道规模预检与预算分档
<!-- knowledge: capability=fast-track-scale-precheck rev=2
     sources=spec/archive/2026-09-18-evo-add-fast-track-scale-precheck,spec/archive/2026-09-18-evo-add-fast-track-scale-precheck-4afdbe -->

fast-track 派发前按任务面做轻量静态规模预估，超阈 SPEC 自动升档预算或降级 full，预算档位与任务规模相匹配。

## 规则

- 派发前静态规模预估：`scale = tasks.md 未勾选任务条数 × 1 + Deliverables 声明段交付物数 × 2`；纯静态计算，不引入 LLM 预估。
- 分档判定（阈值取自配置，higher 阈值必须小于 full 阈值）：
  - `scale ≥ full 阈值`：改写 `.spec.yaml` mode 为 `full`（复用既有升级路径的改写语义），该 SPEC 走完整模式流水线；
  - `higher 阈值 ≤ scale < full 阈值`：按 higher 档派发——spec entry 写 `_fast_track_scale_tier=higher`，超时 extension 上限加成（`max_extensions` 2 → 4，加成常数 `SUPERVISION_FAST_TRACK_EXTRA_EXTENSIONS = 2`）；
  - `scale < higher 阈值`：按常规 fast-track 预算原样派发。
- 配置段 `agents.scale_precheck`（设置界面「预算」页签）：`enabled`（缺省 true）、`higher_threshold`（缺省 30）、`full_threshold`（缺省 45）；非法值逐项回退缺省，higher/full 阈值相等或倒挂时整段回退缺省——归一化单点在 `core.fast_track_result.get_scale_precheck_config`，读侧与设置界面同源，避免展示值与生效值脱节。
- 总开关关闭时整个跳过预检（返回 disabled）：不写档位标记、不触发 full 降级，行为回到无预检状态。
- 预检失败保守放行：tasks.md 缺失、读取失败、路径非法等异常按低档放行并记 WARNING，不阻断派发；异常不向外扩散。
- extension 末位自动 WIP 保全：超时预算进入 extension 末位窗口仍无收尾成果时，终止收口前自动触发一次 WIP checkpoint（复用既有 `commit_wip_checkpoint`，提交消息 `fenix(wip): checkpoint extension-tail <spec>`，幂等标记防重复）；已完成的轮次工作不得随超时无保全作废。
- 末位保全的 git 操作失败（超时/权限）仅记 WARNING，既有超时收口照常执行，不阻断。

## 溯源

- [2026-09-18 2026-09-18-evo-add-fast-track-scale-precheck](spec/archive/2026-09-18-evo-add-fast-track-scale-precheck/) — 新增规模预检：任务条数+文件面静态预估与分档、预检失败保守放行、extension 末位自动 WIP 保全
- [2026-09-18 2026-09-18-evo-add-fast-track-scale-precheck-4afdbe](spec/archive/2026-09-18-evo-add-fast-track-scale-precheck-4afdbe/) — 同名重复立项归档，增量规则口径与前一份一致，未引入新规则
