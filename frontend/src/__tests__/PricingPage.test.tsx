import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const billingMock = vi.hoisted(() => ({
  createBillingCheckout: vi.fn(),
  getBillingAvailability: vi.fn(),
  getManagedModelUsage: vi.fn(),
}));

vi.mock("../features/settings/cloudModelAccess", async () => {
  const actual = await vi.importActual<
    typeof import("../features/settings/cloudModelAccess")
  >("../features/settings/cloudModelAccess");
  return {
    ...actual,
    createBillingCheckout: billingMock.createBillingCheckout,
    getBillingAvailability: billingMock.getBillingAvailability,
    getManagedModelUsage: billingMock.getManagedModelUsage,
  };
});

import { PricingPage } from "../site/PricingPage";

describe("PricingPage payment channels", () => {
  beforeEach(() => {
    billingMock.createBillingCheckout.mockReset();
    billingMock.getBillingAvailability.mockReset();
    billingMock.getManagedModelUsage.mockReset();
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
    billingMock.getManagedModelUsage.mockResolvedValue({
      plan: {
        id: "free",
        name: "Free",
        monthly_price_cny_fen: 0,
        included_ai_credits: 300_000,
        capability_set: "core-v1",
      },
      period: {
        starts_at: "2026-08-01T00:00:00.000Z",
        ends_at: "2026-09-01T00:00:00.000Z",
      },
      usage: {
        reserved_ai_credits: 0,
        consumed_ai_credits: 0,
        remaining_ai_credits: 300_000,
        request_count: 0,
      },
      recent_requests: [],
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
      expect(billingMock.createBillingCheckout).toHaveBeenCalledWith(
        "plus",
        "card",
        "individual",
      );
    });
  });

  it("presents a strictly progressive feature matrix", async () => {
    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    await screen.findByText(/15,000,000 managed AI credits/i);

    const advancedRows = screen.getAllByText("Advanced AURORA strategy previews");
    const routingRows = screen.getAllByText("Premium managed-model routing");
    const comparisonRows = screen.getAllByText(
      "Expanded multi-experiment comparison workspace",
    );

    expect(advancedRows.map((row) => row.closest("li")?.dataset.available)).toEqual([
      "false",
      "false",
      "true",
    ]);
    expect(routingRows.map((row) => row.closest("li")?.dataset.available)).toEqual([
      "false",
      "false",
      "true",
    ]);
    expect(comparisonRows.map((row) => row.closest("li")?.dataset.available)).toEqual([
      "false",
      "true",
      "true",
    ]);
  });

  it("shows lower per-user monthly prices for business workspaces", async () => {
    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    await screen.findByText(/3,000,000 managed AI credits/i);
    fireEvent.click(screen.getByRole("tab", { name: "Business" }));

    const plus = document.querySelector<HTMLElement>('.pricing-card[data-plan="plus"]');
    const pro = document.querySelector<HTMLElement>('.pricing-card[data-plan="pro"]');
    expect(plus?.textContent).toContain("¥19");
    expect(pro?.textContent).toContain("¥69");
    expect(screen.getAllByText("/ user / month")).toHaveLength(3);
    expect(plus?.textContent).not.toContain("¥39");
    expect(pro?.textContent).not.toContain("¥129");
    expect(screen.getAllByText("Shared DroneDream tuning workspace")).toHaveLength(3);
    expect(screen.getByText("3,000,000 managed AI credits per user each month"))
      .toBeVisible();
  });

  it("quietly keeps the HTTP mirror read-only without probing or creating billing", () => {
    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
        sensitiveCloudActionsEnabled={false}
      />,
    );

    expect(screen.queryByRole("status")).toBeNull();
    expect(document.querySelector(".site-security-notice")).toBeNull();
    expect(screen.getByRole("button", { name: "Choose Plus" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose Plus" })).not.toHaveAttribute(
      "title",
    );
    expect(billingMock.getBillingAvailability).not.toHaveBeenCalled();
    expect(billingMock.getManagedModelUsage).not.toHaveBeenCalled();
    expect(billingMock.createBillingCheckout).not.toHaveBeenCalled();
  });

  it("marks the user's current plan instead of recommending a plan", async () => {
    billingMock.getManagedModelUsage.mockResolvedValueOnce({
      plan: {
        id: "pro",
        name: "Pro",
        monthly_price_cny_fen: 12_900,
        included_ai_credits: 15_000_000,
        capability_set: "core-v1",
      },
      account: {
        billing_scope: "individual",
        organization_id: null,
        organization_name: null,
        organization_role: null,
      },
      period: {
        starts_at: "2026-08-01T00:00:00.000Z",
        ends_at: "2026-09-01T00:00:00.000Z",
      },
      usage: {
        reserved_ai_credits: 0,
        consumed_ai_credits: 0,
        remaining_ai_credits: 15_000_000,
        request_count: 0,
      },
      recent_requests: [],
    });

    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(document.querySelector('.pricing-card[data-plan="pro"]'))
        .toHaveClass("is-current");
    });
    expect(screen.getByText("Current plan")).toBeVisible();
    expect(screen.queryByText("Recommended")).toBeNull();
    expect(document.querySelector('.pricing-card[data-plan="plus"]'))
      .not.toHaveClass("is-current");
  });

  it("marks the current business subscription without marking the individual tab", async () => {
    billingMock.getManagedModelUsage.mockResolvedValueOnce({
      plan: {
        id: "plus",
        name: "Plus",
        monthly_price_cny_fen: 1_900,
        included_ai_credits: 3_000_000,
        capability_set: "core-v1",
      },
      account: {
        billing_scope: "business",
        organization_id: "org-1",
        organization_name: "Drone Lab LLC",
        organization_role: "member",
      },
      period: {
        starts_at: "2026-08-01T00:00:00.000Z",
        ends_at: "2026-09-01T00:00:00.000Z",
      },
      usage: {
        reserved_ai_credits: 0,
        consumed_ai_credits: 0,
        remaining_ai_credits: 3_000_000,
        request_count: 0,
      },
      recent_requests: [],
    });

    render(
      <PricingPage
        locale="en"
        authenticated
        onRequireAccount={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.queryByText("Current plan")).toBeNull();
    });
    expect(document.querySelector('[data-subscription="individual-plus"]'))
      .not.toHaveClass("is-current");

    fireEvent.click(screen.getByRole("tab", { name: "Business" }));

    await waitFor(() => {
      expect(document.querySelector('[data-subscription="business-plus"]'))
        .toHaveClass("is-current");
    });
    expect(screen.getByText("Current plan")).toBeVisible();
    expect(screen.getByRole("button", { name: "Current subscription" }))
      .toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose Pro" })).toBeEnabled();
    expect(billingMock.createBillingCheckout).not.toHaveBeenCalled();
  });

  it("locks the Chinese mobile heading to a natural six-plus-nine character rhythm", () => {
    const { container } = render(
      <PricingPage
        locale="zh-CN"
        authenticated={false}
        onRequireAccount={vi.fn()}
        sensitiveCloudActionsEnabled={false}
      />,
    );

    const lines = Array.from(
      container.querySelectorAll(".pricing-page .portal-title-mobile > span"),
      (line) => line.textContent ?? "",
    );
    expect(lines).toEqual(["为每一次飞行", "选择合适的优化深度"]);
    expect(lines.map((line) => Array.from(line).length)).toEqual([6, 9]);
    expect(lines.join("")).not.toMatch(/[。.!！?？]$/);
  });
});
