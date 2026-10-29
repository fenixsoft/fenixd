## Deliverables

```yaml
- path: skills/fenix-prototype/SKILL.md
  kind: new
- path: skills/fenix-prototype/scripts/stack_profile.py
  kind: new
- path: skills/fenix-prototype/scripts/bootstrap_vendor.py
  kind: new
- path: skills/fenix-prototype/scripts/serve_prototype.py
  kind: new
- path: skills/fenix-prototype/assets/annotator.js
  kind: new
- path: skills/fenix-prototype/scripts/anchor_tools.py
  kind: new
- path: tests/test_fenix_prototype.py
  kind: new
- path: skills/fenix-new/SKILL.md
  kind: modify
- path: agents/implementer.md
  kind: modify
- path: agents/code-review.md
  kind: modify
```

## 1. 栈画像与真组件生成

- [x] 1.1 `scripts/stack_profile.py`：侦察目标工程（依赖清单识别组件库与版本、主题/设计 token 文件、DESIGN.md）输出画像 JSON；v1 实现 React+antd 画像，识别失败返回 unknown 并给出降级标记
- [x] 1.2 `scripts/bootstrap_vendor.py`：环境自检（node/代理/缓存）后按画像版本预打包 react+antd 到 skill 自维护缓存（与工程无关），输出三级降级判定（vendor 缓存命中 / CDN ESM / 纯 HTML 仿样）；每级降级在输出中显式可见；缓存落盘于 gitignore 覆盖的运行时目录 `.fenix/prototype-vendor/`（已被 `.fenix/*` 整体忽略），MUST NOT 落仓内 `skills/` 入库
- [ ] 1.3 SKILL.md 原型生成段：生成 prompt 契约——单文件 HTML、真组件假数据、画像主题注入、关键区块 `data-proto-id` 语义化锚规则、仿样级显式标注「视觉参照、无约束力」
- [x] 1.4 `scripts/anchor_tools.py` 锚保持工具：解析旧原型 `data-proto-id` 锚集合、对新原型输出保持/漂移比对报告（SKILL.md 生成契约引用其报告约束重生成）；配套确定性测试落 `tests/test_fenix_prototype.py`——以构造的 v1/v2 fixture 原型对断言未波及锚保持、波及区块换锚可检出，MUST NOT 依赖现场 LLM 生成（非确定性测试）

## 2. 批注回流与会话内迭代

- [ ] 2.1 `assets/annotator.js`：注入式批注器（与栈无关纯 DOM 操作）——hover 高亮、点选元素、意见面板、意见列表、`POST /feedback`（锚点+文本+时间戳+轮次）、服务器不可达时本地导出 JSON
- [x] 2.2 `scripts/serve_prototype.py`：python 标准库 HTTP 服务器——静态伺服原型目录 + `POST /feedback` 落 `feedback.json`；随机高端口冲突重试；绑定地址可配并打印完整 URL；PID 文件生命周期（存活复用 / 残留探测接管 / 回收）
- [x] 2.3 服务器生命周期与批注落盘测试：启动→POST 落盘→重复启动复用→杀进程留陈旧 PID→再启动接管→回收，全链路测试钉死（落 `tests/test_fenix_prototype.py`）
- [x] 2.4 SKILL.md 迭代段：读 `feedback.json` → 修订原型 → 遵守锚保持 → 用户刷新复看 → 循环直至用户明示认可；迭代全程会话内，不依赖异步审批

## 3. 批准入库与绑定力契约

- [x] 3.1 SKILL.md 批准段：用户明示认可后原型落 `specs/<spec>/prototype/` 并入库提交；整页截图尽力而为（playwright-cli 可用则抓，不可用记「无渲染凭证」，不阻塞批准）；冻结语义（再改 = 新一轮确认）；批准后回填 SPEC 正文与 Scenario 声明 UI 真相源
- [ ] 3.2 `agents/implementer.md` 追加条件式契约段：SPEC 声明原型为 UI 真相源时实现前必读 `specs/<spec>/prototype/`、冲突不擅自偏离须升级用户；措辞以 SPEC 内声明为开关，遵循该文件现有契约段惯例
- [ ] 3.3 `agents/code-review.md` 追加条件式契约段：声明原型时对照原型检查（组件选型/布局结构/锚对应），冲突标记升级项；同样条件式开关
- [ ] 3.4 契约段双向推演验证：构造带 UI 真相源声明的最小样例 SPEC 核对两处契约段触发判定（实现前必读原型 / 评审对照原型），构造无原型对照样例核对不触发；双向推演记录落收工说明，确认既有 SPEC 行为不变（带声明侧的首轮真实派发实证随下一个带原型的界面需求进行，非本 SPEC 实现门禁）

## 4. fenix-new 触发衔接

- [ ] 4.1 `skills/fenix-new/SKILL.md` 增触发判定与衔接段：大改（新页面/新大面板/布局重构/多区块联动）提议原型、小改跳过、用户双向一票否；调用 fenix-prototype 的时机与批准后回填 SPEC 的动作说明

## 5. 端到端实证预演

- [ ] 5.1 样例原型生成冒烟：以一个样例界面需求走全流程（画像→生成→浏览器渲染验证），用 playwright-cli 命名会话断言渲染 DOM 含真实 antd 组件标记与 `data-proto-id` 锚
- [ ] 5.2 批注闭环脚本化验证：模拟批注 POST 落 `feedback.json` → 按 SKILL.md 契约修订样例原型 → 断言意见被消化且未波及锚保持；产出验证记录写入收工说明

## 人工部署步骤（非任务，不进门禁对账）

- 实现合并后需在用户级 skill 目录建符号链接使 skill 可被发现（fenix 系惯例，参照 `/root/.claude/skills/fenix-new -> /root/fenixd/skills/fenix-new`）：`ln -s /root/fenixd/skills/fenix-prototype /root/.claude/skills/fenix-prototype`。实现 run 内的端到端实证（§5）不受影响——实现者按仓内路径直读 SKILL.md 执行，无需 Skill 工具注册。
