import { describe, expect, it } from "vitest";

import {
  hostedConsoleRecoveryHref,
  restoredHostedConsolePath,
} from "../hostedConsoleRouting";

describe("hosted console route recovery", () => {
  it.each([
    ["/console/jobs/job-42", "?tab=trials", "", "/console/?route=%2Fjobs%2Fjob-42%3Ftab%3Dtrials"],
    ["/console/trials/trial-7", "", "#evidence", "/console/?route=%2Ftrials%2Ftrial-7%23evidence"],
    ["/console/autonomy/conversations/conversation-9", "", "", "/console/?route=%2Fautonomy%2Fconversations%2Fconversation-9"],
  ])("recovers a dynamic console page through the deployed 404 entry", (
    pathname,
    search,
    hash,
    expected,
  ) => {
    expect(hostedConsoleRecoveryHref(pathname, search, hash)).toBe(expected);
  });

  it("restores the original route before the console router is created", () => {
    expect(restoredHostedConsolePath(
      "/console/",
      "?route=%2Fjobs%2Fjob-42%3Ftab%3Dtrials%23summary",
    )).toBe("/console/jobs/job-42?tab=trials#summary");
  });

  it.each([
    ["/", "?route=%2Fjobs%2Fjob-42"],
    ["/console/", ""],
    ["/console/", "?route=https%3A%2F%2Fexample.com"],
    ["/console/", "?route=%2F%2Fevil.example"],
  ])("ignores non-console and non-relative recovery requests", (pathname, search) => {
    expect(restoredHostedConsolePath(pathname, search)).toBeNull();
  });
});
