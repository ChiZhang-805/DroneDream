import type {
  FieldHardwareTuningPlan,
  FieldTuningDemoReceipt,
  FieldTuningDemoRequest,
  FieldTuningStatus,
} from "../desktop/bridge";

const FIXTURE_COMMIT = "0000000000000000000000000000000000000000";
const FIXTURE_PACK = `sha256:${"0".repeat(64)}`;

function round(value: number): number {
  return Math.round(value * 10_000) / 10_000;
}

function fixtureDigest(index: number): string {
  return index.toString(16).padStart(64, "0");
}

export function fieldBrowserStatus(): FieldTuningStatus {
  return {
    schemaVersion: 1,
    kind: "dronedream-field-tuning-status",
    editionId: "field",
    executionDomain: "real-hardware",
    runtimeProfile: "field-lightweight",
    sourceCommit: FIXTURE_COMMIT,
    enginePackId: FIXTURE_PACK,
    contractSha256: "0".repeat(64),
    simulationSupported: false,
    modelRole: "proposal-only",
    harnessRole: "bounded-execution-evidence-and-rollback",
    demoAvailable: true,
    hardwareAuthority: false,
    validatedPackCount: 0,
    blockers: [
      "field.registry.zero-validated-packs",
      "field.device.not-bound",
      "field.quorum.missing",
    ],
  };
}

export function runFieldBrowserFixture(
  request: FieldTuningDemoRequest,
): FieldTuningDemoReceipt {
  const candidates = Array.from({ length: request.maxIterations }, (_, index) => {
    const progress = index;
    const trackingError = round(Math.max(0.22, 0.78 - 0.085 * progress));
    const overshootPercent = round(Math.max(6, 18 - 2.1 * progress));
    const controlEffort = round(0.46 + 0.025 * progress);
    const score = round(
      trackingError * 0.68 + (overshootPercent / 100) * 0.22 + controlEffort * 0.1,
    );
    return {
      iteration: index + 1,
      proposalSource: "deterministic-model-fixture" as const,
      parameters: {
        MC_ROLL_P: round(6.35 + 0.12 * progress),
        MC_PITCH_P: round(6.35 + 0.12 * progress),
        MPC_XY_VEL_P_ACC: round(1.75 + 0.04 * progress),
      },
      candidateSha256: fixtureDigest(index + 1),
      trackingError,
      overshootPercent,
      controlEffort,
      score,
      accepted: score <= request.targetScore,
      failureClass: "none" as const,
    };
  });
  const selected = [...candidates].sort((left, right) => left.score - right.score)[0];
  if (!selected) throw new Error("Field fixture produced no candidate");
  const holdoutScore = round(Math.min(1, selected.score + 0.035));
  const holdoutPassed = holdoutScore <= request.targetScore;
  return {
    schemaVersion: 1,
    kind: "dronedream-field-tuning-demo-receipt",
    jobId: `field-browser-demo-${request.maxIterations}`,
    editionId: "field",
    executionDomain: "real-hardware",
    executionMode: "fixture-only-no-device-io",
    sourceCommit: FIXTURE_COMMIT,
    enginePackId: FIXTURE_PACK,
    objective: request.objective,
    budget: {
      maxIterations: request.maxIterations,
      usedIterations: candidates.length,
      providerRequests: 0,
      hardwareTrials: 0,
    },
    candidates,
    selectedCandidateSha256: selected.candidateSha256,
    holdout: {
      independent: true,
      score: holdoutScore,
      passed: holdoutPassed,
      fixture: true,
    },
    qualification: {
      status: holdoutPassed ? "demo-qualified" : "demo-rejected",
      hardwareValid: false,
      reason: "Fixture evidence never qualifies hardware",
    },
    hardwareActionsPerformed: [],
    hardwareAuthority: false,
    receiptSha256: "f".repeat(64),
  };
}

export function fieldBrowserHardwareDenial(): FieldHardwareTuningPlan {
  return {
    schemaVersion: 1,
    kind: "dronedream-field-hardware-tuning-plan",
    jobId: "field-browser-hardware-plan-fixture",
    editionId: "field",
    executionDomain: "real-hardware",
    sourceCommit: FIXTURE_COMMIT,
    requestSha256: "0".repeat(64),
    snapshotSha256: null,
    observationSha256: null,
    budget: {
      maxIterations: 5,
      hardwareTrialBudget: 0,
      parameterWriteBudget: 0,
      providerRequests: 0,
    },
    phases: [
      "snapshot-binding",
      "candidate-validation",
      "operator-confirmation",
      "controlled-trial",
      "telemetry-capture",
      "scoring-and-failure-classification",
      "independent-holdout",
      "publish-or-rollback",
    ],
    canExecute: false,
    hardwareAuthority: false,
    hardwareWriteAttempts: 0,
    requiredEvidence: [
      "validated-vehicle-pack",
      "controller-and-firmware-match",
      "protocol-observation-receipt",
      "parameter-snapshot",
      "transaction-rollback",
      "operator-confirmation",
      "preflight",
      "safety-zone",
      "control-takeover",
      "emergency-stop",
      "native-backend-runtime-quorum",
    ],
    blockers: [
      "field.registry.zero-validated-packs",
      "field.snapshot.missing",
      "field.protocol-observation.missing",
      "field.device.transport-unavailable",
      "field.quorum.missing",
      "field.operator-confirmation.missing",
    ],
    planSha256: "1".repeat(64),
  };
}
