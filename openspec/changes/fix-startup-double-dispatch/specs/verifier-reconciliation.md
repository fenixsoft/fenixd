## ADDED Requirements

### Requirement: Verifier Final State Reconciliation

#### Scenario: Verification Completed with State Changed
- **WHEN** verifier completes and spec state is no longer "testing" due to race conditions
- **THEN** verification results are reconciled based on report and implementation status

#### Scenario: Verification Passed and Implementation Merged
- **WHEN** verifier report shows pass and implementation is merged
- **THEN** spec state is replayed through legal transition path (implemented → testing → verified → done)

#### Scenario: Verification Failed or Implementation Not Merged
- **WHEN** verifier report shows fail or implementation is not merged
- **THEN** spec is blocked with evidence from verification report

#### Scenario: Verification Results Never Lost
- **WHEN** verifier completes regardless of spec state
- **THEN** verification conclusion is never silently discarded