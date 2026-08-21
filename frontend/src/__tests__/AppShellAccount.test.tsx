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

    const selector = screen.getByRole("combobox", { name: "Workspace mode" });
    expect(selector).toHaveValue("universal");
    expect(screen.getByRole("option", { name: "DroneDream" })).toBeInTheDocument();
    expect(document.documentElement).toHaveAttribute("data-brand-edition", "universal");
    expect(document.documentElement).toHaveAttribute("data-theme-grants-hardware-authority", "false");

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
    const { container, router } = renderWorkspace();

    const links = container.querySelectorAll(".app-nav a");
    expect(links).toHaveLength(6);
    expect(screen.getByRole("link", { name: "SIM" }))
      .toHaveAttribute("href", "/sim");
    expect(screen.queryByRole("link", { name: "Vehicle Studio" }))
      .not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AGENT" }))
      .toHaveAttribute("href", "/autonomy");
    links.forEach((link) => {
      expect(link.querySelector(".app-nav-entry > svg")).not.toBeNull();
    });

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
    expect(within(panel!).getByRole("link", { name: "SIM" }))
      .toHaveAttribute("href", "/sim");
    expect(within(panel!).getByRole("link", { name: "AGENT" }))
      .toHaveAttribute("href", "/autonomy");

    fireEvent.click(within(panel!).getByRole("button", { name: "Settings" }));
    expect(panel).toHaveAttribute("hidden");
    expect(screen.getByRole("dialog", { name: "Settings" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Close settings" }));
    await waitFor(() => expect(trigger).toHaveFocus());

    fireEvent.click(trigger);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(panel).toHaveAttribute("hidden");
    await waitFor(() => expect(trigger).toHaveFocus());

    router.dispose();
  });
});
