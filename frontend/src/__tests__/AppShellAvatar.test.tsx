import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import { I18nProvider } from "../i18n/I18nProvider";

const authMock = vi.hoisted(() => ({
  updateAvatar: vi.fn(async () => undefined),
  updateDisplayName: vi.fn(async () => undefined),
  signOut: vi.fn(async () => undefined),
}));

vi.mock("../features/auth/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({
    configured: true,
    loading: false,
    account: {
      id: "user-1",
      email: "pilot@example.com",
      displayName: "pilot",
      avatarUrl: null,
    },
    googleEnabled: false,
    appleEnabled: false,
    signInWithPassword: vi.fn(),
    sendRegistrationCode: vi.fn(),
    verifyRegistrationCode: vi.fn(),
    signInWithProvider: vi.fn(),
    updateDisplayName: authMock.updateDisplayName,
    updateAvatar: authMock.updateAvatar,
    signOut: authMock.signOut,
  }),
}));

function renderWorkspace() {
  const router = createMemoryRouter(
    [
      {
        path: "/",
        element: <AppShell />,
        children: [{ path: "assistant", element: <div>Assistant workspace</div> }],
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

describe("workspace profile photo editor", () => {
  afterEach(() => {
    authMock.updateAvatar.mockClear();
    authMock.updateDisplayName.mockClear();
    authMock.signOut.mockClear();
    vi.restoreAllMocks();
    window.localStorage.clear();
    Object.defineProperty(navigator, "mediaDevices", {
      value: undefined,
      configurable: true,
    });
    Object.defineProperty(window, "isSecureContext", {
      value: true,
      configurable: true,
    });
  });

  it("offers a local image picker and requests the camera only after a click", async () => {
    const stop = vi.fn();
    const getUserMedia = vi.fn(async () => ({
      getTracks: () => [{ stop }],
    }));
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia },
      configurable: true,
    });
    Object.defineProperty(window, "isSecureContext", {
      value: true,
      configurable: true,
    });
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    expect(screen.getByRole("link", { name: "DroneDream" }))
      .toHaveAttribute("href", "/");
    expect(getUserMedia).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const dialog = screen.getByRole("dialog", { name: "DroneDream account" });

    expect(within(dialog).getByText("Profile photo")).toBeVisible();
    expect(
      container.querySelector('input[type="file"][accept="image/jpeg,image/png,image/webp"]'),
    ).not.toBeNull();
    expect(getUserMedia).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Use camera" }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    expect(await within(dialog).findByRole("button", { name: "Take photo" }))
      .toBeDisabled();

    fireEvent.click(
      within(dialog).getByRole("button", { name: "Close account" }),
    );
    await waitFor(() => expect(stop).toHaveBeenCalledTimes(1));

    router.dispose();
  });

  it("uses icon-only username save and keeps sign out in the profile row", async () => {
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const dialog = screen.getByRole("dialog", { name: "DroneDream account" });
    const save = within(dialog).getByRole("button", { name: "Save username" });
    const signOut = within(dialog).getByRole("button", { name: "Sign out" });

    expect(save).toBeDisabled();
    expect(save).toHaveTextContent("");
    expect(save.querySelector("svg")).not.toBeNull();
    expect(signOut.closest(".account-profile")).not.toBeNull();

    fireEvent.change(within(dialog).getByLabelText("Username"), {
      target: { value: "pilot-two" },
    });
    fireEvent.click(save);
    await waitFor(() => {
      expect(authMock.updateDisplayName).toHaveBeenCalledWith("pilot-two");
    });

    router.dispose();
  });

  it("explains that an insecure HTTP origin cannot request the camera", async () => {
    const getUserMedia = vi.fn();
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia },
      configurable: true,
    });
    Object.defineProperty(window, "isSecureContext", {
      value: false,
      configurable: true,
    });
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const dialog = screen.getByRole("dialog", { name: "DroneDream account" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Use camera" }));

    expect(getUserMedia).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "Camera access requires HTTPS.",
    );

    router.dispose();
  });
});
