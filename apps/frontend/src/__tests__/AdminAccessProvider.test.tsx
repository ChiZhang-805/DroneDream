import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminAccessProvider } from "../features/admin/AdminAccessProvider";
import { useAdminAccess } from "../features/admin/AdminAccessContext";

const mocks = vi.hoisted(() => ({
  auth: {
    account: {
      id: "owner-1",
      email: "owner@example.test",
      displayName: "Owner",
      avatarUrl: null,
    } as {
      id: string;
      email: string | null;
      displayName: string;
      avatarUrl: string | null;
    } | null,
    configured: true,
  },
  getOrganizationAccess: vi.fn(),
}));

vi.mock("../desktop/bridge", () => ({
  isDesktopRuntime: () => false,
}));

vi.mock("../features/auth/AuthContext", () => ({
  useAuth: () => mocks.auth,
}));

vi.mock("../features/organization/organizationConsole", () => ({
  getOrganizationAccess: mocks.getOrganizationAccess,
}));

function Probe() {
  const admin = useAdminAccess();
  return (
    <output aria-label="admin-status">
      {admin.status}:{admin.access?.role ?? "none"}
    </output>
  );
}

describe("AdminAccessProvider request isolation", () => {
  afterEach(() => {
    mocks.auth.account = {
      id: "owner-1",
      email: "owner@example.test",
      displayName: "Owner",
      avatarUrl: null,
    };
    mocks.auth.configured = true;
    mocks.getOrganizationAccess.mockReset();
  });

  it("ignores an allowed response that arrives after the account signs out", async () => {
    let resolveAccess: ((value: {
      authorized: boolean;
      role: "owner";
      organization_id: string;
    }) => void) | undefined;
    mocks.getOrganizationAccess.mockReturnValueOnce(new Promise((resolve) => {
      resolveAccess = resolve;
    }));

    const view = render(
      <AdminAccessProvider>
        <Probe />
      </AdminAccessProvider>,
    );
    expect(await screen.findByLabelText("admin-status")).toHaveTextContent("loading");

    mocks.auth.account = null;
    view.rerender(
      <AdminAccessProvider>
        <Probe />
      </AdminAccessProvider>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("admin-status")).toHaveTextContent("disabled");
    });

    resolveAccess?.({
      authorized: true,
      role: "owner",
      organization_id: "organization-1",
    });
    await Promise.resolve();
    await Promise.resolve();

    expect(screen.getByLabelText("admin-status")).toHaveTextContent("disabled");
  });

  it("keeps confirmed access stable when auth refreshes the same account object", async () => {
    mocks.getOrganizationAccess.mockResolvedValue({
      authorized: true,
      role: "owner",
      organization_id: "organization-1",
    });

    const view = render(
      <AdminAccessProvider>
        <Probe />
      </AdminAccessProvider>,
    );
    await waitFor(() => {
      expect(screen.getByLabelText("admin-status")).toHaveTextContent("allowed:owner");
    });
    expect(mocks.getOrganizationAccess).toHaveBeenCalledTimes(1);

    mocks.auth.account = {
      id: "owner-1",
      email: "owner@example.test",
      displayName: "Owner after token refresh",
      avatarUrl: null,
    };
    view.rerender(
      <AdminAccessProvider>
        <Probe />
      </AdminAccessProvider>,
    );

    expect(screen.getByLabelText("admin-status")).toHaveTextContent("allowed:owner");
    expect(mocks.getOrganizationAccess).toHaveBeenCalledTimes(1);
  });
});
