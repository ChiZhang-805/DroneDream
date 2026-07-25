import { afterEach, beforeEach, describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { History } from "../pages/History";
import { apiClient } from "../api/client";
import { fetchAllHistoryJobs } from "../features/history/fetchAllHistoryJobs";
import { I18nProvider } from "../i18n/I18nProvider";

function renderPage(locale: "en" | "zh-CN" = "en") {
  window.localStorage.setItem("drone-dream:locale", locale);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <MemoryRouter>
          <History />
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("History compare selection", () => {
  beforeEach(() => window.localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

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
    fireEvent.click(await screen.findByLabelText("Select job job_1"));
    fireEvent.click(await screen.findByLabelText("Select job job_2"));
    expect(button).not.toBeDisabled();
  });

  it("loads every job page instead of hiding history beyond the first page", async () => {
    const firstPage = Array.from({ length: 200 }, (_, index) => ({
      id: `job_${index + 1}`,
    }));
    const listSpy = vi.spyOn(apiClient, "listJobs")
      .mockResolvedValueOnce({
        items: firstPage,
        page: 1,
        page_size: 200,
        total: 201,
      } as never)
      .mockResolvedValueOnce({
        items: [{ id: "job_201" }],
        page: 2,
        page_size: 200,
        total: 201,
      } as never);

    const jobs = await fetchAllHistoryJobs();

    expect(jobs).toHaveLength(201);
    expect(jobs.at(-1)?.id).toBe("job_201");
    expect(listSpy).toHaveBeenNthCalledWith(1, { page: 1, page_size: 200 });
    expect(listSpy).toHaveBeenNthCalledWith(2, { page: 2, page_size: 200 });
  });

  it("filters jobs by name, simulator, and optimizer and clears every filter", async () => {
    vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [
        {
          id: "job_real",
          display_name: "Alpha flight",
          track_type: "circle",
          objective_profile: "robust",
          simulator_backend_requested: "real_cli",
          optimizer_strategy: "optimizer_portfolio",
          status: "COMPLETED",
          created_at: "2026-01-01",
          updated_at: "2026-01-01",
        },
        {
          id: "job_mock",
          display_name: "Beta workflow",
          track_type: "u_turn",
          objective_profile: "stable",
          simulator_backend_requested: "mock",
          optimizer_strategy: "heuristic",
          status: "FAILED",
          created_at: "2026-01-02",
          updated_at: "2026-01-02",
        },
      ],
      page: 1,
      page_size: 100,
      total: 2,
    } as never);
    renderPage();

    expect(await screen.findByText("job_real")).toBeVisible();
    expect(screen.getByText("job_mock")).toBeVisible();

    fireEvent.change(screen.getByLabelText("Search"), { target: { value: "Alpha" } });
    expect(screen.getByText("job_real")).toBeVisible();
    expect(screen.queryByText("job_mock")).toBeNull();

    fireEvent.change(screen.getByLabelText("Simulator"), { target: { value: "real_cli" } });
    fireEvent.change(screen.getByLabelText("Optimizer"), { target: { value: "optimizer_portfolio" } });
    fireEvent.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(screen.getByLabelText("Search")).toHaveValue("");
    expect(screen.getByLabelText("Simulator")).toHaveValue("ALL");
    expect(screen.getByLabelText("Optimizer")).toHaveValue("ALL");
    expect(screen.getByText("job_mock")).toBeVisible();
  });

  it("shows confirm modal and cancels deletion", async () => {
    const listSpy = vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [{ id: "job_1", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" }],
      page: 1, page_size: 100, total: 1,
    } as never);
    const deleteSpy = vi.spyOn(apiClient, "deleteJob").mockResolvedValue({ id: "job_1", deleted: true });
    renderPage();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete this job?" });
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    expect(document.querySelector("table.history-table-centered")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog", { name: "Delete this job?" })).not.toBeInTheDocument();
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
    expect(await screen.findByText("job_1")).toBeInTheDocument();
    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));
    fireEvent.click(screen.getByRole("button", { name: "Delete job" }));
    expect(deleteSpy).toHaveBeenCalledWith("job_1");
    await waitFor(() => expect(listSpy).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText("job_1")).not.toBeInTheDocument());
    listSpy.mockRestore();
    deleteSpy.mockRestore();
  });

  it("localizes filters, enum values, and the delete dialog as one language", async () => {
    vi.spyOn(apiClient, "listJobs").mockResolvedValue({
      items: [{ id: "job_zh", track_type: "circle", objective_profile: "robust", status: "COMPLETED", created_at: "2026-01-01", updated_at: "2026-01-01" }],
      page: 1,
      page_size: 100,
      total: 1,
    } as never);
    renderPage("zh-CN");

    expect(await screen.findByRole("heading", { name: "历史报告" })).toBeVisible();
    expect(screen.getByRole("option", { name: "圆形" })).toBeVisible();
    expect(screen.getByRole("option", { name: "鲁棒优先" })).toBeVisible();
    fireEvent.click(await screen.findByRole("button", { name: "删除" }));
    expect(screen.getByRole("dialog", { name: "确认删除任务？" })).toBeVisible();
    expect(screen.queryByText("Delete this job?")).toBeNull();
  });
});
