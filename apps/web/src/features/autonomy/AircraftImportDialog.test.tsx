import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AircraftImportDialog } from "./AircraftImportDialog";
import { getAgentCoreBootstrap, pickAndCreateAgentCoreAssetImportJob, processAgentCoreAssetImportJob } from "./agentCore";
vi.mock("./agentCore", () => ({ getAgentCoreBootstrap: vi.fn(), pickAndCreateAgentCoreAssetImportJob: vi.fn(), processAgentCoreAssetImportJob: vi.fn() }));
const job = { job_id: "import-1", source_name: "aircraft.zip", asset_id: "new-aircraft", normalized_content_sha256: "a".repeat(64), state: "normalized" };
describe("aircraft upload", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  });
  it("opens the chooser only on upload, retains a received package after cancel, and imports its normalized version", async () => {
    const onImported = vi.fn();
    const version = { asset_id: job.asset_id, content_sha256: job.normalized_content_sha256, maturity: "normalized" };
    vi.mocked(pickAndCreateAgentCoreAssetImportJob).mockResolvedValueOnce(job as never).mockResolvedValueOnce(null);
    vi.mocked(processAgentCoreAssetImportJob).mockResolvedValue(job as never);
    vi.mocked(getAgentCoreBootstrap).mockResolvedValue({ asset_versions: [version] } as never);
    render(<AircraftImportDialog open chinese={false} adapters={[]} onClose={vi.fn()} onImported={onImported} />);
    expect(pickAndCreateAgentCoreAssetImportJob).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", {name:"Upload Aircraft package"}));
    await screen.findByText("aircraft.zip");
    await waitFor(() => expect(screen.getByRole("button", {name:"Upload Model & dependencies folder"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button", {name:"Upload Model & dependencies folder"}));
    await waitFor(() => expect(screen.getByRole("button", {name:"Import"})).toBeEnabled());
    expect(screen.getByText("aircraft.zip")).toBeVisible();
    fireEvent.click(screen.getByRole("button", {name:"Import"}));
    await waitFor(() => expect(onImported).toHaveBeenCalledWith(version));
    expect(screen.getByRole("button", {name:"Done"})).toBeEnabled();
  });
  it("keeps uploaded files when processing requires dependencies", async () => {
    vi.mocked(pickAndCreateAgentCoreAssetImportJob).mockResolvedValue(job as never);
    vi.mocked(processAgentCoreAssetImportJob).mockResolvedValue({...job,state:"needs_input"} as never);
    vi.mocked(getAgentCoreBootstrap).mockResolvedValue({asset_versions:[]} as never);
    const onImported=vi.fn();
    render(<AircraftImportDialog open chinese={false} adapters={[]} onClose={vi.fn()} onImported={onImported} />);
    fireEvent.click(screen.getByRole("button",{name:"Upload Aircraft package"}));
    await screen.findByText("aircraft.zip");
    await waitFor(()=>expect(screen.getByRole("button",{name:"Import"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"Import"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("dependencies or conversion");
    expect(screen.getByText("aircraft.zip")).toBeVisible();
    expect(onImported).not.toHaveBeenCalled();
  });
});
