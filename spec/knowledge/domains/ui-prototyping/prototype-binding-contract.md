# 原型绑定契约

<!-- knowledge: capability=prototype-binding-contract rev=1
     sources=spec/archive/2026-11-02-fenix-prototype -->

批准原型对 AI 实现产生实际约束力的机制：绑定力由「SPEC Scenario UI 真相源声明」与「派发提示词条件式契约段」双通道共同承载，纯视觉参照无约束力。

## 规则

- 原型批准入库后，fenix-prototype MUST 把原型路径（`specs/<spec>/prototype/`）回填进 SPEC 正文，并在 SPEC Scenario 中声明其为 UI 真相源，与「数值以 Scenario 为准」同纪律等级；该声明是绑定力的第一通道，同时是派发契约段的开关。
- `agents/implementer.md` 含条件式契约段：SPEC 声明原型为 UI 真相源时，实现前 MUST 读取 `specs/<spec>/prototype/` 下的原型，组件选型与布局结构以原型为准绳；实现与原型冲突时 MUST NOT 擅自偏离，MUST 升级用户裁决。
- `agents/code-review.md` 含条件式契约段：SPEC 声明原型为 UI 真相源时，评审 MUST 对照原型检查实现（组件选型、布局结构、关键区块与 `data-proto-id` 锚的对应）；发现实现与原型冲突且无用户裁决时 MUST 标记为升级项，不视为可自行接受的偏差。
- 两处契约段均以 SPEC 内 UI 真相源声明为条件开关：未声明原型的 SPEC 不触发契约段，实现与评审流程与既有行为完全一致。
- 冲突仲裁顺序：实现与原型冲突时，有用户裁决记录以裁决为准并把裁决记入 SPEC；无裁决时以原型为准并升级用户。

## 溯源

- 2026-11-02 fenix-prototype（spec/archive/2026-11-02-fenix-prototype） — 新增本能力：SPEC UI 真相源声明通道、implementer/code-review 条件式契约段与冲突仲裁顺序。
