import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const billingMock = vi.hoisted(() => ({
  createBillingCheckout: vi.fn(),
  getBillingAvailability: vi.fn(),
}));

vi.mock("../features/settings/cloudModelAccess", async () => {
  const actual = await vi.importActual<
    typeof import("../features/settings/cloudModelAccess")
  >("../features/settings/cloudModelAccess");
  return {
    ...actual,
    createBillingCheckout: billingMock.createBillingCheckout,
    getBillingAvailability: billingMock.getBillingAvailability,
  };
});

import { PricingPage } from "../site/PricingPage";

describe("PricingPage payment channels", () => {
  beforeEach(() => {
    billingMock.createBillingCheckout.mockReset();
    billingMock.getBillingAvailability.mockReset();
    billingMock.getBillingAvailability.mockResolvedValue({
      enabled: true,
      billing_mode: "manual_monthly_renewal",
      methods: { alipay: false, wechat: false, card: true },
      entitlement_activation: "verified_server_callback_only",
      plans: [
        {
          id: "free",
          name: "Free",
          monthly_price_cny_fen: 0,
          included_ai_credits: 300_000,
          capability_set: "core-v1",
        },
        {
          id: "plus",
          name: "Plus",
          monthly_price_cny_fen: 3_900,
          included_ai_credits: 3_000_000,
          capability_set: "core-v1",
        },
        {
          id: "pro",
          name: "Pro",
          monthly_price_cny_fen: 12_900,
          included_ai_credits: 15_000_000,
          capability_set: "core-v1",
        },
      ],
    });
    billingMock.createBillingCheckout.mockImplementation(
      () => new Promise(() => undefined),
    );
  });

  it("shows authoritative launch allowances and routes card checkout", async () => {
    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    expect(await screen.findByText(/3,000,000 managed AI credits/i)).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Choose Plus" }));

    const card = screen.getByRole("button", { name: "Credit or debit card" });
    await waitFor(() => expect(card).toBeEnabled());
    expect(card).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "Continue to payment" }));
    await waitFor(() => {
      expect(billingMock.createBillingCheckout).toHaveBeenCalledWith("plus", "card");
    });
  });
});
