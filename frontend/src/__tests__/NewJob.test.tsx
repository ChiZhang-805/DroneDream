import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { NewJob } from "../pages/NewJob";
import { apiClient, ApiClientError } from "../api/client";
import type { Job } from "../types/api";

// Silence react-router's "no matching route" warning when we navigate post-submit.
const navigateMock = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>(
    "react-router-dom",
  );
  return {
    ...actual,
    useNavigate: () => navigateMock,
  };
});

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewJob />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function setNumeric(label: RegExp, value: string) {
  const input = screen.getByLabelText(label) as HTMLInputElement;
  fireEvent.change(input, { target: { value } });
}

beforeEach(() => {
  navigateMock.mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("NewJob — documented defaults", () => {
  it("renders the defaults specified in the New Job contract", () => {
    renderPage();

    // Selects compare against string values; number inputs compare against
    // their parsed numeric value per jest-dom's toHaveValue semantics.
    expect(screen.getByLabelText(/Track type/i)).toHaveValue("circle");
    expect(screen.getByLabelText(/Altitude/i)).toHaveValue(3);
    expect(screen.getByLabelText(/Wind north/i)).toHaveValue(0);
    expect(screen.getByLabelText(/Wind east/i)).toHaveValue(0);
    expect(screen.getByLabelText(/Wind south/i)).toHaveValue(0);
    expect(screen.getByLabelText(/Wind west/i)).toHaveValue(0);
    expect(screen.getByLabelText(/Sensor noise/i)).toHaveValue("medium");
    expect(screen.getByLabelText(/Objective profile/i)).toHaveValue("robust");
  });
});

describe("NewJob — client-side validation", () => {
  it("rejects altitude above 20.0 and blocks submission", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();

    setNumeric(/Altitude/i, "25.0");
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    expect(await screen.findByText(/Must be between 1.0 and 20.0/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("rejects altitude below 1.0 and blocks submission", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();

    setNumeric(/Altitude/i, "0.5");
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    expect(await screen.findByText(/Must be between 1.0 and 20.0/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("rejects wind components outside [-10, 10] and blocks submission", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();

    setNumeric(/Wind north/i, "25");
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    expect(await screen.findByText(/Must be between -10 and 10/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("rejects non-numeric values in required numeric fields", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();

    setNumeric(/Altitude/i, "abc");
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    expect(await screen.findByText(/Required numeric value/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("requires valid reference_track JSON with at least 2 points when track=custom", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();

    fireEvent.change(screen.getByLabelText(/Track type/i), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByLabelText(/Reference track \(JSON\)/i), {
      target: { value: "{\"x\":1}" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));
    expect(await screen.findByText(/Must be JSON array/i)).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/Reference track \(JSON\)/i), {
      target: { value: "[{\"x\":0,\"y\":0}]" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));
    expect(
      await screen.findByText(/Custom track requires at least 2 points/i),
    ).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });
});

describe("NewJob — Phase 8 execution backend & auto-tuning", () => {
  it("renders defaults for simulator_backend and optimizer_strategy", () => {
    renderPage();
    expect(screen.getByLabelText(/Simulator backend/i)).toHaveValue("mock");
    expect(screen.getByLabelText(/Optimizer strategy/i)).toHaveValue(
      "gpt",
    );
    expect(screen.getByLabelText(/Max iterations/i)).toHaveValue(20);
    expect(screen.getByLabelText(/Trials per candidate/i)).toHaveValue(3);
    expect(screen.getByLabelText(/Min pass rate/i)).toHaveValue(0.8);
  });

  it("shows the OpenAI API key field only when strategy is gpt", () => {
    renderPage();
    expect(screen.getByLabelText(/OpenAI API key/i)).toBeVisible();
    fireEvent.change(screen.getByLabelText(/Optimizer strategy/i), {
      target: { value: "heuristic" },
    });
    expect(screen.queryByLabelText(/OpenAI API key/i)).toBeNull();
    expect(screen.queryByLabelText(/OpenAI model/i)).toBeNull();
  });

  it("blocks submission when strategy=gpt and api key is blank", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_unused" } as unknown as Job);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));
    expect(
      await screen.findByText(/API key required when strategy is gpt/i),
    ).toBeVisible();
    expect(createSpy).not.toHaveBeenCalled();
  });

  it("submits the full Phase 8 payload when gpt fields are filled", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_created" } as unknown as Job);
    renderPage();
    fireEvent.change(screen.getByLabelText(/Optimizer strategy/i), {
      target: { value: "gpt" },
    });
    fireEvent.change(screen.getByLabelText(/Simulator backend/i), {
      target: { value: "real_cli" },
    });
    fireEvent.change(screen.getByLabelText(/OpenAI API key/i), {
      target: { value: "sk-testing" },
    });
    fireEvent.change(screen.getByLabelText(/OpenAI model/i), {
      target: { value: "gpt-4.1" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.simulator_backend).toBe("real_cli");
    expect(payload.optimizer_strategy).toBe("gpt");
    expect(payload.openai?.api_key).toBe("sk-testing");
    expect(payload.openai?.model).toBe("gpt-4.1");
    expect(payload.acceptance_criteria?.min_pass_rate).toBe(0.8);
  });

  it("submits reference_track payload for custom track", async () => {
    const createSpy = vi
      .spyOn(apiClient, "createJob")
      .mockResolvedValue({ id: "job_created" } as unknown as Job);
    renderPage();
    fireEvent.change(screen.getByLabelText(/Track type/i), {
      target: { value: "custom" },
    });
    fireEvent.change(screen.getByLabelText(/Reference track \(JSON\)/i), {
      target: {
        value:
          '[{"x":0,"y":0,"z":3},{"x":5,"y":0,"z":3},{"x":5,"y":5}]',
      },
    });
    fireEvent.change(screen.getByLabelText(/OpenAI API key/i), {
      target: { value: "sk-testing" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    await waitFor(() => expect(createSpy).toHaveBeenCalledTimes(1));
    const payload = createSpy.mock.calls[0][0];
    expect(payload.track_type).toBe("custom");
    expect(payload.reference_track).toEqual([
      { x: 0, y: 0, z: 3 },
      { x: 5, y: 0, z: 3 },
      { x: 5, y: 5, z: null },
    ]);
  });
});

describe("NewJob — failed submission", () => {
  it("preserves user input and surfaces a structured API error", async () => {
    vi.spyOn(apiClient, "createJob").mockRejectedValue(
      new ApiClientError(
        "INVALID_INPUT",
        "Backend rejected the payload.",
        null,
        422,
      ),
    );
    renderPage();

    // Change a field away from defaults so we can assert it is preserved.
    setNumeric(/Altitude/i, "5.5");
    fireEvent.change(screen.getByLabelText(/Optimizer strategy/i), {
      target: { value: "heuristic" },
    });

    fireEvent.click(screen.getByRole("button", { name: /Create job/i }));

    await waitFor(() =>
      expect(screen.getByText(/Backend rejected the payload\./i)).toBeVisible(),
    );
    // User input is NOT reset on failure.
    expect(screen.getByLabelText(/Altitude/i)).toHaveValue(5.5);
    expect(navigateMock).not.toHaveBeenCalled();
  });
});
