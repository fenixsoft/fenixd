# 设计（add-verify-evidence-placement-contract）

## 现状与根因

- 无契约：grep verify-evidence /root/fenixd/core 零命中；core/verify_contract.py:230-240 VerifyContract 无证据字段；core/verify_report.py:961 入库 rel_path 严格单文件（docstring 明言禁整目录 add）。
- 盘点盲区：core/worktree_manager/stray_wip.py:151-162 tracked-only 脏判定（_list_dirty_tracked_files 过滤）；evo-add-maintree-stray-wip-sweep design.md:26 明文 untracked 留待后续扩展。
- 落位契约先例：core/agent_runner/prompt_builder.py:910-943 quality-gates.json 落盘契约段（提示词注入同族模式）。
- 信号登记三处制：core/admin_monitor.py:324（severity 映射）、:404（recommended_action 文案）、:469-472（已知类型清单）；「只告警不处置」同款先例=maintree_stray_wip_stale（零触碰+同指纹一次性+复位）。
- 实测样本：potplayer-base verify-evidence/ 为混合目录（55 tracked＋build/ ignored＋20 untracked）——信号必须 entry 级。

## 方案决策

1. **落位契约走「缺省+契约覆盖」**：VerifyContract 增可选 evidence_dir 字段（缺省 .fenix/verify-evidence/<spec>/），模板注释化声明；验证/核查链的指引注入点按 prompt_builder.py:910-943 同族模式补落位约定。报告本体只引用相对路径，不动 verify_report.py:961 单文件 pathspec。
2. **untracked 信号 entry 级、豁免白名单**：stray_wip.py _sweep_locked（:148-165）处增 git status --porcelain 口径，按 entry 判定并豁免 .fenix/ negation 放行项与已 ignore 路径；阈值起步保守（info 级），宽限/指纹记账/复位复用既有形态（:217-251）。
3. **三处登记**：新信号类型落 admin_monitor.py 三处（:324/:404/:469-472），文案复制 maintree_stray_wip_stale 的「只告警不处置」模板。
4. **弃用「随报告入库」形态**：verify_report.py 单文件 pathspec 的防污染约束（不卷入其它 spec 在途草案）不支持扩目录 add，保留现状。

## 风险

- untracked 噪声（构建型项目散件天然多）：info 级+阈值+同指纹一次性兜底；观察误报率后再调。
- 消费项目 .gitignore 形态差异（无 .fenix/* 规则的项目）：evidence_dir 落 .fenix/ 下仍可能 untracked——此时由 untracked 信号兜底可见性，契约不依赖忽略规则成立。