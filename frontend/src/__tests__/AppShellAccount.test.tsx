import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

vi.mock("../features/auth/supabaseClient", () => ({
  appleAuthEnabled: false,
  cloudAuthConfigured: false,
  googleAuthEnabled: false,
  supabaseClient: null,
}));

function renderWorkspace(initialEntry = "/assistant") {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "assistant", element: <div>Assistant workspace</div> },
          { path: "autonomy", element: <div>Autonomy workspace</div> },
          { path: "vehicle-studio", element: <div>Vehicle Studio workspace</div> },
        ],
      },
    ],
    { initialEntries: [initialEntry] },
  );
  const page = render(
    <I18nProvider>
      <RouterProvider router={router} />
    </I18nProvider>,
  );
  return { ...page, router };
}

afterEach(() => {
  window.localStorage.clear();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

function useMobileViewport(): void {
  vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
    matches: query === "(max-width: 520px)",
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
}

describe("workspace account entry", () => {
  it("identifies the Universal-only modeling surface instead of the last professional workspace", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.localStorage.setItem("dronedream:universal-workspace:v2", "field");
    const { router } = renderWorkspace("/vehicle-studio");

    const selector = screen.getByRole("button", { name: "Switch DroneDream edition" });
    expect(selector).toHaveTextContent("DroneDream");
    fireEvent.click(selector);
    expect(screen.getByRole("menuitemradio", { name: "DroneDream" }))
      .toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: /DroneDream.*FIELD/ }))
      .toHaveAttribute("aria-checked", "false");
    expect(document.documentElement).toHaveAttribute("data-brand-edition", "universal");
    expect(document.documentElement).toHaveAttribute("data-theme-grants-hardware-authority", "false");

    router.dispose();
  });

  it("keeps AUTONOMY vehicle drafts inside the active AUTONOMY workspace", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.localStorage.setItem("dronedream:universal-workspace:v2", "autonomy");
    const { router } = renderWorkspace("/vehicle-studio");

    const selector = screen.getByRole("button", { name: "Switch DroneDream edition" });
    expect(selector).toHaveTextContent("AUTONOMY");
    expect(document.documentElement).toHaveAttribute("data-brand-edition", "autonomy");

    router.dispose();
  });

  it("shows an honest local profile when cloud auth is not configured", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    const accountButton = screen.getByRole("button", { name: "Account" });
    expect(accountButton).toHaveTextContent("Local user");
    expect(accountButton).toHaveTextContent("Local workspace");
    fireEvent.click(accountButton);

    const dialog = screen.getByRole("dialog", { name: "Local workspace" });
    expect(
      within(dialog).getByText(/keeps experiments on this computer/i),
    ).toBeVisible();
    expect(within(dialog).queryByLabelText("Email address")).not.toBeInTheDocument();

    fireEvent.click(within(dialog).getByRole("button", { name: "Close account" }));
    expect(screen.queryByRole("dialog", { name: "Local workspace" }))
      .not.toBeInTheDocument();

    router.dispose();
  });

  it("uses a consistent icon and label for every item in the active SIM workspace", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.localStorage.setItem("dronedream:universal-workspace:v2", "sim");
    const { container, router } = renderWorkspace();

    const links = container.querySelectorAll(".app-nav a");
    expect(links).toHaveLength(6);
    expect(screen.queryByRole("link", { name: "SIM" }))
      .not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Vehicle Studio" }))
      .not.toBeInTheDocument();
    links.forEach((link) => {
      expect(link.querySelector(".app-nav-entry > svg")).not.toBeNull();
    });

    router.dispose();
  });

  it("keeps every edition within its product-specific primary areas", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    window.localStorage.setItem("dronedream:universal-workspace:v2", "universal");
    const { container, router } = renderWorkspace();
    const navigationLabels = () => Array.from(
      container.querySelectorAll<HTMLAnchorElement>(".app-nav a"),
      (link) => link.textContent?.trim(),
    );
    const selectEdition = (name: RegExp) => {
      fireEvent.click(screen.getByRole("button", { name: "Switch DroneDream edition" }));
      fireEvent.click(screen.getByRole("menuitemradio", { name }));
    };

    expect(navigationLabels()).toEqual([
      "Tuning Chat",
      "Autonomy",
      "Vehicle Studio",
      "Dashboard",
      "Run History",
      "Scenarios",
    ]);

    selectEdition(/DroneDream.*SIM/);
    expect(navigationLabels()).toEqual([
      "Tuning Chat",
      "Autonomy",
      "Experiment",
      "Dashboard",
      "Scenarios",
      "Run History",
    ]);

    selectEdition(/DroneDream.*LAB/);
    expect(navigationLabels()).toEqual([
      "Tuning Chat",
      "Autonomy",
      "Experiment",
      "Lab workspace",
      "Hardware Lab",
      "Evidence Review",
      "Run History",
    ]);

    selectEdition(/DroneDream.*FIELD/);
    expect(navigationLabels()).toEqual([
      "Tuning Chat",
      "Autonomy",
      "Device & Vehicle",
      "Tuning Plan",
      "Safety & Recovery",
      "Run History",
    ]);
    expect(screen.queryByRole("link", { name: "ECE498BH" })).not.toBeInTheDocument();

    selectEdition(/DroneDream.*AUTONOMY/);
    expect(navigationLabels()).toEqual([
      "Tuning Chat",
      "Autonomy",
      "Vehicle Studio",
      "Run History",
    ]);
    expect(Array.from(
      container.querySelectorAll<HTMLElement>(".app-nav-section-label"),
      (label) => label.textContent?.trim(),
    )).toEqual(["Autonomous tasks", "Workspace", "Records"]);

    router.dispose();
  });

  it("collapses mobile account, navigation, and settings into one disclosure", async () => {
    useMobileViewport();
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    const trigger = screen.getByRole("button", { name: "Open navigation menu" });
    const panel = document.getElementById("app-mobile-navigation");
    expect(panel).not.toBeNull();
    expect(panel).toHaveAttribute("hidden");
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-label", "Close navigation menu");
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(panel).not.toHaveAttribute("hidden");
    expect(within(panel!).getByRole("button", { name: "Account" }))
      .toHaveTextContent("Local user");
    expect(within(panel!).getAllByRole("link")).toHaveLength(6);
    expect(within(panel!).queryByRole("link", { name: "SIM" }))
      .not.toBeInTheDocument();

    fireEvent.click(within(panel!).getByRole("button", { name: "Settings" }));
    expect(panel).toHaveAttribute("hidden");
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "ECE498BH" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("tab", { name: "ECE498BH" }));
    expect(screen.getByRole("link", { name: "Open course" }))
      .toHaveAttribute(
        "href",
        "https://binhu7.github.io/courses/ECE498/Spring2025/ECE498home.html",
      );
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(panel).toHaveAttribute("hidden");
    await waitFor(() => expect(trigger).toHaveFocus());

    router.dispose();
  });
});
