# 验证报告：fenix-prototype

> ⚠️ 本报告由框架于 2026-10-29T08:54:43Z 自动合成（裁决 Agent 未写报告，已由框架合成），内容为结构化验证产物（report.json / .fenix-run-result.json）的忠实渲染。
> 报告时效标记（判定本报告是否属上一轮）：合成源轮次指纹：report.json@2026-10-29T08:50:26.237590+00:00+run-result@mtime1793264068026882015

## 结论：❌ 未通过（Bug Found）

**状态：bug-found — 17/18 场景通过，1 失败，0 错误（1 个真实产品 Bug）**

18 场景：17 pass、1 fail（product-bug 1、test-defect 0、flaky 0、env 0）。唯一失败为 serve_prototype.py 存活实例复用的命令行核实不对称（绝对解析路径 vs 调用形态路径子串匹配），活实例被误判残留另起新端口；同场景 stale 接管、SIGTERM 回收、端口释放均通过。无场景文件缺陷，无需修复场景。

| 指标 | 数量 |
| --- | --- |
| 通过 | 17 |
| 失败 | 1 |
| 错误 | 0 |
| 产品 Bug | 1 |
| 本链增量 Token（输入） | 0.44M |
| 本链增量 Token（输出） | 0.09M |


## 真实产品 Bug

### BUG-01（severity=major）· output_match

- 关联场景：proto-server-lifecycle-reuse-stale-recycle
- 描述：serve_prototype.py 存活实例复用失效：同目录已有存活实例时再次启动，活实例被误判为残留并接管，新实例另起新端口（38975→42455），违反 SPEC「存活实例复用」Scenario（应复用既有实例与端口、打印同一端口、不报端口冲突）
- 根因：serve_prototype.py L125 身份核实条件 `script_path in cmdline` 与 L276 `script_path=str(Path(__file__).resolve())` 不对称：script_path 是解析后的绝对路径，而 cmdline 记录的是调用形态路径（相对路径/符号链接时不同），子串匹配失败 → probe_existing 把存活本脚本实例误判为 stale（L127-128）→ 清 PID 文件另起新实例。凡非绝对解析路径方式调用即确定性触发
- 证据（场景 proto-server-lifecycle-reuse-stale-recycle 结构化证据，引用）：
  - failed_assertions: [{"type": "output_match", "selector": "REUSE_SAME_PORT_OK", "expected": "第二实例复用既有实例端口（打印同一端口 38975）", "actual": "SECOND_URL=http://127.0.0.1:42455，REUSE_PORT_MISMATCH=38975/42455——第二实例另起新端口监听，未复用存活实例"}]
  - screenshots: []
  - first_failed_step: 步骤①存活实例复用：同目录首实例存活(端口38975)时再次启动 serve_prototype.py，新实例打印新端口 42455 而非复用既有端口


## 场景结果

