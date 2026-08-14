import { beforeEach, describe, expect, it, vi } from "vitest";

import { createVehicleModelDraft } from "../features/vehicleStudio/model";

const supabaseMock = vi.hoisted(() => ({
  from: vi.fn(),
}));

vi.mock("../features/auth/supabaseClient", () => ({
  supabaseClient: { from: supabaseMock.from },
}));

import {
  loadCloudVehicleModels,
  saveCloudVehicleModel,
  type VehicleModelBoundary,
} from "../features/vehicleStudio/cloudStorage";

const USER_ID = "00000000-0000-4000-8000-000000000001";
const boundary: VehicleModelBoundary = {
  userId: USER_ID,
  tenantId: USER_ID,
  organizationId: null,
  workspaceId: "console-universal",
  edition: "universal",
};

describe("vehicle studio cloud storage", () => {
  beforeEach(() => {
    supabaseMock.from.mockReset();
  });

  it("reads every tenant-scoped page before applying local model and revision caps", async () => {
    const firstDraft = createVehicleModelDraft(new Date("2026-08-14T00:00:00.000Z"));
    const secondDraft = createVehicleModelDraft(new Date("2026-08-13T00:00:00.000Z"));
    const firstPage = Array.from({ length: 1_000 }, (_, index) => {
      const revision = index + 1;
      return {
        draft_id: firstDraft.draftId,
        revision,
        model: { ...firstDraft, revision },
      };
    });
    const secondPage = [{
      draft_id: secondDraft.draftId,
      revision: secondDraft.revision,
      model: secondDraft,
    }];
    const range = vi.fn()
      .mockResolvedValueOnce({ data: firstPage, error: null })
      .mockResolvedValueOnce({ data: secondPage, error: null });
    const query: Record<string, ReturnType<typeof vi.fn>> = {
      select: vi.fn(),
      eq: vi.fn(),
      order: vi.fn(),
      range,
    };
    query.select.mockReturnValue(query);
    query.eq.mockReturnValue(query);
    query.order.mockReturnValue(query);
    supabaseMock.from.mockReturnValue(query);

    const models = await loadCloudVehicleModels(boundary);

    expect(range).toHaveBeenNthCalledWith(1, 0, 999);
    expect(range).toHaveBeenNthCalledWith(2, 1_000, 1_999);
    expect(models).toHaveLength(2);
    expect(models?.find((model) => model.draftId === firstDraft.draftId)?.revisions)
      .toHaveLength(40);
    expect(models?.find((model) => model.draftId === secondDraft.draftId)?.revisions)
      .toHaveLength(1);
  });

  it("uses insert-only publication and rejects an immutable revision conflict", async () => {
    const draft = createVehicleModelDraft(new Date("2026-08-14T00:00:00.000Z"));
    const insert = vi.fn().mockResolvedValue({ error: { code: "23505" } });
    supabaseMock.from.mockReturnValue({ insert });

    await expect(saveCloudVehicleModel(boundary, draft))
      .rejects.toThrow("already exists and cannot be overwritten");
    expect(insert).toHaveBeenCalledWith(expect.objectContaining({
      draft_id: draft.draftId,
      revision: draft.revision,
      model: draft,
    }));
  });

  it("publishes a new immutable revision with insert", async () => {
    const draft = createVehicleModelDraft(new Date("2026-08-14T00:00:00.000Z"));
    const insert = vi.fn().mockResolvedValue({ error: null });
    supabaseMock.from.mockReturnValue({ insert });

    await expect(saveCloudVehicleModel(boundary, draft)).resolves.toBe(true);
    expect(insert).toHaveBeenCalledOnce();
  });
});
