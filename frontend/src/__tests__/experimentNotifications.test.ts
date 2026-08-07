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
  getExperimentNotificationPreferences,
  experimentNotificationsEnabled,
  requestExperimentNotificationPermission,
  sendExperimentCompletionNotification,
  setExperimentNotificationPreferences,
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
    setExperimentNotificationPreferences({
      enabled: true,
      taskResults: false,
      attentionRequired: true,
      qualificationResults: false,
      environmentIssues: true,
    });
    expect(getExperimentNotificationPreferences()).toEqual({
      enabled: true,
      taskResults: false,
      attentionRequired: true,
      qualificationResults: false,
      environmentIssues: true,
    });
  });

  it("fails closed when the structured preference is corrupt", () => {
    window.localStorage.setItem("dronedream:notify-experiment-complete", "true");
    window.localStorage.setItem("dronedream:notification-preferences-v2", "{not-json");

    expect(getExperimentNotificationPreferences()).toEqual({
      enabled: false,
      taskResults: true,
      attentionRequired: true,
      qualificationResults: true,
      environmentIssues: true,
    });
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
    setExperimentNotificationsEnabled(true);

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
      title: "DroneDream · SIM 需要处理",
      body: "扰动边界实验：调优任务失败，请检查失败原因。",
    });

    expect(await sendExperimentCompletionNotification({
      id: "running-job-id",
      display_name: "Still running",
      status: "RUNNING",
    }, "en")).toBe(false);
    expect(sendNotification).toHaveBeenCalledTimes(2);
  });

  it("routes qualified candidates through the qualification preference", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    isPermissionGranted.mockResolvedValue(true);
    setExperimentNotificationPreferences({
      enabled: true,
      taskResults: false,
      attentionRequired: false,
      qualificationResults: true,
      environmentIssues: false,
    });

    expect(await sendExperimentCompletionNotification({
      id: "qualified-job-id",
      display_name: "Robust holdout",
      status: "COMPLETED",
      first_qualified_candidate_id: "candidate-1",
    }, "en")).toBe(true);
    expect(sendNotification).toHaveBeenLastCalledWith({
      title: "DroneDream · SIM qualification",
      body: "Robust holdout produced a qualified candidate.",
    });
  });

  it("does not leak failed tasks into the general result preference", async () => {
    window.__TAURI__ = { core: { invoke: vi.fn() } };
    isPermissionGranted.mockResolvedValue(true);
    setExperimentNotificationPreferences({
      enabled: true,
      taskResults: true,
      attentionRequired: false,
      qualificationResults: false,
      environmentIssues: false,
    });

    expect(await sendExperimentCompletionNotification({
      id: "failed-job-id",
      display_name: "Failed task",
      status: "FAILED",
    }, "en")).toBe(false);
    expect(sendNotification).not.toHaveBeenCalled();
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
