# merge-back 能力规格：spec-dir-inflight-guard

## 概述

merge-back（实现分支合回主树）前与失败后的处置，新增「spec/changes/ 目录在飞编辑卫检查」与「可重试失败仅重试合并」两条语义，杜绝已成功 run 因合流受阻整轮作废。

## 现状与缺口

- merge-back 前：WIP 重叠闸门（auto/block）只处理「tracked 主树改动与分支重叠」，spec/changes/ 下在飞未提交编辑不被识别为顺延信号；Self-heal 检测差异仅告警即中止。
- merge-back 失败后：spec 回置 ready + Retry N/3，等待窗口后重新派发实现整轮（新 run 从头实现），已成功分支与产物不保留复用；实现尝试预算被无产出消耗。

## 规格

### 卫检查（merge-back 前）

- merge-back 前对 spec/changes/<spec>/ 目录（spec 名由分支推导）做未提交改动检测。
- 命中 → merge-back 顺延（不进入 merge），携带顺延原因与等待语义，由调度方重排，不判失败。

### 失败分类与重试（merge-back 失败后）

- 可重试失败（主树脏 / spec 在飞编辑 / 锁冲突）：保留已成功分支与产物，等待条件满足后仅重试合并；等待/重试不消耗实现尝试预算，不重派实现整轮。
- 不可重试（语义冲突 / 熔断 / 交付物守卫）：保持既有 repair lane / 熔断 blocked / 冻结转人工通道。

## 边界

- 不改变 WIP 重叠闸门现有 stash/block 语义。
- 不改变 repair lane 与熔断的既有触发条件。