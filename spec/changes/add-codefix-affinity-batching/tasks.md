# 任务：add-codefix-affinity-batching

## Deliverables

```yaml
- path: core/code_fix.py
  kind: modify
- path: core/agent_runner/prompt_builder.py
  kind: modify
- path: agents/code-fix.md
  kind: modify
- path: .fenix/config.template.yaml
  kind: modify
- path: core/dashboard/static/src/pages/settings/components/QualityPanel.tsx
  kind: modify
- path: tests/test_code_fix_affinity_batching.py
  kind: new
- path: core/dashboard/static/dist/index.html
  kind: reference
```

## 1. 选批亲和性聚类

- [ ] 1.1 重写 `core/code_fix.py` `select_batch`：open 条目按 `file` 字段归并为文件组（组不可拆）；组间按组内最早 `first_seen_at` 升序（缺失回退组内最小 `item_id`），组内保持既有稳定序；按直接父目录聚簇做贪心装箱——目标规模 T=`batch_size`、硬上限 H=2T；同目录组允许浮动吸收至 H、异目录组仅在批 <T 时吸收且吸收后 ≥T 即封批、达 H 封批、单文件组 >H 独立成批不拆；每次调用返回装箱后的首批（链推进每轮重调，语义零改动）；排除口径（失败档案 ∪ exclude_ids）与台账读失败返回空的 fail-closed 行为不变
- [ ] 1.2 新增 `tests/test_code_fix_affinity_batching.py`，覆盖 spec 全部聚类场景：同文件条目跨时间必同批 / 同目录组超 T 仍同批 / 异目录组达 T 即封批 / 硬上限封批且余组进下批 / 单文件超大组独立成批 45 条不拆 / 排除口径与两次调用结果一致（稳定性）；并核对既有 select_batch 相关测试迁移后全过

## 2. 批内波次上限自适应

- [ ] 2.1 `core/code_fix.py` 新增波次上限分档纯函数：批内文件组数 G ≤4 → 4；5≤G≤8 → 6；G≥9 → 8（8 为硬上限）
- [ ] 2.2 `core/agent_runner/prompt_builder.py` `_build_code_fix_prompt` 按本批 items 计算文件组数并以 `{wave_cap}` 占位符注入 prompt；模板缺占位符时回退缺省 4（旧模板文案兼容）
- [ ] 2.3 `agents/code-fix.md` 模板更新：「派发」节固定「并发上限 4（固定上限）」改为 `{wave_cap}` 占位符引用并写明分档语义与 8 硬上限；串行路径判定（仅 1 文件组或总条目 ≤2）表述保持不变
- [ ] 2.4 单测：分档函数三档边界（4/5/8/9 组）+ prompt 注入含 `{wave_cap}` + 模板无占位符回退 4

## 3. 批收尾回归两段式

- [ ] 3.1 链末批判定：批收尾回归前（核销前）以「排除本批 item_ids 后 `count_open_items` 为 0」判定末批，判定结果供回归分流使用；本批条目集合从既有批上下文取得
- [ ] 3.2 `core/code_fix.py` 新增触碰面映射纯函数（fixed 行 `file` 集合 → 测试路径列表）：测试文件（`tests/` 下或 `test_` 前缀/`_test` 后缀）直接入选；产品文件按「同目录 `tests/` 的 `test_<stem>.py` glob 命名匹配」∪「`tests/` 树内 `grep -rl` import/from 反查」（subprocess 单次调用，MUST NOT 逐文件 Python 遍历）；路径相对回归执行根解析
- [ ] 3.3 `{test_targets}` 占位符替换：str/list 两态 `regression.cmd` 支持（替换为空格连接的测试路径列表、路径做 shell 引用包裹、同值导出 `FENIX_TEST_TARGETS` 环境变量，对齐 `{port}` 占位符先例）；以替换后的 RegressionSpec 副本传入既有 `run_regression`（主机级锁/JUnit 解析/硬超时全继承，不新增执行通道）
- [ ] 3.4 批收尾回归分流：末批恒全量；非末批且 `targeted_regression=true` 且 cmd 含占位符且映射非空 → 定向回归；否则回退全量并记日志（fail-open）；进度写点 `current` 文案区分「定向回归」与「全量回归」（不带分母）；失败语义走既有回归失败路径（含定向重试轮），零新增处置分支
- [ ] 3.5 单测：末批判定（剩余 open 为 0/非 0）+ 映射规则（测试文件直选/命名匹配/import 反查并集/空集）+ 占位符替换（str/list 两态、路径引用）+ 三分支回退（无占位符/映射空/配置关）+ 定向失败与末批全量失败均进既有失败路径

## 4. 配置键与设置页

- [ ] 4.1 配置解析：`admin.code_review_fix.targeted_regression` 严格 bool、缺省 true；非法值（非 bool 类型）回退缺省并记 warning，MUST NOT 抛异常
- [ ] 4.2 `.fenix/config.template.yaml` `code_review_fix` 注释样例段新增该键：语义说明 true=非末批定向回归+末批恒全量、false=全批全量，缺省 true
- [ ] 4.3 `core/dashboard/static/src/pages/settings/components/QualityPanel.tsx`：`code_review_fix` 区块（`code_review_fix_batch_size` 同区域）新增 `targeted_regression` Switch 控件，经既有 GET/POST `/api/config` 通道读写，说明文案含两段式语义
- [ ] 4.4 前端源码改动后 `npm run build` 构建通过（dist 为运行时重建产物，锚点 `core/dashboard/static/dist/index.html` 按 reference 审计）

## 5. 收尾验证

- [ ] 5.1 全仓测试通过：`pytest tests/ -q` 零失败，既有 code-fix 车道测试（test_code_fix*.py 全系）零回归
