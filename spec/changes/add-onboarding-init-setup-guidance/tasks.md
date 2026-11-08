## Deliverables

```yaml
- path: fenix-init
  kind: modify
- path: templates/gitignore-fenix.txt
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: skills/fenix-setup/SKILL.md
  kind: modify
- path: tests/test_init_self_bootstrap.py
  kind: new
```

## 1. 白名单文件初始化自动入库（D1）

- [ ] 1.1 fenix-init 骨架写入完成后新增 git add 步骤：git 仓库内对 `.fenix/todo.md`、`.fenix/verify.yaml` 离散路径 git add（仅 staged 不 commit），控制台输出已入库提示；git add 逐文件存在性守卫——todo.md 非 init 播种物（自省/进化车道后续创建），不存在时跳过该文件且不报错，在场时一并入库；非 git 仓库跳过并输出「待 git init 后手工入库」提示；unborn 分支正常工作；幂等重跑不报错
- [ ] 1.2 pytest 单测（tests/test_init_self_bootstrap.py）：tmp git 仓库内初始化后 `git ls-files` 含 `.fenix/verify.yaml`（todo.md 非 init 播种物：断言其缺席时初始化不报错，事后补建 todo.md 再重跑能补入库）、无 commit 产生、非 git 目录跳过提示、重复执行幂等

## 2. 运行时产物预防性 ignore（D2）

- [ ] 2.1 `templates/gitignore-fenix.txt` 增加 `.claude/agents/` 规则（带成因注释：框架播种运行时产物，预防性 ignore）；`append_gitignore` 幂等补齐同一实现产出（判据 `^\.claude/agents/$`），既有项目缺失规则时追加
- [ ] 2.2 pytest 单测：新模板初始化后 `git status` 不视 `.claude/agents/` 为 untracked、`--ensure-gitignore` 对缺规则项目幂等补齐、已跟踪文件不受影响

## 3. 配置模板注释分形态改写（D3）

- [ ] 3.1 `.fenix/config.template.yaml` llm 段与 agents.models 段注释改写：按 `agent.harness` 分形态描述无分配默认行为（claude=环境继承 CLI 默认档；dsh=回落 dsh profile 默认档，对称回落），删除「默认环境变量模型」误导表述，补显式分配（provider+model）建议路径说明；dsh 分支措辞受 SPEC ①（add-dispatch-precheck-true-fallback，对称回落闭环）落地状态约束——① 尚未合入时按「无分配回落行为将随对称回落闭环（SPEC ①）落地生效」的条件式表述，不得断言当下不存在的行为（当前模板 agent.harness 段明示 dsh adapter 尚未部署）；其余注释不动
- [ ] 3.2 验证：模板渲染（`fenix-init render_config` 路径）产物 YAML 可正常解析（safe_load），注释改动不破坏结构

## 4. fenix-setup 引导补强（D4）

- [ ] 4.1 `skills/fenix-setup/SKILL.md` 增加模型配置检查步骤：读项目 config.yaml → 核对 `llm.providers` 与 `agents.models` 形态 → 未配置分支给 Dashboard 设置页/手工编辑模板示例指引、已配置分支给 provider 名与注册表一致性核对要点
- [ ] 4.2 SKILL.md 增加首跑常见告警解读小节：白名单脱落（初始化已自举、存量 `git add` 处置）、散件首现（预防性 ignore 已内置）、契约模板态（实现期 info 属预期、验证期前完成裁决）三类，各含来源 + 处置
- [ ] 4.3 全量回归：fenixd pytest 既有套件绿；对 fenixd 自身 `.fenix/` 目录演练 `--ensure-gitignore` 幂等（不产生重复规则）
