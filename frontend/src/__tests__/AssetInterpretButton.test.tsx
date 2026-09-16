import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AssetInterpretButton } from "../features/autonomy/AssetInterpretButton";
import { ModelAccessContext, type ModelAccessContextValue } from "../features/settings/ModelAccessContext";
import * as planning from "../features/autonomy/agentCorePlanning";

vi.mock("../features/auth/AuthContext", () => ({ useOptionalAuth: () => ({ account: { id: "account-test" } }) }));
const access = { settings: { accessMode: "platform", managedProvider: "kimi", managedModel: "kimi-k2.6" } } as ModelAccessContextValue;
const props = { edition: "autonomy", chinese: true, kind: "map", assetId: "school-map", contentSha256: "a".repeat(64), name: "School Map" } as const;
const result = { cache_key: "key", cached: false, source: { asset_id: "school-map", content_sha256: "a".repeat(64), kind: "map" as const }, understanding: { summary: "Map", items: [], limitations: [] }, model_calls: [] };

describe("asset interpretation icon", () => {
  it("uses the selected model and exact asset, without adding explanatory text", async () => {
    const spy = vi.spyOn(planning, "interpretAgentCoreAsset").mockResolvedValue(result);
    render(<ModelAccessContext.Provider value={access}><AssetInterpretButton {...props} /></ModelAccessContext.Provider>);
    const button = screen.getByRole("button", { name: "解析 School Map" });
    expect(button.textContent).toBe("");
    expect(button).toHaveClass("autonomy-repository-interpret");
    fireEvent.click(button);
    expect(await screen.findByRole("button", { name: "已解析 School Map" })).toBeEnabled();
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ provider: "kimi", model: "kimi-k2.6", contentSha256: props.contentSha256, accountId: "account-test" }));
  });

  it("blocks repeat clicks and ignores an old response after the asset changes", async () => {
    let resolve!: (value: typeof result) => void;
    const spy = vi.spyOn(planning, "interpretAgentCoreAsset").mockImplementation(() => new Promise((done) => { resolve = done; }));
    const view = render(<ModelAccessContext.Provider value={access}><AssetInterpretButton {...props} /></ModelAccessContext.Provider>);
    const button = screen.getByRole("button");
    fireEvent.click(button);
    fireEvent.click(button);
    expect(spy).toHaveBeenCalledTimes(1);
    view.rerender(<ModelAccessContext.Provider value={access}><AssetInterpretButton {...props} contentSha256={"b".repeat(64)} /></ModelAccessContext.Provider>);
    resolve(result);
    await waitFor(() => expect(screen.getByRole("button")).toHaveAccessibleName("解析 School Map"));
  });

  it("reports failure through the icon label and permits a deliberate retry", async () => {
    vi.spyOn(planning, "interpretAgentCoreAsset").mockRejectedValue(new Error("source unavailable"));
    render(<ModelAccessContext.Provider value={access}><AssetInterpretButton {...props} /></ModelAccessContext.Provider>);
    fireEvent.click(screen.getByRole("button"));
    expect(await screen.findByRole("button", { name: /解析失败/ })).toBeEnabled();
  });
});
