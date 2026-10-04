## Deliverables

```yaml
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: agents/spec-review.md
  kind: modify
```

## 1. 检查单与提示固化

- [x] 1.1 skills/fenix-new/SKILL.md：在 §3.2 交付段强制条目串末尾（「任务必须是实现 Agent 可独立完成的（强制，见 §3.2.1）」之后）新增一条——平台移植/新采集链路类 SPEC 的首个采集里程碑必须含可观测性交付项（输入帧 dump、管线逐级计数、坏事件分类统计至少其二），与功能交付同批验收，允许按平台等价替代
- [x] 1.2 agents/spec-review.md：「评审维度」检查区补同款表述，措辞与 1.1 一致——评审平台移植/新采集链路类 SPEC 时核查首个采集里程碑是否含上述观测交付项，缺失按 severity 判定标准处置

## 2. 一致性校验

- [x] 2.1 通读两处改动，确认与既有 §3.2/§3.2.1 条款及 spec-review 既有评审维度、severity 判定标准无冲突、无重复定义；确认纯文案改动不触及 core/deliverables.py 的 lint 规则