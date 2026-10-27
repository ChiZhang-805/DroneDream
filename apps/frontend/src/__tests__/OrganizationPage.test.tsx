import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const organizationMock = vi.hoisted(() => ({
  getOrganizationAccess: vi.fn(),
  getOrganizationSnapshot: vi.fn(),
  addOrganizationMember: vi.fn(),
  setOrganizationMemberRole: vi.fn(),
  removeOrganizationMember: vi.fn(),
  setOrganizationMemberPlan: vi.fn(),
  setOrganizationPlan: vi.fn(),
  updateOrganizationName: vi.fn(),
  setOrganizationJoinPassword: vi.fn(),
  transferOrganizationFounder: vi.fn(),
  createOrganization: vi.fn(),
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
      public_code: "DD00001",
      description: "Flight research",
      structure_model: "flat" as const,
      join_password_configured: true,
      join_password: "shared-flight-secret",
    },
    actor: {
      user_id: role === "owner"
        ? "11111111-1111-4111-8111-111111111111"
        : "22222222-2222-4222-8222-222222222222",
      role,
      can_manage_members: true,
      can_manage_admins: role === "owner",
      can_transfer_founder: role === "owner",
    },
    admin_limit: 3 as const,
    departments: [],
    join_requests: [],
    members: [
      {
        id: "11111111-1111-4111-8111-111111111111",
        display_name: "Organization Owner",
        email: "owner@example.test",
        avatar_url: "/owner-avatar.png",
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
        avatar_url: null,
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
        avatar_url: null,
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
    window.history.replaceState({}, "", "/organization/");
    Object.values(organizationMock).forEach((mock) => mock.mockReset());
    organizationMock.getOrganizationAccess.mockResolvedValue({ authorized: true, organization_id: "33333333-3333-4333-8333-333333333333", role: "owner" });
    organizationMock.getOrganizationSnapshot.mockResolvedValue(snapshot());
    organizationMock.addOrganizationMember.mockResolvedValue(snapshot());
    organizationMock.setOrganizationMemberRole.mockResolvedValue(snapshot());
    organizationMock.removeOrganizationMember.mockResolvedValue(snapshot());
    organizationMock.setOrganizationMemberPlan.mockResolvedValue(snapshot());
    organizationMock.setOrganizationPlan.mockResolvedValue(snapshot());
    organizationMock.updateOrganizationName.mockResolvedValue(snapshot());
    organizationMock.setOrganizationJoinPassword.mockResolvedValue(snapshot());
    organizationMock.transferOrganizationFounder.mockResolvedValue(snapshot());
    organizationMock.createOrganization.mockResolvedValue(snapshot());
  });

  it("renders a compact member directory and five explicit application marks", async () => {
    const { container } = render(<OrganizationPage locale="en" accountId="user-owner" />);

    expect(await screen.findByRole("heading", { name: "Aerial Systems Lab" })).toBeVisible();
    expect(screen.getByText("1 / 3")).toBeVisible();
    expect(screen.getAllByRole("row")).toHaveLength(4);
    const ownerRow = screen.getByText("owner@example.test").closest("tr");
    expect(ownerRow).not.toBeNull();
    expect(within(ownerRow!).getAllByLabelText(
      /^(Universal|SIM|LAB|FIELD|AGENT) (not )?used$/i,
    )).toHaveLength(5);
    expect(ownerRow?.querySelectorAll(".edition-license-strip .is-active")).toHaveLength(2);
    expect(ownerRow!.querySelector(".organization-avatar img"))
      .toHaveAttribute("src", "/owner-avatar.png");
    expect(container.querySelector(".organization-member-table")).toBeVisible();
  });

  it("uses the authenticated account avatar when the organization snapshot lacks it", async () => {
    const accountId = "22222222-2222-4222-8222-222222222222";
    render(
      <OrganizationPage
        locale="en"
        accountId={accountId}
        accountAvatarUrl="https://accounts.example.test/current-avatar.jpg"
      />,
    );

    const adminRow = (await screen.findByText("admin@example.test")).closest("tr");
    expect(adminRow).not.toBeNull();
    expect(adminRow!.querySelector(".organization-avatar img"))
      .toHaveAttribute("src", "https://accounts.example.test/current-avatar.jpg");
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
    expect(within(dialog).getByRole("button", { name: "Close member details" })).toBeVisible();
    expect(within(dialog).getByText("Applications").closest("div"))
      .toHaveClass("organization-member-applications");
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

  it("creates a Business organization through the two-step architecture wizard", async () => {
    organizationMock.getOrganizationAccess.mockResolvedValueOnce({ authorized: false, organization_id: null, role: null });
    render(<OrganizationPage locale="en" accountId="new-founder" />);
    expect(await screen.findByRole("heading", { name: "How would you like to use Business?" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Create a new organization" }));
    expect(screen.getByRole("button", { name: "Back" })).toBeVisible();
    fireEvent.change(screen.getByLabelText("Organization name"), { target: { value: "Flight Lab" } });
    fireEvent.change(screen.getByLabelText("Organization description"), { target: { value: "Research team" } });
    fireEvent.change(screen.getByLabelText("Organization password"), { target: { value: "secure-flight-2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByText("Departments · two managers"));
    fireEvent.change(screen.getByLabelText("Founder Business plan"), { target: { value: "plus" } });
    fireEvent.click(screen.getByRole("button", { name: "Create organization" }));
    await waitFor(() => expect(organizationMock.createOrganization).toHaveBeenCalledWith({
      name: "Flight Lab", description: "Research team", structure: "department_dual", plan: "plus", password: "secure-flight-2026",
    }));
  });

  it("carries the selected Business tier into both onboarding paths", async () => {
    window.history.replaceState({}, "", "/organization/?plan=plus");
    organizationMock.getOrganizationAccess.mockResolvedValueOnce({ authorized: false, organization_id: null, role: null });
    render(<OrganizationPage locale="en" accountId="new-founder" />);
    await screen.findByRole("heading", { name: "How would you like to use Business?" });

    fireEvent.click(screen.getByRole("button", { name: "Create a new organization" }));
    fireEvent.change(screen.getByLabelText("Organization name"), { target: { value: "Flight Lab" } });
    fireEvent.change(screen.getByLabelText("Organization password"), { target: { value: "secure-flight-2026" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByLabelText("Founder Business plan")).toHaveValue("plus");
  });

  it("opens organization details and applies member delete permissions", async () => {
    render(<OrganizationPage locale="en" accountId="user-owner" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });
    fireEvent.click(screen.getByRole("button", { name: "Organization" }));
    const dialog = screen.getByRole("dialog", { name: "Organization details" });
    expect(within(dialog).getAllByText("DD00001")).toHaveLength(2);
    expect(within(dialog).getByText("shared-flight-secret")).toBeVisible();
    expect(within(dialog).getByLabelText("Organization name")).toHaveValue("Aerial Systems Lab");
    fireEvent.click(within(dialog).getByRole("button", { name: "Close member details" }));

    const ownerRow = screen.getByText("owner@example.test").closest("tr")!;
    const memberRow = screen.getByText("pilot@example.test").closest("tr")!;
    expect(within(ownerRow).getByRole("button", { name: "Delete member: Organization Owner" })).toBeDisabled();
    expect(within(memberRow).getByRole("button", { name: "Delete member: Pilot Member" })).toBeEnabled();
  });

  it("saves organization fields independently", async () => {
    const renamed = snapshot();
    renamed.organization.name = "Renamed Flight Lab";
    let resolveName!: (value: ReturnType<typeof snapshot>) => void;
    organizationMock.updateOrganizationName.mockImplementationOnce(() => new Promise((resolve) => {
      resolveName = resolve;
    }));

    render(<OrganizationPage locale="en" accountId="user-owner" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });
    fireEvent.click(screen.getByRole("button", { name: "Organization" }));
    const dialog = screen.getByRole("dialog", { name: "Organization details" });

    fireEvent.change(within(dialog).getByLabelText("Organization name"), {
      target: { value: "Renamed Flight Lab" },
    });
    fireEvent.change(within(dialog).getByLabelText("Plan"), { target: { value: "plus" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save organization name" }));
    await waitFor(() => expect(organizationMock.updateOrganizationName).toHaveBeenCalledWith("Renamed Flight Lab"));
    expect(within(dialog).getByRole("button", { name: "Save plan" })).toBeEnabled();
    expect(organizationMock.setOrganizationPlan).not.toHaveBeenCalled();
    expect(organizationMock.setOrganizationJoinPassword).not.toHaveBeenCalled();

    resolveName(renamed);
    await waitFor(() => expect(within(dialog).getByRole("button", { name: "Save organization name" })).toBeDisabled());
    fireEvent.click(within(dialog).getByRole("button", { name: "Save plan" }));
    await waitFor(() => expect(organizationMock.setOrganizationPlan).toHaveBeenCalledWith("plus"));
    expect(organizationMock.updateOrganizationName).toHaveBeenCalledTimes(1);
  });

  it("saves member role without submitting the member plan", async () => {
    render(<OrganizationPage locale="en" accountId="user-owner" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });
    const memberRow = screen.getByText("pilot@example.test").closest("tr")!;
    fireEvent.click(within(memberRow).getByRole("button", { name: "View details" }));
    const dialog = screen.getByRole("dialog", { name: "Pilot Member" });
    fireEvent.change(within(dialog).getByLabelText("Role"), { target: { value: "admin" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save role" }));
    await waitFor(() => expect(organizationMock.setOrganizationMemberRole).toHaveBeenCalledWith(
      "44444444-4444-4444-8444-444444444444",
      "admin",
    ));
    expect(organizationMock.setOrganizationMemberPlan).not.toHaveBeenCalled();
  });

  it("lets administrators view organization details without edit controls", async () => {
    organizationMock.getOrganizationSnapshot.mockResolvedValueOnce(snapshot("admin"));
    render(<OrganizationPage locale="en" accountId="user-admin" />);
    await screen.findByRole("heading", { name: "Aerial Systems Lab" });
    fireEvent.click(screen.getByRole("button", { name: "Organization" }));
    const dialog = screen.getByRole("dialog", { name: "Organization details" });
    expect(within(dialog).getByText("shared-flight-secret")).toBeVisible();
    expect(within(dialog).queryByLabelText("Organization name")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Save password" })).not.toBeInTheDocument();
  });
});
