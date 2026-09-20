# merge-back 能力规格：stash-pop-conflict-triage

## 概述

merge-back 自愈链中「stash pop 冲突」的处置从「丢弃 stash 版」升级为三态重试（merge → 恢复 commit → 保留登记），保证主树未提交改动永不因自愈静默丢失。

## 现状与缺口

- stash_guard.py pop 冲突即丢弃 stash 版，仅信号 + git show 口令兜底；
- 交付物丢失后依赖 admin 手工找回（978f9f65 实证），窗口内同类 4+ 起。

## 规格

### 三态重试

- 冲突时按序尝试：
  1. merge：stash 版与 merge 结果合并且落回工作区（真正冲突才留冲突标记）；
  2. merge 不可行：自动创建恢复 commit 留审计并登记 disposition；
  3. 兜底：保留冲突文件并登记 disposition。
- 任一态不得静默丢弃 stash 内容；stash 条目保留、stash_pop_conflict 信号与唤起 admin 行为保持。

### 可观测性

- 冲突处置路径写结构化日志（文件清单 / 处置方式 / stash sha），dashboard 与自省可见。

## 边界

- 不改变 WIP 重叠闸门 auto/block 策略与 stash 时机；
- 不改变 stash_pop_conflict 信号契约。