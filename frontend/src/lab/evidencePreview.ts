export const MAX_LAB_EVIDENCE_BYTES = 256 * 1024;

const SHA256 = /^[a-f0-9]{64}$/;
const PARAMETER_NAME = /^[A-Z][A-Z0-9_]{1,63}$/;

export interface LabParameterPreview {
  name: string;
  value: number;
  unit: string | null;
}
export interface LabEvidencePreview {
  fileName: string;
  kind: "dronedream-simulation-qualification-receipt";
  sourceEdition: "sim";
  commonCoreCommit: string;
  vehiclePackId: string;
  qualificationLevel: "sim" | "hitl";
  qualificationDecision: string;
  evidenceHash: string;
  holdoutContractHash: string;
  parameterCandidateHash: string;
  parameters: LabParameterPreview[];
  authorityDecision: "deny";
  previewOnly: true;
}

export class LabEvidencePreviewError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LabEvidencePreviewError";
  }
}

function objectValue(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new LabEvidencePreviewError(`${label} must be an object.`);
  }
  return value as Record<string, unknown>;
}

function stringValue(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new LabEvidencePreviewError(`${label} must be a non-empty string.`);
  }
  return value.trim();
}

function sha256Value(value: unknown, label: string): string {
  const normalized = stringValue(value, label).toLowerCase();
  if (!SHA256.test(normalized)) {
    throw new LabEvidencePreviewError(`${label} must be a lowercase SHA-256 value.`);
  }
  return normalized;
}

export function parseLabEvidencePreview(
  fileName: string,
  source: string,
): LabEvidencePreview {
  const byteLength = new TextEncoder().encode(source).byteLength;
  if (byteLength === 0) {
    throw new LabEvidencePreviewError("The evidence file is empty.");
  }
  if (byteLength > MAX_LAB_EVIDENCE_BYTES) {
    throw new LabEvidencePreviewError("The evidence file exceeds the 256 KiB preview limit.");
  }

  let decoded: unknown;
  try {
    decoded = JSON.parse(source);
  } catch {
    throw new LabEvidencePreviewError("The evidence file is not valid JSON.");
  }

  const receipt = objectValue(decoded, "Evidence receipt");
  const kind = stringValue(receipt.kind, "Evidence kind");
  if (kind !== "dronedream-simulation-qualification-receipt") {
    throw new LabEvidencePreviewError("Only simulation qualification receipts can be previewed.");
  }
  if (receipt.schemaVersion !== 1) {
    throw new LabEvidencePreviewError("The evidence schema version is unsupported.");
  }

  const sourceBinding = objectValue(receipt.source, "Evidence source");
  const sourceEdition = stringValue(sourceBinding.editionId, "Source edition");
  if (sourceEdition !== "sim") {
    throw new LabEvidencePreviewError("The evidence source edition must be sim.");
  }
  const commonCoreCommit = stringValue(
    sourceBinding.commonCoreCommit,
    "Common-core commit",
  ).toLowerCase();
  if (!/^[a-f0-9]{40}$/.test(commonCoreCommit)) {
    throw new LabEvidencePreviewError("Common-core commit must be a full Git commit.");
  }

  const vehicle = objectValue(receipt.vehicle, "Vehicle binding");
  const qualification = objectValue(receipt.qualification, "Qualification");
  const parameterCandidate = objectValue(
    receipt.parameterCandidate,
    "Parameter candidate",
  );
  const qualificationLevel = stringValue(
    qualification.level,
    "Qualification level",
  );
  if (qualificationLevel !== "sim" && qualificationLevel !== "hitl") {
    throw new LabEvidencePreviewError("Qualification level must be sim or hitl.");
  }

  const rawParameters = parameterCandidate.parameters;
  if (!Array.isArray(rawParameters) || rawParameters.length > 64) {
    throw new LabEvidencePreviewError("Parameter candidate must contain at most 64 parameters.");
  }
  const parameters = rawParameters.map((rawParameter, index) => {
    const parameter = objectValue(rawParameter, `Parameter ${index + 1}`);
    const name = stringValue(parameter.name, `Parameter ${index + 1} name`);
    if (!PARAMETER_NAME.test(name)) {
      throw new LabEvidencePreviewError(`Parameter ${index + 1} name is unsupported.`);
    }
    if (typeof parameter.value !== "number" || !Number.isFinite(parameter.value)) {
      throw new LabEvidencePreviewError(`Parameter ${index + 1} value must be finite.`);
    }
    return {
      name,
      value: parameter.value,
      unit: typeof parameter.unit === "string" && parameter.unit.trim()
        ? parameter.unit.trim()
        : null,
    };
  });

  return {
    fileName,
    kind,
    sourceEdition,
    commonCoreCommit,
    vehiclePackId: stringValue(vehicle.packId, "Vehicle Pack ID"),
    qualificationLevel,
    qualificationDecision: stringValue(
      qualification.decision,
      "Qualification decision",
    ),
    evidenceHash: sha256Value(qualification.evidenceHash, "Evidence hash"),
    holdoutContractHash: sha256Value(
      qualification.holdoutContractHash,
      "Holdout contract hash",
    ),
    parameterCandidateHash: sha256Value(
      parameterCandidate.hash,
      "Parameter candidate hash",
    ),
    parameters,
    authorityDecision: "deny",
    previewOnly: true,
  };
}
