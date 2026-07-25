import { fireEvent, render, screen, within } from "@testing-library/react";
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
});

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
    expect(links).toHaveLength(4);
    links.forEach((link) => {
      expect(link.querySelector(".app-nav-entry > svg")).not.toBeNull();
    });

    router.dispose();
  });
});
