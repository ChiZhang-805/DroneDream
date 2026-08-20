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

function renderWorkspace() {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppShell />,
        children: [
          { path: "assistant", element: <div>Assistant workspace</div> },
        ],
      },
    ],
    { initialEntries: ["/assistant"] },
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

  it("uses a consistent icon and label for every workspace navigation item", () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    const links = container.querySelectorAll(".app-nav a");
    expect(links).toHaveLength(6);
    expect(screen.getByRole("link", { name: "AUTONOMY" }))
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
    expect(within(panel!).getByRole("link", { name: "AUTONOMY" }))
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
