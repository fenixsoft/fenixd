## Deliverables

```yaml
- path: agents/planner-plan.md
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: agents/administrator.md
  kind: modify
- path: agents/self-review.md
  kind: modify
- path: agents/arbiter.md
  kind: modify
- path: CLAUDE.md
  kind: modify
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: skills/fenix-process/SKILL.md
  kind: modify
- path: spec/knowledge/index.md
  kind: modify
- path: spec/knowledge/domains/knowledge-atlas/knowledge-atlas-directory.md
  kind: modify
```

## 1. 车道纪律段

- [x] 1.1 起草知识纪律段基准文案：接任务先读 `spec/knowledge/index.md` 判断相关域；
      命中相关域则 MUST 下钻 `domains/<域>/_domain.md` 与相关能力页后再动手；未命中
      可跳过、MUST NOT 为走流程而全量阅读；项目无 `spec/knowledge/` 目录时静默跳过
- [x] 1.2 将纪律段写入六个 `agents/{planner-plan,implementer,code-fix,administrator,
      self-review,arbiter}.md`，按车道职责各微调一句话（implementer 强调动手前查模块
      能力页、planner-plan 强调立项前查重、administrator 强调排查先查域知识等）；
      遵守 prompt 文件纪律——先 merge main 再改，只在非契约段追加，不得改写既有
      契约段与占位符

## 2. 交互会话面

- [x] 2.1 项目 `CLAUDE.md` 增加知识消费指路段（同款 index-first 纪律）并预告回填
      纪律「值得沉淀的排查/立项结论投递 `spec/knowledge/_inbox/`」，标注该目录由
      SPEC `add-knowledge-inbox-pipeline` 提供、尚不存在时不投递
- [x] 2.2 仓内 `skills/fenix-new/SKILL.md` 增加立项前先读 index 识别相关域并下钻
      能力页的指引；`skills/fenix-process/SKILL.md` 增加查进度时对账相关能力页
      当前规则的指引

## 3. index 简介 增厚

- [x] 3.1 逐一读取 29 个 `spec/knowledge/domains/<域>/_domain.md`，将 `index.md`
      每域简介列增厚为 2~3 句（覆盖主要能力面，不引入新事实），域行结构与能力数量
      列不变，顶部盖戳行刷新为当前本地时区 `UTC+8` 形态；简介列保持单行单元格且
      不含裸竖线 `|`（`core/knowledge.py` `_check_stamp_table` 按竖线切列校验
      四列结构与末列时间格式，简介含裸竖线或换行会确定性触发更新时间格式违规）
- [x] 3.2 同步更新目录契约页 `spec/knowledge/domains/knowledge-atlas/knowledge-atlas-directory.md`：
      将 index.md「列全部能力域与一行简介」的简介表述对齐为增厚后形态（2~3 句），
      并刷新该页盖戳行——该页是蒸馏 run 维护 `index.md` 的契约依据（导航层由
      蒸馏 run 维护），不同步则下次蒸馏会按旧契约把增厚简介回退为一句话

## 4. 自验

- [x] 4.1 静态核验：六个 prompt 文件均含纪律段且指路路径拼写正确；`CLAUDE.md` 与
      两个 SKILL.md 指路段落位；`git diff --stat` 确认零代码文件（.py/.tsx/.ts）被触碰
- [x] 4.2 Scenario 静态对账：spec.md 三个 Requirement 的 Scenario 逐一对照文案与
      增厚后的 index 核验成立（下钻路径真实存在、存在性条件语义完整、简介可独立
      支撑任务↔域判断），核验结论写入收工报告
