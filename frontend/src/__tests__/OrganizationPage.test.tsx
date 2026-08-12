import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const organizationMock = vi.hoisted(() => ({
  getOrganizationSnapshot: vi.fn(),
  addOrganizationMember: vi.fn(),
  setOrganizationMemberRole: vi.fn(),
  removeOrganizationMember: vi.fn(),
}));

vi.mock("../features/organization/organizationConsole", async () => {
  const actual = await vi.importActual<
    typeof import("../features/organization/organizationConsole")
  >("../features/organization/organizationConsole");
  return { ...actual, ...organizationMock };
});

import { OrganizationPage } from "../site/OrganizationPage";

function snapshot(role: "owner" | "admin" = "owner") {
  return {
    organization: {
      id: "33333333-3333-4333-8333-333333333333",
      name: "Aerial Systems Lab",
      plan: "pro" as const,
      status: "active" as const,
      owner_user_id: "11111111-1111-4111-8111-111111111111",
    },
    actor: {
      user_id: role === "owner"
        ? "11111111-1111-4111-8111-111111111111"
        : "22222222-2222-4222-8222-222222222222",
      role,
      can_manage_members: true,
      can_manage_admins: role === "owner",
    },
    admin_limit: 3 as const,
    members: [
      {
        id: "11111111-1111-4111-8111-111111111111",
        display_name: "Organization Owner",
        email: "owner@example.test",
        role: "owner" as const,
        plan: "pro" as const,
        subscription_status: "active",
        created_at: "2026-08-01T00:00:00.000Z",
        last_sign_in_at: "2026-08-12T00:00:00.000Z",
        licenses: ["universal", "lab"] as const,
      },
      {
        id: "22222222-2222-4222-8222-222222222222",
        display_name: "Flight Admin",
        email: "admin@example.test",
        role: "admin" as const,
        plan: "pro" as const,
        subscription_status: "active",
        created_at: "2026-08-02T00:00:00.000Z",
        last_sign_in_at: null,
        licenses: ["sim", "field"] as const,
      },
      {
        id: "44444444-4444-4444-8444-444444444444",
        display_name: "Pilot Member",
        email: "pilot@example.test",
        role: "member" as const,
        plan: "pro" as const,
        subscription_status: "active",
        created_at: "2026-08-03T00:00:00.000Z",
        last_sign_in_at: null,
        licenses: [] as const,
      },
    ],
  };
}

describe("OrganizationPage", () => {
  beforeEach(() => {
    Object.values(organizationMock).forEach((mock) => mock.mockReset());
    organizationMock.getOrganizationSnapshot.mockResolvedValue(snapshot());
    organizationMock.addOrganizationMember.mockResolvedValue(snapshot());
    organizationMock.setOrganizationMemberRole.mockResolvedValue(snapshot());
    organizationMock.removeOrganizationMember.mockResolvedValue(snapshot());
  });

  it("renders a compact member directory and four explicit application marks", async () => {
    const { container } = render(<OrganizationPage locale="en" accountId="user-owner" />);

    expect(await screen.findByRole("heading", { name: "Aerial Systems Lab" })).toBeVisible();
    expect(screen.getByText("1 / 3")).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(4);
    const ownerRow = screen.getByText("owner@example.test").closest("tr");
    expect(ownerRow).not.toBeNull();
    expect(within(ownerRow!).getAllByLabelText(
      /^(Universal|SIM|LAB|FIELD) (not )?licensed$/i,
    )).toHaveLength(4);
    expect(ownerRow?.querySelectorAll(".edition-license-strip .is-active")).toHaveLength(2);
    expect(container.querySelector(".organization-member-table")).toBeVisible();
  });

  it("adds an existing account with an owner-selected delegated role", async () => {
    render(<OrganizationPage locale="en" accountId="user-owner" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });

    fireEvent.change(screen.getByLabelText("Account email"), {
      target: { value: "new-admin@example.test" },
    });
    fireEvent.change(screen.getByLabelText("Role"), { target: { value: "admin" } });
    fireEvent.click(screen.getByRole("button", { name: "Add member" }));

    await waitFor(() => {
      expect(organizationMock.addOrganizationMember).toHaveBeenCalledWith(
        "new-admin@example.test",
        "admin",
      );
    });
  });

  it("keeps detailed data and destructive actions inside the member card", async () => {
    render(<OrganizationPage locale="en" accountId="user-owner" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });

    const pilotRow = screen.getByText("pilot@example.test").closest("tr");
    fireEvent.click(within(pilotRow!).getByRole("button", { name: "View details" }));
    const dialog = screen.getByRole("dialog", { name: "Pilot Member" });
    expect(within(dialog).queryByText("Individual · Free")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove from organization" }));
    expect(within(dialog).getByText("Individual · Free")).toBeVisible();
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm removal" }));

    await waitFor(() => {
      expect(organizationMock.removeOrganizationMember).toHaveBeenCalledWith(
        "44444444-4444-4444-8444-444444444444",
      );
    });
  });

  it("does not let a delegated admin control another delegated admin", async () => {
    organizationMock.getOrganizationSnapshot.mockResolvedValueOnce(snapshot("admin"));
    render(<OrganizationPage locale="en" accountId="user-admin" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });

    const adminRow = screen.getByText("admin@example.test").closest("tr");
    fireEvent.click(within(adminRow!).getByRole("button", { name: "View details" }));
    const dialog = screen.getByRole("dialog", { name: "Flight Admin" });
    expect(within(dialog).queryByRole("button", { name: "Remove from organization" }))
      .not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Save role" }))
      .not.toBeInTheDocument();
  });
});
