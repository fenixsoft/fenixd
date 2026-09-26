# implementer-deliverable-gate — 增量规格（缺件凭据核销收敛）

## ADDED Requirements

### Requirement: 缺件凭据核销收敛

守卫产出缺件（`missing`）后，若该路径在**跨 run 持久的 dispute 审计流**中已存在
凭据——`typo` 裁决（`element == path` 且带 `actual_path`）或重定位凭据
（`old_path == path` 且带替代路径）——则系统 MUST 以**凭据核销**收敛该条目：不再
要求旧路径在实现分支存在，MUST NOT 仅因「本轮无新凭据」而无限重派。

核销 MUST 与既有 `removed` 收缩防护的豁免同源（读同一审计流）；凭据不存在或替代
路径无据时 MUST NOT 核销（fail-safe，走既有缺件处置）。

核销后 MUST 以生效声明复检真实路径是否落地（防「凭据在册但交付物从未落地」的空洞
核销）：替代路径在实现分支 HEAD 不存在时 MUST NOT 核销。

核销的判定 MUST 能**取得凭据中的替代路径**（`new_path` / `actual_path`）以完成上述
落地校验——仅有「该路径是否有凭据」的布尔判定不足以判定核销。

核销作用域 MUST 限于 `violation == "missing"`：`undeleted`（`kind: delete` 反判）与
`removed`（收缩防护）MUST NOT 因本核销而不计入违规清单。

#### Scenario: 残留凭据核销缺件

- **GIVEN** 缺件 `pages/settings/X.tsx` 在审计流已有 `typo` 凭据（替代路径
  `pages/projects/X.tsx`），且该替代路径在实现分支 HEAD 存在
- **WHEN** 守卫/裁决处理该缺件
- **THEN** 该条核销，不计入缺件违规清单
- **AND** 正常合并推进，不重派、不 blocked

#### Scenario: 凭据在册但替代路径未落地不核销

- **GIVEN** 缺件路径有 `typo` 凭据，但替代路径在实现分支 HEAD 不存在
- **WHEN** 处理该缺件
- **THEN** MUST NOT 核销，走既有缺件处置（终审 / 打回）

#### Scenario: 无凭据按既有缺件处置

- **GIVEN** 缺件路径在审计流无任何 typo/重定位凭据
- **WHEN** 处理该缺件
- **THEN** 走既有缺件处置，不受本核销条款影响