| 场景 | 描述 | 状态 | 失败断言 | 分类 |
| --- | --- | --- | --- | --- |
| proto-deliverables-exist | 交付物齐备：tasks.md Deliverables 清单（tasks.md L4-L23）声明的 10 个文件全部存在于验证树——skills/fenix-prototype/ 下 SKILL.md、scripts/stack_profile.py、scripts/bootstrap_vendor.py、scripts/serve_prototype.py、scripts/anchor_tools.py、assets/annotator.js，tests/test_fenix_prototype.py，以及三处修改目标 skills/fenix-new/SKILL.md、agents/implementer.md、agents/code-review.md。本 SPEC 交付物为命令/脚本/落盘形态（不改 dashboard 端点与页面），故全部场景取 kind=cli。 | pass | 0/13 | - |
| proto-vendor-cache-gitignored | vendor 缓存运行时目录治理（tasks.md L29、design.md 决策 3）：bootstrap_vendor.py 声明缓存落 .fenix/prototype-vendor/；该路径被 .gitignore 的 .fenix/* 规则覆盖（git check-ignore 实证）；skills/fenix-prototype/ 下无 vendor/node_modules 类产物被 git 追踪（缓存 MUST NOT 落仓内 skills/ 入库）。 | pass | 0/4 | - |
| proto-stack-profile-react-antd | 栈画像侦察正向路径（ui-prototype-generation/spec.md「栈画像侦察」、tasks.md L28）：对含 react@19.1.0 + antd@6.1.0 依赖清单与 DESIGN.md（主色 #1677ff）的夹具工程运行 stack_profile.py，应输出可解析的画像 JSON，其中识别出组件库 antd、版本号（6.x）与主题 token（#1677ff）；退出码 0。调用形态按 位置参数/--project/--dir/--root 容错探测（CLI 契约未在 SPEC 钉死）。 | pass | 0/6 | - |
| proto-stack-profile-unknown-degrade | 栈画像侦察异常路径——未知栈降级（ui-prototype-generation/spec.md「栈画像侦察」Scenario:未知栈降级、tasks.md L28「识别失败返回 unknown 并给出降级标记」）：对仅含 lodash 的依赖清单运行 stack_profile.py，画像应可解析且含 unknown 标识与降级标记（降级/fallback/仿样字样之一），进程正常退出、无 Traceback 崩溃。 | pass | 0/5 | - |
| proto-stack-profile-edge-inputs | 栈画像侦察边界输入（覆盖规则：空输入/异常路径）：stack_profile.py 对空目录（无 package.json）应优雅返回 unknown/降级画像而非崩溃；对不存在的路径应干净报错或返回 unknown——两种输入下输出均不得出现 Python Traceback。侦察失败同样走「识别失败返回 unknown」（tasks.md L28）。 | pass | 0/4 | - |
| proto-bootstrap-ladder-contract | 资源三级降级契约（ui-prototype-generation/spec.md「资源三级降级」、tasks.md L29）：bootstrap_vendor.py 须体现环境自检（node 探测）与三级降级判定——vendor 预打包缓存、CDN ESM 兜底、纯 HTML 仿样三级均在其实现/输出词汇中显式可见，缓存路径 prototype-vendor 落位明确；SKILL.md 须写明每一级降级对用户可见（生成时说明所用层级）。行为级验证由 tests/test_fenix_prototype.py 套件（proto-pytest-suite-green 场景）承载，本场景钉静态契约。 | pass | 0/7 | - |
| proto-skillmd-generation-contract | 原型生成 prompt 契约（ui-prototype-generation/spec.md「真组件高保真生成」、tasks.md L30）：SKILL.md 原型生成段须钉明——单文件 HTML、工程真实组件库渲染、数据全为假数据、画像/主题注入、关键区块打 data-proto-id 语义化稳定锚、降级仿样级显式标注「视觉参照、无约束力」。 | pass | 0/8 | - |
| proto-anchor-tools-keep-drift | 重生成锚保持报告（ui-prototype-generation/spec.md「重生成锚保持」、tasks.md L31）：构造 v1/v2 原型对——v2 保持 proto-header 与 proto-footer、波及区块改锚为 proto-chart-v2；运行 anchor_tools.py 输出保持/漂移比对报告，报告须引用未波及锚 proto-header、proto-footer（保持），并检出 proto-chart 锚消失（漂移可检出，且不得与 proto-chart-v2 混淆）。语义级断言由 tests/test_fenix_prototype.py 确定性 fixture 测试兜底（tasks.md L31 MUST NOT 依赖现场 LLM 生成）。 | pass | 0/5 | - |
| proto-server-serve-feedback | 独立简易 HTTP 服务器正向路径（prototype-annotation-loop/spec.md「独立简易 HTTP 服务器」Scenario:启动与批注落盘、tasks.md L36）：serve_prototype.py 以 python 标准库独立进程启动（不经 dashboard），启动即打印完整访问 URL（http://host:port），随机高端口 ≥1024；静态伺服原型目录（GET / 返回 200 且含 data-proto-id 内容）；POST /feedback 后批注（锚点 proto-header + 意见文本）落盘到原型目录下 feedback.json，内容为合法 JSON 且含锚点、意见文本、时间戳类与轮次类字段；结束后进程可回收。批注 POST 体按 锚点+文本+时间戳+轮次 的常见 schema 形态容错探测（批注 JSON schema 细节为 SPEC 留给实现的开放点）。 | pass | 0/13 | - |
| proto-server-lifecycle-reuse-stale-recycle | 服务器 PID 文件生命周期三态（prototype-annotation-loop/spec.md「独立简易 HTTP 服务器」Scenario:存活实例复用/残留实例接管、tasks.md L36-L37）：①同目录已有存活实例时再次启动——复用既有实例与端口（打印同一端口、原进程仍存活服务），不报端口冲突；②kill -9 制造残留（PID 文件留存但进程已死）后再启动——探测残留并接管，新实例可正常伺服 200，不留僵尸；③SIGTERM 回收——进程正常终止、端口释放。全程同一场景内多步交互并校验中间状态。 | failed（已修正） | 1/8 | product-bug |
| proto-server-feedback-edge-inputs | 批注提交异常路径（覆盖规则：空输入/超长输入/特殊字符；prototype-annotation-loop/spec.md 服务器健壮性）：服务器在跑时依次投递——空 body POST、非法 JSON body、对 /feedback 的 GET（方法不允许），每次异常请求后服务器必须仍存活可服务（GET / 200），不得崩溃；随后提交 20KB 超长文本 + 特殊字符（引号/反斜杠/换行/制表/emoji/<script> 标签）的批注，应被接受且 feedback.json 保持合法 JSON、特殊字符与超长文本完整保真（转义正确、无截断）。 | pass | 0/9 | - |
| proto-annotator-contract | 注入式批注器契约（prototype-annotation-loop/spec.md「批注器交互」、tasks.md L35）：annotator.js 与组件栈无关（纯 DOM 操作），须含——data-proto-id 锚点捕获（批注挂锚不挂裸 selector）、POST /feedback 上送、hover 高亮、点选元素、意见输入面板、意见列表、时间戳与轮次记录、服务器不可达时本地导出 JSON 的降级路径（导出/export/download/Blob 字样及失败处理）。批注器交互发生在独立原型服务器页面上（非 fenixd dashboard 实例，web 场景 navigate 不可达），故以静态契约 + S9/S11 的 HTTP 链路黑盒组合验收。 | pass | 0/12 | - |
| proto-skillmd-iteration-contract | 会话内迭代闭环契约（prototype-annotation-loop/spec.md「会话内迭代闭环」、tasks.md L38）：SKILL.md 迭代段须钉明——读 feedback.json → 修订原型 → 遵守锚保持 → 用户刷新复看 → 循环直至用户明示认可；迭代全程发生在当前会话内、不依赖异步审批流（提及异步并排除依赖）。 | pass | 0/8 | - |
| proto-skillmd-approval-backfill-contract | 批准入库、冻结与 SPEC 回填契约（prototype-annotation-loop/spec.md「批准入库与冻结」+ prototype-binding-contract/spec.md「SPEC UI 真相源声明通道」、tasks.md L42）：SKILL.md 批准段须钉明——用户明示认可后原型落 specs/<spec>/prototype/ 并入库提交、草稿目录清理；整页截图尽力而为、失败记「无渲染凭证」不阻塞批准；批准即冻结、再改视为新一轮确认；批准后回填 SPEC 正文并在 Scenario 中声明 UI 真相源。 | pass | 0/11 | - |
| proto-implementer-binding-contract | implementer 条件式契约段（prototype-binding-contract/spec.md「implementer 条件式契约段」、tasks.md L43）：agents/implementer.md 须新增条件段——开关为 SPEC 内 UI 真相源声明（提及真相源+原型）；声明生效时实现前必读 specs/<spec>/prototype/ 原型、组件选型与布局结构以原型为准绳；实现与原型冲突 MUST NOT 擅自偏离、须升级用户裁决；并对无原型/未声明 SPEC 写明零影响（既有行为不变）。 | pass | 0/7 | - |
| proto-code-review-binding-contract | code-review 条件式契约段（prototype-binding-contract/spec.md「code-review 条件式契约段」、tasks.md L44）：agents/code-review.md 须新增条件段——SPEC 声明 UI 真相源时评审 MUST 对照原型检查（组件选型/布局结构/关键区块与 data-proto-id 锚的对应）；实现与原型冲突且无用户裁决时标记为升级项而非自行放行；对无原型 SPEC 零影响。与 S15 共同承载「绑定力双通道成立」（spec.md 同名 Requirement）。 | pass | 0/6 | - |
| proto-fenix-new-trigger-section | fenix-new 触发判定与衔接段（ui-prototype-generation/spec.md「触发判定」、tasks.md L49）：skills/fenix-new/SKILL.md 须新增——大范围改动判定（新页面/新大面板/布局重构/多区块联动 → 主动提议原型）；小范围局部修改跳过原型直接起草 SPEC；用户双向一票否（大改可豁免、小改可主动要求，以用户决定为准不再劝阻）；调用 fenix-prototype 的衔接；批准后回填 SPEC 的动作说明。 | pass | 0/7 | - |
| proto-pytest-suite-green | 确定性测试套件绿灯（tasks.md L16 交付 tests/test_fenix_prototype.py；L31/L37 要求锚保持与服务器生命周期全链路测试钉死且 MUST NOT 依赖现场 LLM 生成）：在验证树根运行 python3 -m pytest tests/test_fenix_prototype.py -v --tb=short（只带 -v 不并列 -q，保证输出含 passed 汇总行），退出码 0 且至少 1 个用例通过（pytest 无用例时退出码为 5，会被 exit_code=0 断言拦截）。 | pass | 0/3 | - |


## 断言级豁免清单

以下失败断言被归类为非产品缺陷（不记产品 Bug），逐条列出供人工复核豁免是否掩盖真实缺陷（场景级一句话归因不足以复核）。

无非 product-bug 的被豁免失败断言。

## 本轮场景集变更

当前稳定场景集共 18 个（第 1 轮）。

- 首轮写入 18 个场景

