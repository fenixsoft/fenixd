# 场景产物顶层契约
<!-- knowledge: capability=scenario-product-toplevel rev=1 sources=spec/archive/2026-10-27-evo-scenario-product-toplevel-contract -->

场景规划产物 `test_scenarios.json` 的顶层形状是显式交付契约；验收拒收按失败类别给最小修复路径，dict 包裹的可拯救形态机械解包采纳，杜绝一层包裹错误放大成全量场景重建。

## 现行规则

- 顶层形状契约：`test_scenarios.json` 顶层必须是纯 JSON 数组，禁止 `{"scenarios": […]}` 之类 dict 包裹。契约双侧注入——静态模板 `agents/planner-plan.md` 在交付要求中显式声明（附正反例各一行，并显式区分同目录 `scenarios.json` 持久化集的 dict 形态：两文件形状相反不得互抄）；运行时由 prompt_builder 场景 schema 段单源注入「顶层交付契约」条目，仅 planner-plan 会话生效——planner-judge、fast-track 等其他 agent 分支不注入该条目（其既有场景 schema 必填字段段不受影响）。
- 可拯救形态唯一：验收器遇顶层非数组的场景文件，仅对「顶层 dict 且含非空 scenarios 数组」这一形态机械拯救——解包后重过既有全部场景校验，通过则以解包后的纯数组原子重写 `test_scenarios.json`（盘上落地而非仅内存采纳，原始条目字段零丢失、无临时文件残留）；解包后仍不合法、dict 缺 scenarios 键、scenarios 非数组或空数组，一律按原错误拒收且盘上保持原文不落地。字符串/数字/列表套列表等其余非数组顶层无解包面，照常拒收。`load_scenarios` 本体顶层硬门语义不变（非数组照抛「场景文件格式错误」）。
- 拯救单点接入：拯救助手只接在验收归因路径（stage2 产物验收点），`load_scenarios` 本体与其余读端（fastlane、verdict_evidence、冻结层顶层读端等）不接助手——读端恒可假设顶层为纯数组，无需各自防御 dict 包裹；解包重写落地后，其余读端与冻结层按既有语义自然恢复。
- 解包留痕：解包属框架改写 agent 产物，必须留痕（解包前顶层键、条目数、落地结果，WARNING 级）；解包成功不产生 env_error、不触发 replan 重派。契约已双侧明示，再现 dict 包裹即 agent 违约，反馈仍会指出错误类别——解包只作一次性止损，不弱化契约约束。
- 拒收反馈按类别分类：REPLAN_FEEDBACK 场景文件拒收文案按失败类别生成——格式类（顶层形状/条目结构）给「最小修复」指引（错误类别 + 修复动作，指明顶层纯数组契约与 dict 反例），不得一律硬编码「重新输出全部场景」；内容类缺失（如场景整体缺失）保留全量重建指示。格式类侧车缺省 False（未经历 stage2 的路径）照旧全量重建文案，既有行为不变。
- 分类判据宽口径：格式/内容分类按失败发生阶段判定（顶层形状→拯救路径；解包后条目校验失败→格式类），不新增错误文本解析器；凡可通过小改动修复的归格式类，误判代价是多给一条修复指引，不阻塞重建路径。

## 溯源

- 2026-10-27 evo-scenario-product-toplevel-contract（spec/archive/2026-10-27-evo-scenario-product-toplevel-contract） — 新增顶层形状双侧契约、dict 包裹可拯救形态机械解包（原子重写落地+留痕、拯救单点接入验收路径）、REPLAN_FEEDBACK 格式类最小修复文案（此前顶层 dict 包裹被读端整份拒收，硬编码「重新输出全部场景」放大成 25 场景全量重建）
