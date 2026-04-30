import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { History } from "../pages/History";
import { apiClient } from "../api/client";

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <History />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("History compare selection", () => {
  it("enables Compare button after selecting at least two jobs", async () => {
    vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [
        { id: "job_1", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" },
        { id: "job_2", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" },
      ],
      page: 1,
      page_size: 100,
      total: 2,
    } as never);
    renderPage();
    const button = await screen.findByRole("button", { name: /Compare selected/i });
    expect(button).toBeDisabled();
    fireEvent.click(await screen.findByLabelText("select-job_1"));
    fireEvent.click(await screen.findByLabelText("select-job_2"));
    expect(button).not.toBeDisabled();
  });

  it("shows confirm modal and cancels deletion", async () => {
    const listSpy = vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [{ id: "job_1", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" }],
      page: 1, page_size: 100, total: 1,
    } as never);
    const deleteSpy = vi.spyOn(apiClient, "deleteJob").mockResolvedValue({ id: "job_1", deleted: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    expect(screen.getByText("确认删除 job")).toBeInTheDocument();
    expect(document.querySelector("table.history-table-centered")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByText("确认删除 job")).not.toBeInTheDocument();
    expect(deleteSpy).not.toHaveBeenCalled();
    listSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("confirms deletion and refetches jobs", async () => {
    const listSpy = vi.spyOn(apiClient, "listJobs")
      .mockResolvedValueOnce({ items: [{ id: "job_1", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" }], page: 1, page_size: 100, total: 1 } as never)
      .mockResolvedValueOnce({ items: [], page: 1, page_size: 100, total: 0 } as never);
    const deleteSpy = vi.spyOn(apiClient, "deleteJob").mockResolvedValue({ id: "job_1", deleted: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "确定删除" }));
    expect(deleteSpy).toHaveBeenCalledWith("job_1");
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/Compare selected/)).toBeInTheDocument();
    listSpy.mockRestore();
    deleteSpy.mockRestore();
  });
});
