# proposal：幻影失败结构化双源否决（合流三源）

## 背景

日报聚合把已按成功落地的 run 误计为失败，家族三源、机制各异：

- 第一源（2026-09-25 两 run，spec/archive/2026-10-03-evo-fix-self-review-phantom-failed-samples 已修）：result 文本回声，落地「回声剥除 + 双源交叉守卫」，但守卫只对 detail 前缀 signal= 生效；
- 第二源（2026-10-22#可改进#1，三现）：marker= 失败词复述把成功 run 判失败，其建议③「结构化双源否决」未立项；
- 第三源（本案 evo-1792692791，2026-10-22T18:44:17Z）：CLI 429 死于收尾交换，产物直读按成功落地（terminal=success、50248 字节产物入库、6.756 美元零损失），聚合器 _classify_run 读文件尾 error 事件记 failed——error 终态样本不在守卫射程，salvage 登记未被聚合侧消费。

附带口径分裂：产物直读路径的 lane run_metrics 行 turns=0/cost=null（日志 2026-10-22T18:44:17.565347Z），真实 197 轮/6.756 美元只在档案 result 事件。

## 提案

1. 双源否决扩界：error 终态样本（detail 为 Exit code/CLI 错误形态）与 marker= 命中样本均接入 daemon run_metrics 终态交叉裁决——terminal=success 即改计 success 并写 self_review_phantom_failure 告警；查无账面行保守保持 failed（宁可不拦不可误伤）。
2. 指标透传：产物直读/salvage 登记路径透传档案侧真实 turns 与 total_cost_usd，消除双账分裂。
3. 契约测试：以 evo-1792692791 形态为夹具，连同「查无账面行」「daemon=error 反例」一并钉住。

## 非目标

不改动 signal= 既有守卫语义与告警通道；不处理 daemon 终态本身记录错误的场景（超出聚合器可证范围）。