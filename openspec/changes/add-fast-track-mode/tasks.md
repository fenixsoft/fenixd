# Tasks: add-fast-track-mode

## 1. mode 元数据与读取

- [ ] 1.1 定义 `.openspec.yaml` 的 `mode` 字段约定（`fast-track` / `full`，缺省 full），写入 design 或 config 文档
- [ ] 1.2 dispatch 派发前读取 spec 目录 `.openspec.yaml` mode 字段的读取器（字段缺失/非法一律返回 full），含单测

## 2. fast-track agent 与统一结果文件

- [ ] 2.1 编写 `agents/fast-track.md` 提示词模板：实现 → 场景设计 → 场景验证 → 判定四段职责、统一结果文件 schema、护栏告知（零变更哨/交付物清单/fix 预算）
- [ ] 2.2 扩展 `.fenix-run-result.json` schema：fast-track 验证段（设计场景、逐场景结果、最终判定、证据），定义解析器
- [ ] 2.3 `runner.run_fast_track`：单 run 派发、同一 worktree 全生命周期、成功路径 merge 语义与完整模式一致（含 ensure_spec_committed）
- [ ] 2.4 `prompt_builder` 增加 fast-track 段，场景集落盘兼容现有 scenario schema（供升级完整模式后 verifier 复用）

## 3. daemon 派发分支与护栏适配

- [ ] 3.1 PMEngine/dispatch 增加 fast-track 分支：ready 后派单 run，不派 planner/verifier，状态沿现有转换图推进
- [ ] 3.2 零变更哨与交付物守卫适配 fast-track run（run 内守卫语义，阻断行为与完整模式一致）
- [ ] 3.3 fail 预算与 token 预算接线：run 内修复轮次计入预算
- [ ] 3.4 结果文件驱动状态推进：硬校验通过 → `implemented → testing → verified`；缺失/非法/校验失败 → 重派并累计计数

## 4. 框架侧硬校验

- [ ] 4.1 verdict_check 扩展：统一结果文件的结构完整性、场景全量执行（豁免走现有豁免规则）、逐场景证据存在性三要素校验，含单测
- [ ] 4.2 校验失败路径：fail-closed 处理（不推进 verified，按失败重派），错误信息可读

## 5. bug run 内修复与超预算升级

- [ ] 5.1 run 内修复重验流程：fast-track run 验证发现 bug 时同上下文修复重验，轮次计入 fix 预算
- [ ] 5.2 超预算升级：mode 改写 full（同步 `.openspec.yaml`）、保留分支成果、spec 置 implemented、派发完整模式 verifier 流水线、升级原因写入 spec entry
- [ ] 5.3 升级路径单测：预算耗尽 → 不回 ready 重跑 implementer、成果不丢失

## 6. fenix-new 模式选择

- [ ] 6.1 更新项目源 `skills/fenix-new/SKILL.md`：复杂度评估标准（影响面/模块数/UI 或迁移/场景数量）、明确建议话术、`--fast-track` / `--full` 参数、确认后写入 `.openspec.yaml` mode 行
- [ ] 6.2 同步安装副本 `~/.claude/skills/fenix-new/`（两份内容一致）

## 7. Dashboard 模式标记

- [ ] 7.1 后端 data 层输出 spec 执行模式（读 `.openspec.yaml`，缺省 full）
- [ ] 7.2 spec 列表与详情页展示模式标记（fast-track 与 full 可辨识），存量 spec 显示 full 等价标记

## 8. 验证与收尾

- [ ] 8.1 mock runner 单测覆盖 fast-track 全链路：派发单 run → 守卫触发 → 硬校验 → 状态推进 → 超预算升级
- [ ] 8.2 用 dashboard fixture 验证配方做端到端人工验证（假 spec + mode 字段 + 伪造结果文件，不烧 token）
- [ ] 8.3 更新 PROJECT_LOG.md；确认无新增配置键（不加 config.template.yaml 条目）
