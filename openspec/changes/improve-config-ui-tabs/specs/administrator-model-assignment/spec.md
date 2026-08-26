# administrator-model-assignment

## ADDED Requirements

### Requirement: Administrator assignable to a provider and model

The Agent model assignment section of the config page SHALL include an Administrator role card. The card SHALL offer the same interaction as other agent roles: an enable checkbox, a provider dropdown listing all available LLM providers, and a model-name input. When enabled and saved, the assignment SHALL be written to `agents.models.administrator = {"provider": <provider-name>, "model": <model-name>}`.

#### Scenario: Administrator card present in assignment section

- **WHEN** a user opens the Agent 模型分配 tab on the config page
- **THEN** the section SHALL render an assignment card labeled Administrator（运维） alongside the existing implementer/planner-plan/planner-judge/verifier cards, with checkbox, provider dropdown, and model-name input

#### Scenario: Save administrator assignment

- **WHEN** a user enables the Administrator card, selects a provider from the dropdown, enters a model name, and saves
- **THEN** the persisted config SHALL contain `agents.models.administrator` with the chosen provider and model, and the config validation SHALL accept it

#### Scenario: Read-back displays saved administrator assignment

- **WHEN** `agents.models.administrator` exists in the effective config and a user opens the Agent 模型分配 tab
- **THEN** the Administrator card SHALL be rendered enabled with the assigned provider selected and the assigned model name filled in

#### Scenario: Administrator unassigned by default

- **WHEN** no `agents.models.administrator` is present in the effective config
- **THEN** the Administrator card SHALL render with the enable checkbox unchecked and blank provider/model fields, and the hint for missing providers SHALL apply to it like other roles

### Requirement: Administrator runtime resolves assignment before legacy keys

When the daemon invokes the Administrator agent, its model resolution SHALL proceed in order: (1) `agents.models.administrator` assignment — model name used as `--model` and the assigned provider's environment injected (baseurl/apikey/custom env), matching other assigned agents; (2) legacy `admin.agent_model` string; (3) the default gateway model constant. Provider injection SHALL only occur when an assignment exists.

#### Scenario: Assignment configured

- **WHEN** `agents.models.administrator = {"provider": "volc-engine", "model": "deepseek-v4-flash"}` exists and Administrator is invoked
- **THEN** the Administrator run SHALL use `--model deepseek-v4-flash` and inject the volc-engine provider's baseurl/apikey/custom env variables into the subprocess

#### Scenario: No assignment, legacy key present

- **WHEN** no `agents.models.administrator` exists but `admin.agent_model` is set, and Administrator is invoked
- **THEN** the Administrator run SHALL use the `admin.agent_model` value as `--model` with no provider environment injected (default gateway behavior, unchanged from before this change)

#### Scenario: No assignment, no legacy key

- **WHEN** neither `agents.models.administrator` nor `admin.agent_model` is set, and Administrator is invoked
- **THEN** the Administrator run SHALL use the default gateway model constant with no provider environment injected

#### Scenario: Invalid provider rejected at save

- **WHEN** a user assigns the Administrator card a provider name that is not in the LLM Provider list and saves
- **THEN** the save SHALL be rejected with a validation error naming the unknown provider, and no partial config SHALL be written