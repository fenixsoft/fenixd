# spec-repo-review-concurrency

## ADDED Requirements

### Requirement: 全仓审查并发配置读取（fail-open 单点缺省）
框架 SHALL 提供配置键 `verify.repo_code_review_concurrency`（正整数，缺省 **4**）读取器；语义与 `get_impl_code_review_concurrency` 同款——仅接受正整数 `int`（`bool` 不算），缺失/verify 节缺失/str/float/≤0 一律回退缺省 4（脏值不中断派发）；该键 MUST NOT 进入 `resolve_config` 缺省填充列表（缺省只由读取器单点提供）。该键控制**全仓审查** run（`review_kind` 为 `manual_full` / `manual_window` / `scheduled`）的并行审查度；implement 任务内审查继续由 `verify.impl_code_review_concurrency` 控制（缺省 4，语义不变）。

#### Scenario: 合法配置生效
- **WHEN** config.yaml 中 `verify.repo_code_review_concurrency: 2`
- **THEN** 读取器返回 2，全仓审查 run 按 2 注入并发上限

#### Scenario: 脏值回退缺省
- **WHEN** 该键为 `"8"`（str）/ `0` / `true` / 缺失
- **THEN** 读取器一律返回 4，派发不中断

### Requirement: 并发双通道注入
全仓审查 run 派发时框架 SHALL 将并发值注入两处：① 提示词（`agents/code-review.md`）新增并行扇出上限条款——主 agent 同时在飞的审查子代理数 MUST ≤ 该值（波次滚动推进，非总数上限）；② `ocr scan` 命令 MUST 带 `--concurrency <n>`（ocr 不传参时其内部缺省为 8，即 2026-09-24 事故的并发来源之一）。

#### Scenario: 提示词注入扇出上限
- **WHEN** 全仓审查 run 构建提示词且配置值为 4
- **THEN** 渲染后的提示词含「同时至多 4 个子代理」类上限条款

#### Scenario: ocr scan 带并发参数
- **WHEN** run 提示词中的 scan 命令被渲染
- **THEN** 命令含 `--concurrency 4`（渲染值为配置值）

### Requirement: 设置界面与配置链路同步
Dashboard 设置页（QualityPanel）SHALL 新增「全仓审查并发」输入项，与既有「SPEC 审查并发」（`verify.impl_code_review_concurrency`）并列展示、分别保存；`config_admin` 读写链路、`.fenix/config.template.yaml` 示例值（必须等于缺省 4，防模板派生配置恒为显式旧值）同步更新。

#### Scenario: 界面修改生效
- **WHEN** 用户在设置页将「全仓审查并发」改为 6 并保存
- **THEN** config 写入 `verify.repo_code_review_concurrency: 6`，下一次全仓审查 run 按 6 注入

#### Scenario: 两键独立不串扰
- **WHEN** 仅修改「全仓审查并发」
- **THEN** `verify.impl_code_review_concurrency` 值不变，implement 任务内审查并发不受影响
