# Structured artifact flow

Every arrow below is a serialized, validated boundary. Model prose is retained only as
an explanation field inside a typed artifact; it is never forwarded as an actuator command.

| Stage | Structured input | Structured output | Consumer and gate |
|---|---|---|---|
| Request intake | `MissionRequest`, `ConversationWindow`, `MapCatalog` | `IntentArtifact` | Intent critic checks ambiguity and map grounding |
| Intent critique | Request + intent + catalog | `IntentCritique` | Bounded loop repairs intent or fails |
| Contract freeze | Accepted intent | `MissionContract` | Exact ID must later be confirmed by the operator |
| Decomposition | Frozen contract + bounded context | `TaskGraphArtifact` | IDs, dependencies, task types, and semantic targets validated |
| Semantic planning | Contract + task graph + map catalog | `SemanticPlan` | Tool layer resolves geometry |
| Route tool | `RouteQuery` + qualified graph | `GraphRoute` + `ToolReceipt` | Generic shortest-path and flight-verification constraints |
| Clearance tool | Route + semantic collision geometry + vehicle envelope | `RouteClearanceReport` + receipt | Zero forbidden collisions and minimum clearance |
| PX4 track tool | `Px4TrackRequest` + graph + map frame | `Px4Track` + receipt | ENU/world/NED coordinate contract frozen |
| Plan critique | Plan + route + clearance + track summaries | `PlanCritique` | Bounded repair loop; model cannot waive tool failures |
| Preparation | All accepted artifacts + call records + receipts | `PreparedMission` | Canonical hash binds the entire prepared mission |
| Task lifecycle | Conversation + prepared hash + source-message hash | `TaskThread`, `PlanRevisionRecord`, `MissionLifecycleBinding` | Same mission ID; old revision superseded atomically |
| Launch | Prepared mission + explicit contract ID + file hashes | Runtime process set | Any mismatch fails before launch |
| Runtime message ingress | Active `RuntimeControlSession` + user text | `RuntimeUserMessage` | Exact conversation, mission, plan, contract, and execution IDs required |
| Immediate hold | Runtime message + PX4 telemetry | `RuntimeHoldAcknowledgement` | Old track and semantic side effects disabled before any model call |
| Runtime classification | Message + stable-hold evidence + current mission | `RuntimeInterruptionDecision` | Code alone authorizes resume, replan hold, or landing |
| Runtime reroute | Decision + hold telemetry + map graph + map semantics + vehicle envelope | `RuntimeReplacementTrack` | Target grounding, route, continuous clearance, hashes, and prior-track binding must all pass |
| Checkpoint | `RuntimeCheckpointRequest` | `RuntimeCheckpointDecision` | Code recomputes binding and safety authorization |
| Runtime collection | Gazebo poses + ROS observations + PX4 state/ULog + process/timing records | `Px4GazeboRunEvidence` | Deterministic gates evaluate observed execution |
| Completion review | Prepared mission + bounded evidence summary | `CompletionAssessment` | Advisory review only |
| Final acceptance | Runtime evidence + completion assessment + hash-linked ledger | `SimulationWorkflowResult` | `verified` only when every mandatory code gate passes |

## Files produced by preparation

```text
prepared-mission.json       Complete structured planning result
mission-lifecycle.json      Stable mission ID and this plan revision binding
mission-request.json        Original user request
intent-artifact.json        Grounded interpreted intent
intent-critique.json        Accepted critique or final rejection
mission-contract.json       Frozen authorization boundary
task-graph.json             Dependency-ordered mission tasks
semantic-plan.json          Model-authored semantic movement plan
graph-route.json            Tool-computed geometric route
clearance-report.json       Sampled static collision evidence
px4-track.json              Bound world/ENU/PX4 trajectory
plan-critique.json          Final planning review
context-window.json         Durable bounded conversation context
model-calls.json            Provider/model/token/latency records
tool-receipts.json          Plugin input/output hashes and authority
evidence.jsonl              Hash-linked preparation ledger
```

Preparation artifacts are never sufficient evidence that a flight succeeded.

## Files produced by execution

```text
workflow-result.json        Final verified/failed result
runtime-control/session.json Exact active execution identity
runtime-control/inbox/       Atomically submitted runtime messages
runtime-control/detected/    Pre-model track/side-effect inhibition evidence
runtime-control/acks/        Stable-hover telemetry and latency evidence
runtime-control/decisions/   Model classification plus code authorization gates
runtime-control/side-effects.state.json Shared semantic-action interlock
runtime-evidence.json       Typed PX4/Gazebo/ROS measurements and gates
checkpoint-requests.jsonl   Exact observations presented to the model
checkpoint-decisions.jsonl  Typed responses plus code authorization result
gazebo-poses.csv             High-rate world observations
ros-observations.csv         ROS observation-node output
processes.json               Launch/exit identity and return-code evidence
timing.json                  Simulator, track, landing, and wall-clock timing
completion-assessment.json  Final model review
evidence.jsonl              Extended hash-linked workflow ledger
```

The PX4 ULog is large and may remain in PX4's runtime log directory. Its exact path,
size, and SHA-256 are included in runtime evidence. A portable acceptance manifest may
therefore prove which log was used without committing the binary log to Git.

## Coordinate contract

Map nodes and Gazebo observations use world ENU meters. The offboard executor converts
each validated world point to PX4 local NED using the frozen origin and axis mapping in
`Px4CoordinateContract`. Runtime checkpoint requests carry both semantic identity and
route/track indices so a plausible-looking position from another segment cannot authorize
continuation.

## Changing a contract

1. Update the Pydantic model in `contracts.py`.
2. Update every producer and consumer in the same change.
3. Run `python scripts/export_schemas.py`.
4. Run `python scripts/export_schemas.py --check`, Ruff, and pytest.
5. Re-run the relevant real ROS/Gazebo/PX4 acceptance level; unit tests alone are not
   evidence of simulator compatibility.
