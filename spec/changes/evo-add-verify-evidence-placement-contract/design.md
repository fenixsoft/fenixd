# 设计（add-verify-evidence-placement-contract）

## 现状与根因

- 无契约：grep verify-evidence /root/fenixd/core 零命中；core/verify_contract.py:230-240 VerifyContract 无证据字段；core/verify_report.py:961 入库 rel_path 严格单文件（docstring 明言禁整目录 add）。
- 盘点盲区：core/worktree_manager/stray_wip.py:151-162 tracked-only 脏判定（_list_dirty_tracked_files 过滤）；evo-add-maintree-stray-wip-sweep design.md:26 明文 untracked 留待后续扩展。
- 落位契约先例：core/agent_runner/prompt_builder.py:910-943 quality-gates.json 落盘契约段（提示词注入同族模式）。
- 信号登记三处制：core/admin_monitor.py:324（severity 映射）、:404（recommended_action 文案）、:469-472（已知类型清单）；「只告警不处置」同款先例=maintree_stray_wip_stale（零触碰+同指纹一次性+复位）。
- 实测样本：potplayer-base verify-evidence/ 为混合目录（55 tracked＋build/ ignored＋20 untracked）——信号必须 entry 级。

## 方案决策

1. **落位契约走「缺省+契约覆盖」**：VerifyContract 增可选 evidence_dir 字段（缺省 .fenix/verify-evidence/<spec>/），模板注释化声明；验证/核查链的指引注入点按 prompt_builder.py:910-943 同族模式补落位约定。报告本体只引用相对路径，不动 verify_report.py:961 单文件 pathspec。**落点约定为消费项目主树**（绝对路径 = 项目根/.fenix/verify-evidence/<spec>/）：evidence 是「run 后人工核查」语义，落主树与 worktree 生命周期解耦（worktree 销毁后报告引用不断链），且 .fenix/ 被消费项目忽略规则覆盖、不产生 untracked 噪声——与框架既有主树运行时形态（.fenix/verify-progress/<spec>/report.json）一致。指引注入须写明「主树根绝对路径」，防验证 agent 在 worktree 内自发落位、run 结束即失联。
2. **untracked 信号 entry 级、豁免白名单**：stray_wip.py _sweep_locked（:148-165）处增 git status --porcelain 口径，按 entry 判定并豁免 .fenix/ negation 放行项与已 ignore 路径；插桩点须覆盖 tracked 空集早退（:163-165 现行实现 tracked 零改动即返回 clean，纯 untracked 场景须在该早退之前完成 untracked 判定，否则信号永不触发）。untracked 条目不进 ``git diff HEAD``，指纹不能复用 tracked 形态（会退化为路径集哈希、内容演化不重计）：untracked 指纹 = 路径排序集 + 逐文件内容 sha256。阈值/宽限键：``admin.maintree_untracked_stray_threshold``（缺省 5 个 entry，info 级降噪起步）、宽限复用 ``admin.maintree_stray_wip_grace_minutes``（同族同语义，不膨胀配置面）。新信号类型常量 ``maintree_untracked_stray_stale``（stray_wip.py:35 SIGNAL_TYPE 同格式）。tracked 口径现行行为逐字节不变（D6 只增不改同款约束）。
3. **两处登记、不收录 STORED_SIGNAL_TYPES**：新信号只登记 SIGNAL_SEVERITY（值 ``info``，:324 处）与 SIGNAL_RECOMMENDATION（文案复制 maintree_stray_wip_stale 的「只告警不处置」模板，:404 处）两表（写入方 stray_wip._write_alert 查表单源取值同款形态）；**MUST NOT 收录 STORED_SIGNAL_TYPES**（:469-472）——摄取循环（admin_monitor.py:2189-2192）对收录类型无条件唤起、无 severity 过滤，收录即把 info 留痕升级为人工唤起，违背「只告警不处置」降噪意图。可见性由 AdminStore 留痕（admin_store.py:38 INFO=纯留痕）与 Dashboard 承载。
4. **弃用「随报告入库」形态**：verify_report.py 单文件 pathspec 的防污染约束（不卷入其它 spec 在途草案）不支持扩目录 add，保留现状。

## 风险

- untracked 噪声（构建型项目散件天然多）：info 级+阈值+同指纹一次性兜底；观察误报率后再调。
- 消费项目 .gitignore 形态差异（无 .fenix/* 规则的项目）：evidence_dir 落 .fenix/ 下仍可能 untracked——此时由 untracked 信号兜底可见性，契约不依赖忽略规则成立。
- evidence 持久性：落点为主树（决策 1），跨 run/worktree 销毁可回查；契约显式覆盖 evidence_dir 指向非忽略路径时产生的 untracked 散件由本 SPEC 的 untracked 信号暴露，不自愈。