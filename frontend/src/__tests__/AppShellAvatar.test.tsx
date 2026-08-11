import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { RouterProvider, createMemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppShell } from "../AppShell";
import {
  AVATAR_OUTPUT_SIZE,
  avatarCropGeometry,
  clampAvatarCropOffset,
} from "../features/account/avatarCrop";
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

function mockAvatarObjectUrls() {
  const createObjectURL = vi.spyOn(URL, "createObjectURL")
    .mockReturnValueOnce("blob:avatar-source");
  const revokeObjectURL = vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  return { createObjectURL, revokeObjectURL };
}

function chooseTestPhoto(container: HTMLElement) {
  const input = container.querySelector<HTMLInputElement>(
    'input[type="file"][accept="image/jpeg,image/png,image/webp"]',
  );
  if (!input) throw new Error("Avatar file input was not rendered.");
  fireEvent.change(input, {
    target: {
      files: [
        new File(["synthetic-avatar"], "avatar.png", { type: "image/png" }),
      ],
    },
  });
}

function loadCropImage(dialog: HTMLElement) {
  const image = dialog.querySelector<HTMLImageElement>(".avatar-crop-viewport img");
  if (!image) throw new Error("Crop source image was not rendered.");
  Object.defineProperties(image, {
    naturalWidth: { configurable: true, value: 800 },
    naturalHeight: { configurable: true, value: 600 },
  });
  fireEvent.load(image);
  return image;
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

  it("keeps the minimum crop scale covered and clamps drag offsets", () => {
    const geometry = avatarCropGeometry({ width: 800, height: 600 }, 300, 1);
    expect(geometry.scale).toBe(0.5);
    expect(geometry.maxOffsetX).toBe(50);
    expect(geometry.maxOffsetY).toBe(0);
    expect(clampAvatarCropOffset({ x: 200, y: -200 }, geometry)).toEqual({
      x: 50,
      y: -0,
    });
    expect(AVATAR_OUTPUT_SIZE).toBe(512);
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

    expect(screen.getByRole("link", { name: "DroneDream · SIM" }))
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

  it("opens the cropper for a file and cancels without uploading", async () => {
    const { createObjectURL, revokeObjectURL } = mockAvatarObjectUrls();
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    chooseTestPhoto(container);

    const cropDialog = screen.getByRole("dialog", { name: "Crop profile photo" });
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(within(cropDialog).getByRole("group", {
      name: "Profile photo crop area",
    })).toBeVisible();
    expect(within(cropDialog).getByText("Circular preview")).toBeVisible();
    expect(authMock.updateAvatar).not.toHaveBeenCalled();

    fireEvent.click(within(cropDialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Crop profile photo" })).toBeNull();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:avatar-source");
    });
    expect(authMock.updateAvatar).not.toHaveBeenCalled();

    router.dispose();
  });

  it("supports keyboard and pointer crop adjustments, then uploads exactly once", async () => {
    mockAvatarObjectUrls();
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      imageSmoothingEnabled: false,
      imageSmoothingQuality: "low",
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL")
      .mockReturnValue("data:image/jpeg;base64,cropped-avatar");
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    chooseTestPhoto(container);
    const cropDialog = screen.getByRole("dialog", { name: "Crop profile photo" });
    loadCropImage(cropDialog);

    const cropArea = within(cropDialog).getByRole("group", {
      name: "Profile photo crop area",
    });
    const zoom = within(cropDialog).getByRole("slider", { name: "Zoom" });
    fireEvent.change(zoom, { target: { value: "1.6" } });
    expect(zoom).toHaveValue("1.6");
    fireEvent.keyDown(cropArea, { key: "ArrowRight" });
    fireEvent.keyDown(cropArea, { key: "+" });
    fireEvent.pointerDown(cropArea, { pointerId: 4, clientX: 100, clientY: 100 });
    fireEvent.pointerMove(cropArea, { pointerId: 4, clientX: 118, clientY: 112 });
    fireEvent.pointerUp(cropArea, { pointerId: 4, clientX: 118, clientY: 112 });

    fireEvent.click(within(cropDialog).getByRole("button", {
      name: "Save cropped photo",
    }));
    await waitFor(() => {
      expect(authMock.updateAvatar).toHaveBeenCalledTimes(1);
      expect(authMock.updateAvatar).toHaveBeenCalledWith(
        "data:image/jpeg;base64,cropped-avatar",
      );
    });
    expect(drawImage).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog", { name: "Crop profile photo" })).toBeNull();

    router.dispose();
  });

  it("does not let Escape dismiss the cropper while a confirmed upload is pending", async () => {
    mockAvatarObjectUrls();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      drawImage: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL")
      .mockReturnValue("data:image/jpeg;base64,pending-avatar");
    let finishUpload: (() => void) | undefined;
    authMock.updateAvatar.mockImplementationOnce(() => new Promise<undefined>((resolve) => {
      finishUpload = () => resolve(undefined);
    }));
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    chooseTestPhoto(container);
    const cropDialog = screen.getByRole("dialog", { name: "Crop profile photo" });
    loadCropImage(cropDialog);
    fireEvent.click(within(cropDialog).getByRole("button", {
      name: "Save cropped photo",
    }));

    await waitFor(() => expect(authMock.updateAvatar).toHaveBeenCalledTimes(1));
    expect(within(cropDialog).getByRole("button", { name: "Cancel" })).toBeDisabled();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.getByRole("dialog", { name: "Crop profile photo" })).toBeVisible();

    finishUpload?.();
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Crop profile photo" })).toBeNull();
    });
    router.dispose();
  });

  it("sends a camera frame to the cropper, mirrors the preview, and releases media", async () => {
    const stop = vi.fn();
    const stream = { getTracks: () => [{ stop }] } as unknown as MediaStream;
    Object.defineProperty(navigator, "mediaDevices", {
      value: { getUserMedia: vi.fn(async () => stream) },
      configurable: true,
    });
    const { revokeObjectURL } = mockAvatarObjectUrls();
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const translate = vi.fn();
    const scale = vi.fn();
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({
      translate,
      scale,
      drawImage,
    } as unknown as CanvasRenderingContext2D);
    vi.spyOn(HTMLCanvasElement.prototype, "toBlob").mockImplementation(
      (callback) => callback(new Blob(["camera-frame"], { type: "image/jpeg" })),
    );
    window.localStorage.setItem("drone-dream:locale", "en");
    const { router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    const accountDialog = screen.getByRole("dialog", { name: "DroneDream account" });
    fireEvent.click(within(accountDialog).getByRole("button", { name: "Use camera" }));
    const video = await waitFor(() => {
      const next = accountDialog.querySelector("video");
      expect(next).not.toBeNull();
      return next as HTMLVideoElement;
    });
    Object.defineProperties(video, {
      videoWidth: { configurable: true, value: 1280 },
      videoHeight: { configurable: true, value: 720 },
    });
    fireEvent.canPlay(video);
    fireEvent.click(within(accountDialog).getByRole("button", { name: "Take photo" }));

    expect(await screen.findByRole("dialog", { name: "Crop profile photo" })).toBeVisible();
    expect(authMock.updateAvatar).not.toHaveBeenCalled();
    expect(translate).toHaveBeenCalledWith(1280, 0);
    expect(scale).toHaveBeenCalledWith(-1, 1);
    expect(drawImage).toHaveBeenCalledTimes(1);
    expect(stop).toHaveBeenCalledTimes(1);

    fireEvent.keyDown(document, { key: "Escape" });
    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Crop profile photo" })).toBeNull();
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:avatar-source");
    });
    expect(authMock.updateAvatar).not.toHaveBeenCalled();

    router.dispose();
  });

  it("closes and releases an unreadable crop source without uploading", async () => {
    const { revokeObjectURL } = mockAvatarObjectUrls();
    window.localStorage.setItem("drone-dream:locale", "en");
    const { container, router } = renderWorkspace();

    fireEvent.click(screen.getByRole("button", { name: "Account" }));
    chooseTestPhoto(container);
    const cropDialog = screen.getByRole("dialog", { name: "Crop profile photo" });
    const image = cropDialog.querySelector<HTMLImageElement>(".avatar-crop-viewport img");
    if (!image) throw new Error("Crop image was not rendered.");
    fireEvent.error(image);

    await waitFor(() => {
      expect(screen.queryByRole("dialog", { name: "Crop profile photo" })).toBeNull();
      expect(screen.getByRole("alert")).toHaveTextContent(
        "The profile photo could not be cropped.",
      );
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:avatar-source");
    });
    expect(authMock.updateAvatar).not.toHaveBeenCalled();

    router.dispose();
  });
});
