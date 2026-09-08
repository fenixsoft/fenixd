## ADDED Requirements

### Requirement: Dispatch Single-Flight Guard

#### Scenario: Startup Duplicate Dispatch Prevention
- **WHEN** daemon starts and processes both startup scan and event replay for the same spec
- **THEN** only one implementer run is dispatched for that spec, regardless of how many `spec_ready` events are received

#### Scenario: Concurrent Async Dispatch Handling
- **WHEN** multiple async calls to `_on_spec_ready` occur for the same spec before the first dispatch completes
- **THEN** only the first call proceeds with dispatch, subsequent calls are skipped

#### Scenario: Dispatch Completion Cleanup
- **WHEN** a dispatch attempt completes (success or failure)
- **THEN** the spec is removed from the pending dispatches registry, allowing future dispatches

#### Scenario: Worktree Lock Coordination
- **WHEN** a spec has an active worktree lock held by a live attempt
- **THEN** duplicate dispatches are skipped without entering backoff or consuming attempt quota