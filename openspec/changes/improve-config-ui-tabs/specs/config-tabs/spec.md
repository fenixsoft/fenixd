# config-tabs

## ADDED Requirements

### Requirement: Config page organized into tabs

The config page SHALL organize its content into 4 tabs: 「LLM Provider」,「Agent 模型分配」,「并行度设置」,「审批模式」. Each tab SHALL display exactly the content of the corresponding original config section. A save button and its save-hint text SHALL remain visible below the tab bar, outside any single tab's content.

#### Scenario: All four tabs visible

- **WHEN** a user opens the config page
- **THEN** the page SHALL show a tab bar with 4 tabs labeled  LLM Provider / Agent 模型分配 / 并行度设置 / 审批模式, with the first tab active by default, and the save button visible below the tab bar

#### Scenario: Switching tabs preserves all content

- **WHEN** a user switches from the active tab to another tab
- **THEN** the previously active tab's content SHALL be hidden, the newly selected tab's content SHALL be shown, and all form field states (inputs, checkboxes, radio selections, provider cards) across all tabs SHALL be preserved (no re-render, no data loss)

#### Scenario: All config sections reachable via tabs

- **WHEN** a user sequentially visits each tab
- **THEN** each tab SHALL expose the full original section: Provider list management on the LLM Provider tab; agent model assignment cards on the Agent 模型分配 tab; parallel degree and run timeout fields on the 并行度设置 tab; approve mode radio options on the 审批模式 tab

#### Scenario: Save writes all tabs' config

- **WHEN** a user edits fields across multiple tabs and clicks the save button
- **THEN** the system SHALL serialize config from all tabs' fields (not only the active tab) and persist the merged result

#### Scenario: Error banner visible on any tab

- **WHEN** a config load error occurs or a save fails while any tab is active
- **THEN** the error/warning banner SHALL be visible regardless of which tab is active

### Requirement: Tab state is frontend-only

Tab selection SHALL be a pure frontend DOM state. Opening or reloading the config page SHALL reset to the default first tab. Config page refresh behavior driven by SSE SHALL not re-render the page (existing behavior unchanged).

#### Scenario: Reload resets to first tab

- **WHEN** a user selects a non-first tab and then reloads the page
- **THEN** the config page SHALL render with the first tab (LLM Provider) active

#### Scenario: SSE push does not reset tab

- **WHEN** a background event pushes data while the config page is open on a non-first tab
- **THEN** the page SHALL keep the currently active tab and preserve all form inputs for the active and inactive tabs