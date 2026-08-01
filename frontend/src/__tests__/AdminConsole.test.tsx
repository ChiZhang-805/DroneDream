import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminAccessContext,
  type AdminAccessContextValue,
} from "../features/admin/AdminAccessContext";
import { AdminAccessProvider } from "../features/admin/AdminAccessProvider";
import { exportAdminUsers } from "../features/admin/adminConsole";
import { AuthProvider } from "../features/auth/AuthContext";
import { I18nProvider } from "../i18n/I18nProvider";
import { AdminPage } from "../pages/AdminPage";

const allowed: AdminAccessContextValue = {
  status: "allowed",
  access: {
    authorized: true,
    role: "owner",
    permissions: [
      "metrics.read",
      "users.read",
      "users.export",
      "models.write",
      "community.moderate",
      "audit.read",
    ],
  },
  error: null,
  refresh: vi.fn(async () => undefined),
};

function renderAdmin(value: AdminAccessContextValue = allowed) {
  return render(
    <I18nProvider>
      <AdminAccessContext.Provider value={value}>
        <AdminPage />
      </AdminAccessContext.Provider>
    </I18nProvider>,
  );
}

describe("administration console", () => {
  const createObjectUrl = vi.fn<(blob: Blob) => string>(
    () => "blob:admin-user-export",
  );
  const revokeObjectUrl = vi.fn();

  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem("drone-dream:locale", "en");
    window.history.replaceState({}, "", "/admin?adminPreview=1&docsPreview=1");
    Object.defineProperty(URL, "createObjectURL", {
      configurable: true,
      value: createObjectUrl,
    });
    Object.defineProperty(URL, "revokeObjectURL", {
      configurable: true,
      value: revokeObjectUrl,
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
  });

  afterEach(() => {
    window.history.replaceState({}, "", "/");
    vi.restoreAllMocks();
    createObjectUrl.mockClear();
    revokeObjectUrl.mockClear();
  });

  it("derives the admin entry from a server access decision", async () => {
    function Probe() {
      return (
        <AdminAccessContext.Consumer>
          {(value) => <output>{value?.status}</output>}
        </AdminAccessContext.Consumer>
      );
    }

    render(
      <AuthProvider>
        <AdminAccessProvider>
          <Probe />
        </AdminAccessProvider>
      </AuthProvider>,
    );

    expect(await screen.findByText("allowed")).toBeVisible();
  });

  it("does not render administrative data after access is denied", () => {
    renderAdmin({
      status: "denied",
      access: null,
      error: null,
      refresh: vi.fn(async () => undefined),
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Administration access denied",
    );
    expect(screen.queryByText("Total users")).not.toBeInTheDocument();
  });

  it("shows growth definitions, model controls, user usage, and audited moderation", async () => {
    renderAdmin();

    expect(await screen.findByText("Total users")).toBeVisible();
    expect(screen.getByText("Activation funnel")).toBeVisible();
    expect(screen.getByText("Weekly retention cohorts")).toBeVisible();
    expect(screen.getByText("Acquisition quality")).toBeVisible();
    expect(screen.getByText("Time to first value · Median")).toBeVisible();
    expect(screen.getByText("Metric definitions")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Model availability" }));
    expect(await screen.findByText("GPT")).toBeVisible();
    expect(screen.getByText("DeepSeek")).toBeVisible();
    expect(screen.getByText("Qwen")).toBeVisible();
    expect(screen.queryByLabelText(/API key/i)).not.toBeInTheDocument();

    const gptCard = screen.getByText("GPT").closest("article");
    const gptSwitches = gptCard?.querySelectorAll<HTMLInputElement>(
      'input[type="checkbox"]',
    );
    expect(gptSwitches).toHaveLength(3);
    fireEvent.click(gptSwitches?.[1] as HTMLInputElement);
    await waitFor(() => expect(gptSwitches?.[1]).not.toBeChecked());

    fireEvent.click(screen.getByRole("button", { name: "Users & usage" }));
    expect(await screen.findByText("pilot.one@example.test")).toBeVisible();
    expect(screen.getByText(/Passwords and password hashes are never returned/))
      .toBeVisible();
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(screen.getByText(/Passwords, API keys, auth tokens, and raw conversations are excluded/))
      .toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Export user data" }));
    await waitFor(() => expect(createObjectUrl).toHaveBeenCalledTimes(1));
    expect(createObjectUrl.mock.calls[0]?.[0]).toBeInstanceOf(Blob);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "DroneDream-users-preview.csv (3)",
    );

    fireEvent.click(screen.getByRole("button", { name: "Community & audit" }));
    expect(await screen.findByText("Stable hover before entering a circle track"))
      .toBeVisible();
    const removeButtons = screen.getAllByRole("button", { name: "Remove" });
    fireEvent.click(removeButtons[0]);
    const confirm = screen.getByRole("button", { name: "Confirm removal" });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Moderation reason"), {
      target: { value: "Confirmed policy violation" },
    });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByText("Recent administrative audit")).toBeVisible();
  });

  it("exports only the bounded non-secret user fields in preview mode", async () => {
    const exported = await exportAdminUsers("pilot.one");
    const csv = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onerror = () => reject(reader.error);
      reader.onload = () => resolve(String(reader.result));
      reader.readAsText(exported.blob);
    });

    expect(exported.row_count).toBe(1);
    expect(csv).toContain('"email"');
    expect(csv).toContain('"pilot.one@example.test"');
    expect(csv).not.toMatch(/password|api[_ -]?key|access[_ -]?token|raw[_ -]?conversation/iu);
  });
});
