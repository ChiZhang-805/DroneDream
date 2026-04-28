import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { BatchCreate } from "../pages/BatchCreate";
import { apiClient } from "../api/client";

const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <BatchCreate />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  navigateMock.mockReset();
  vi.restoreAllMocks();
});

describe("BatchCreate", () => {
  it("validates JSON array before submitting", async () => {
    const spy = vi.spyOn(apiClient, "createBatch").mockResolvedValue({ id: "bat_1" } as never);
    renderPage();

    fireEvent.change(screen.getByLabelText(/Jobs JSON Array/i), { target: { value: "{}" } });
    fireEvent.click(screen.getByRole("button", { name: /Create Batch/i }));

    expect(await screen.findByText(/must be an array/i)).toBeInTheDocument();
    expect(spy).not.toHaveBeenCalled();
  });
});
