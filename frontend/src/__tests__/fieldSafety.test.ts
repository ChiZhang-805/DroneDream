import { describe, expect, it } from "vitest";

import {
  evaluateFieldSafety,
  FIELD_HARDWARE_ACTIONS,
  FIELD_OBSERVATION_FIXTURES,
  FIELD_VALIDATED_PACK_COUNT,
} from "../field/safety";

describe("Field safety decision", () => {
  it("binds the product to the current zero-validated-pack registry", () => {
    expect(FIELD_VALIDATED_PACK_COUNT).toBe(0);
  });

  it.each(Object.entries(FIELD_OBSERVATION_FIXTURES))(
    "keeps every hardware action denied for %s",
    (_state, observation) => {
      const decision = evaluateFieldSafety(observation);

      expect(decision.frontendIsAuthority).toBe(false);
      expect(decision.observationGrantsAuthority).toBe(false);
      expect(decision.readOnlyObservationAllowed).toBe(true);
      expect(decision.validatedPackCount).toBe(0);
      expect(decision.actions).toEqual(
        Object.fromEntries(FIELD_HARDWARE_ACTIONS.map((action) => [action, false])),
      );
      expect(decision.blockers).toContain("field.registry.zero-validated-packs");
    },
  );

  it("does not treat a recognized controller and firmware match as authorization", () => {
    const decision = evaluateFieldSafety(
      FIELD_OBSERVATION_FIXTURES["recognized-unvalidated"],
    );

    expect(decision.threeLayerQuorum).toBe("missing");
    expect(decision.blockers).toContain("field.device.pack-unvalidated");
    expect(decision.blockers).toContain(
      "field.quorum.vehicle-pack-receipt-missing",
    );
  });

  it("reports unknown devices and firmware drift as distinct blockers", () => {
    expect(
      evaluateFieldSafety(FIELD_OBSERVATION_FIXTURES["unknown-device"]).blockers,
    ).toContain("field.device.unknown");
    expect(
      evaluateFieldSafety(FIELD_OBSERVATION_FIXTURES["firmware-drift"]).blockers,
    ).toEqual(expect.arrayContaining([
      "field.device.firmware-drift",
      "field.quorum.firmware-match-missing",
    ]));
  });
});
