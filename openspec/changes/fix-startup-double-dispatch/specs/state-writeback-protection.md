## ADDED Requirements

### Requirement: State Writeback Protection

#### Scenario: Merge-Back Failure During Active Testing
- **WHEN** implementer merge-back fails and spec is in "testing" state with an active tester run
- **THEN** spec state is not downgraded to "ready", conflict is logged and verification continues

#### Scenario: Merge-Back Failure Without Active Tester
- **WHEN** implementer merge-back fails and spec is in "testing" state without an active tester run
- **THEN** spec state may be downgraded to "ready" per existing logic

#### Scenario: State Transition Safety
- **WHEN** any state writeback operation occurs
- **THEN** the current state and active run status are checked before proceeding