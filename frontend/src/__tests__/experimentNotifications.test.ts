import { afterEach, describe, expect, it, vi } from "vitest";

const isPermissionGranted = vi.fn();
const requestPermission = vi.fn();
const sendNotification = vi.fn();

vi.mock("@tauri-apps/plugin-notification", () => ({
  isPermissionGranted,
  requestPermission,
  sendNotification,
}));

import {
  experimentNotificationsEnabled,
  requestExperimentNotificationPermission,
  sendExperimentCompletionNotification,
  setExperimentNotificationsEnabled,
} from "../desktop/experimentNotifications";

afterEach(() => {
  window.localStorage.clear();
  delete window.__TAURI__;
  vi.clearAllMocks();
});

describe("experiment completion notifications", () => {
  it("persists the real user preference", () => {
    expect(experimentNotificationsEnabled()).toBe(false);
    setExperimentNotificationsEnabled(true);
    expect(experimentNotificationsEnabled()).toBe(true);
    setExperimentNotificationsEnabled(false);
    expect(experimentNotificationsEnabled()).toBe(false);
  });

  it("requests permission only inside the desktop app", async () => {
    requestPermission.mockResolvedValue("granted");
    expect(await requestExperimentNotificationPermission()).toBe(false);
    expect(requestPermission).not.toHaveBeenCalled();

    window.__TAURI__ = { core: { invoke: vi.fn() } };
    isPermissionGranted.mockResolvedValue(false);
    expect(await requestExperimentNotificationPermission()).toBe(true);
    expect(requestPermission).toHaveBeenCalledTimes(1);
  });

  it("sends localized notifications only for terminal jobs with permission", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    isPermissionGranted.mockResolvedValue(true);

    expect(await sendExperimentCompletionNotification({
      id: "completed-job-id",
      display_name: "Holdout A",
      status: "COMPLETED",
    }, "en")).toBe(true);
    expect(sendNotification).toHaveBeenLastCalledWith({
      title: "DroneDream · SIM tuning task",
      body: "Holdout A completed",
    });

    expect(await sendExperimentCompletionNotification({
      id: "failed-job-id",
      display_name: "扰动边界实验",
      status: "FAILED",
    }, "zh-CN")).toBe(true);
    expect(sendNotification).toHaveBeenLastCalledWith({
      title: "DroneDream · SIM 调优任务",
      body: "扰动边界实验：失败",
    });

    expect(await sendExperimentCompletionNotification({
      id: "running-job-id",
      display_name: "Still running",
      status: "RUNNING",
    }, "en")).toBe(false);
    expect(sendNotification).toHaveBeenCalledTimes(2);
  });

  it("fails closed when notification permission is unavailable", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    isPermissionGranted.mockResolvedValue(false);

    expect(await sendExperimentCompletionNotification({
      id: "cancelled-job-id",
      display_name: "Cancelled",
      status: "CANCELLED",
    }, "en")).toBe(false);
    expect(sendNotification).not.toHaveBeenCalled();
  });
});
