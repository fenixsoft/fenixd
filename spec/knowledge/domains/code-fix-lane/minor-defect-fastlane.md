# 轻微缺陷快车道

<!-- knowledge: capability=minor-defect-fastlane rev=1
     sources=spec/archive/2026-09-27-add-pipeline-throughput-governance -->

bug-found 小缺陷的轻量通道：三条件全满足时走 code-fix 轻量修复 + 子集重验，否则回落整轮 fix SPEC 路径。

## 规则

### 判定阈值
- 验证轮判定 bug-found 时，验证管线评估三个条件：① 本轮失败场景数 = 1；② judge 归因的修复影响面 ≤ 3 文件；③ judge 无争议/裁决标记（判据从实现/验证结果文件 findings 的 dispute/adjudication 类条目读取；信号机制缺失或无条目时按「无争议」fail-open 并在判定记录留痕）。
- 三条件全部满足走 fastlane：生成 code-fix 轻量修复任务（`agents/code-fix.md` 车道）并对其成果仅执行子集重验；任一条件不满足走既有 bug-found→fix SPEC 整轮路径。
- 判定过程与所选路径记录在验证产物或日志中，可追溯为何走/不走 fastlane。

### 子集重验与回落
- 重验场景集 = 失败场景 ∪ 其 `depends_on` 前置依赖链（递归）∪ 以失败场景为前置的下游场景（递归，防修复波及依赖方而漏验）；其余通过场景本轮不重复执行，重验报告含全部场景判定（未实跑者沿用上一轮通过结论并标注来源）。
- fastlane 修复轮次计入该 spec 既有验证轮预算；同一验证轮内连续 2 次 fastlane 修复后子集重验仍失败，强制回落整轮 fix SPEC 路径（已消耗轮次计入预算），不再发起第 3 次。
- 子集重验独立可用：直接以子集场景集作为本轮执行集，不依赖 verdict 缓存能力。
- fastlane 修复产生的代码 diff 按既有 impl-code-review-gate / 交付物门禁语义接受审查，不因轻量通道豁免任何门。

## 溯源

- [2026-09-27 2026-09-27-add-pipeline-throughput-governance](spec/archive/2026-09-27-add-pipeline-throughput-governance/) — 新建本页：三条件阈值判定、子集重验场景集口径（前置链 + 下游递归）、连续两次失败强制回落与审查门不豁免。
