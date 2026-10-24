import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MapImportDialog } from "../features/autonomy/MapImportDialog";
import * as core from "../features/autonomy/agentCore";

vi.mock("../features/autonomy/AssetInterpretButton", () => ({ AssetInterpretButton: () => <button>AI</button> }));
beforeEach(() => {
  vi.restoreAllMocks();
  HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
});
function setup() {
  const imported = vi.fn();
  render(<MapImportDialog open chinese edition="universal" onClose={vi.fn()} onImported={imported} />);
  return imported;
}

describe("map upload dialog", () => {
  it("opens the checklist without opening a file picker; checks only a completed upload", async () => {
    let resolve!: (value: core.MapUploadReceipt | null) => void;
    const picker = vi.spyOn(core, "pickMapUpload").mockReturnValue(new Promise((done) => { resolve = done; }));
    setup();
    expect(picker).not.toHaveBeenCalled();
    expect(screen.getAllByRole("status")).toHaveLength(4);
    expect(screen.getByRole("button", { name: "导入" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "上传 地图场景" }));
    expect(screen.getByRole("status", { name: "地图场景 · 上传中" })).toBeVisible();
    await act(async () => resolve({ role: "scene", filePath: "cache/world.sdf", name: "campus.world", fileCount: 1 }));
    expect(screen.getByRole("status", { name: "地图场景 · 已上传" })).toBeVisible();
    expect(screen.getByRole("button", { name: "导入" })).toBeEnabled();
    expect(document.querySelector("dialog p")).toBeNull();
    expect(screen.queryByText(/必需|可选|required|optional/i)).not.toBeInTheDocument();
  });

  it("keeps the old upload when picking is cancelled and accepts a complete package without duplicate slots", async () => {
    const picker = vi.spyOn(core, "pickMapUpload").mockResolvedValueOnce({ role: "scene", filePath: "cache/map.ddpkg", name: "Campus.ddpkg", fileCount: 1 }).mockResolvedValueOnce(null);
    setup();
    fireEvent.click(screen.getByRole("button", { name: "上传 地图场景" }));
    await screen.findByText("Campus.ddpkg");
    expect(screen.getAllByRole("status")).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: "上传 地图场景" }));
    await waitFor(() => expect(picker).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Campus.ddpkg")).toBeVisible();
  });

  it("registers an uploaded map even while flight qualification is pending, without spending AI credits", async () => {
    vi.spyOn(core, "pickMapUpload").mockResolvedValue({ role: "scene", filePath: "cache/world.sdf", name: "campus.world", fileCount: 1 });
    vi.spyOn(core, "createMapUploadImport").mockResolvedValue({ job_id: "job" } as core.AgentCoreAssetImportJob);
    vi.spyOn(core, "processAgentCoreAssetImportJob").mockResolvedValue({ state: "needs_input", asset_id: "campus", normalized_content_sha256: "abc", required_inputs: ["qualification_evidence"] } as core.AgentCoreAssetImportJob);
    const version = { asset_id: "campus", content_sha256: "abc", maturity: "physics_ready", kind: "map", asset_ir: { name: "Campus" }, manifest: {}, imported_at: "2026-10-12T00:00:00Z" } as core.AgentCoreAssetVersion;
    vi.spyOn(core, "getAgentCoreBootstrap").mockResolvedValue({ asset_versions: [version] } as unknown as core.AgentCoreBootstrap);
    const imported = setup();
    fireEvent.click(screen.getByRole("button", { name: "上传 地图场景" }));
    await screen.findByText("campus.world");
    fireEvent.click(screen.getByRole("button", { name: "导入" }));
    await screen.findByRole("button", { name: "完成" });
    expect(imported).toHaveBeenCalledWith(version);
    expect(screen.getByRole("status", { name: "地图场景 · 已上传" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
