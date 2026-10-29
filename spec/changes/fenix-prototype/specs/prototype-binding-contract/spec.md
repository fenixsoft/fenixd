# prototype-binding-contract 规格

## ADDED Requirements

### Requirement: SPEC UI 真相源声明通道
原型批准入库后，fenix-prototype MUST 把原型路径（`specs/<spec>/prototype/`）回填进 SPEC 正文，并在 SPEC Scenario 中声明其为 UI 真相源（与「数值以 Scenario 为准」同纪律等级）。声明 MUST 是绑定力的第一通道。

#### Scenario: 批准后回填声明
- **WHEN** 原型批准入库完成
- **THEN** SPEC 正文引用原型路径，Scenario 显式声明「界面以 prototype/ 为准」

### Requirement: implementer 条件式契约段
`agents/implementer.md` MUST 新增条件式契约段：当 SPEC 声明原型为 UI 真相源时，实现前 MUST 读取 `specs/<spec>/prototype/` 下原型；实现与原型冲突时 MUST NOT 擅自偏离，MUST 升级用户裁决。契约段 MUST 以 SPEC 内声明为条件开关，对无原型 SPEC MUST 零影响。

#### Scenario: 带声明的 SPEC 触发必读
- **WHEN** implementer 领到声明了 UI 真相源的 SPEC
- **THEN** 实现前读取原型目录，组件选型与布局结构以原型为准绳

#### Scenario: 无原型 SPEC 零影响
- **WHEN** implementer 领到未声明原型的普通 SPEC
- **THEN** 契约段不触发，实现流程与既有行为完全一致

### Requirement: code-review 条件式契约段
`agents/code-review.md` MUST 新增条件式契约段：当 SPEC 声明原型为 UI 真相源时，评审 MUST 对照原型检查实现（组件选型、布局结构、关键区块与锚的对应）；发现实现与原型冲突 MUST 标记为需升级项而非自行放行。对无原型 SPEC MUST 零影响。

#### Scenario: 评审对照原型发现冲突
- **WHEN** 实现的布局结构与原型声明的结构冲突且无用户裁决记录
- **THEN** 评审把冲突标记为升级项，不视为可自行接受的偏差

#### Scenario: 无原型 SPEC 评审不变
- **WHEN** 评审未声明原型的 SPEC
- **THEN** 评审流程与既有行为完全一致

### Requirement: 绑定力双通道成立
UI 真相源的约束力 MUST 由双通道共同承载：SPEC Scenario 声明（派发契约主体通道）+ 派发提示词契约段（评审对照通道）。实现与原型冲突且有用户裁决时，MUST 以用户裁决为准并把裁决记入 SPEC；无裁决时 MUST 以原型为准。

#### Scenario: 冲突仲裁顺序
- **WHEN** 实现与原型冲突
- **THEN** 有用户裁决记录以裁决为准；无裁决以原型为准并升级用户
