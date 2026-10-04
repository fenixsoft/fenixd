## Deliverables

```yaml
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: agents/planner-plan.md
  kind: modify
```

## 1. 检查单与提示固化

- [ ] 1.1 skills/fenix-new/SKILL.md：在 §3.2.1 强制检查单同族位置新增一条——平台移植/新采集链路类 SPEC 的首个采集里程碑必须含可观测性交付项（输入帧 dump、管线逐级计数、坏事件分类统计至少其二），与功能交付同批验收，允许按平台等价替代
- [ ] 1.2 agents/planner-plan.md：出题约束区补同款表述，措辞与 1.1 一致

## 2. 一致性校验

- [ ] 2.1 通读两处改动，确认与既有 §3.2.1 条款及 planner 既有约束无冲突、无重复定义；确认纯文案改动不触及 core/deliverables.py 的 lint 规则