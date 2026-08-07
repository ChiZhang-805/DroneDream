import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const cloudMock = vi.hoisted(() => ({
  submitBusinessUpgradeApplication: vi.fn(),
}));

vi.mock("../features/settings/cloudModelAccess", async () => {
  const actual = await vi.importActual<
    typeof import("../features/settings/cloudModelAccess")
  >("../features/settings/cloudModelAccess");
  return {
    ...actual,
    submitBusinessUpgradeApplication: cloudMock.submitBusinessUpgradeApplication,
  };
});

import { BusinessUpgradePage } from "../site/BusinessUpgradePage";

function submitBusinessForm(buttonName: string) {
  const button = screen.getByRole("button", { name: buttonName });
  const form = button.closest("form");
  if (!form) throw new Error("Missing business upgrade form");
  fireEvent.submit(form);
}

function fillBusinessForm() {
  fireEvent.change(screen.getByLabelText("Company legal name"), {
    target: { value: "Drone Lab LLC" },
  });
  fireEvent.change(screen.getByLabelText("Company email domain"), {
    target: { value: "dronelab.example" },
  });
  fireEvent.change(screen.getByLabelText("Company website"), {
    target: { value: "https://dronelab.example" },
  });
  fireEvent.change(screen.getByLabelText("Country or region"), {
    target: { value: "United States" },
  });
  fireEvent.change(screen.getByLabelText("Your role or title"), {
    target: { value: "Founder" },
  });
  fireEvent.change(screen.getByLabelText("Employee count"), {
    target: { value: "11-50" },
  });
  fireEvent.change(screen.getByLabelText("Registration or tax number"), {
    target: { value: "IL-2026-DRONE" },
  });
  fireEvent.change(screen.getByLabelText("Business plan"), {
    target: { value: "pro" },
  });
  fireEvent.change(screen.getByLabelText("Company proof attachment", { selector: "input" }), {
    target: {
      files: [new File(["proof"], "registration.pdf", { type: "application/pdf" })],
    },
  });
}

describe("BusinessUpgradePage", () => {
  it("requires a signed-in account before submitting a company request", () => {
    const onRequireAccount = vi.fn();
    render(
      <BusinessUpgradePage
        locale="en"
        authenticated={false}
        accountEmail=""
        onRequireAccount={onRequireAccount}
      />,
    );

    fireEvent.change(screen.getByLabelText("Company owner email"), {
      target: { value: "owner@dronelab.example" },
    });
    fillBusinessForm();
    submitBusinessForm("Sign in before applying");

    expect(onRequireAccount).toHaveBeenCalledTimes(1);
    expect(cloudMock.submitBusinessUpgradeApplication).not.toHaveBeenCalled();
  });

  it("submits the bounded company identity questionnaire for admin review", async () => {
    cloudMock.submitBusinessUpgradeApplication.mockResolvedValueOnce({
      id: "application-1",
      status: "pending",
      target_owner_email: "owner@dronelab.example",
      company_legal_name: "Drone Lab LLC",
      requested_plan_id: "pro",
      created_at: "2026-08-07T00:00:00.000Z",
    });
    render(
      <BusinessUpgradePage
        locale="en"
        authenticated
        accountEmail="owner@dronelab.example"
        onRequireAccount={vi.fn()}
      />,
    );

    fillBusinessForm();
    submitBusinessForm("Submit for review");

    await waitFor(() => {
      expect(cloudMock.submitBusinessUpgradeApplication).toHaveBeenCalledWith({
        target_owner_email: "owner@dronelab.example",
        company_legal_name: "Drone Lab LLC",
        company_domain: "dronelab.example",
        company_website: "https://dronelab.example",
        country_region: "United States",
        applicant_role: "Founder",
        employee_count_range: "11-50",
        registration_number: "IL-2026-DRONE",
        requested_plan_id: "pro",
        proof_file_names: ["registration.pdf"],
        note: "",
      });
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Application submitted");
  });
});
