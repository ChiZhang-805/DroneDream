import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { readEvidenceFile, validateEvidenceTree } from "../evidenceInput";
import { useEvidenceImport } from "../useEvidenceImport";

/** Explicit settlement order makes stale-result tests independent of wall-clock timing. */
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function file(text: () => Promise<string>, size = 2) {
  const value = new File(["{}"], "evidence.json", { type: "application/json" });
  Object.defineProperties(value, { text: { value: text }, size: { value: size } });
  return value;
}

describe("Evidence import ownership", () => {
  it.each(["success", "failure"])("does not apply a stale file %s", async (ending) => {
    const old = deferred<string>();
    const parse = vi.fn((_name: string, source: string) => source);
    const { result } = renderHook(() => useEvidenceImport(100, parse));
    let pending!: Promise<void>;
    act(() => { pending = result.current.importFile(file(() => old.promise)); });
    await act(() => result.current.importFile(file(async () => "new")));
    await act(async () => {
      if (ending === "success") old.resolve("old");
      else old.reject(new Error("old file failed"));
      await pending;
    });
    expect(result.current.value).toBe("new");
    expect(result.current.error).toBeNull();
    expect(parse).toHaveBeenCalledTimes(1);
  });

  it("reset invalidates an in-flight asynchronous digest result", async () => {
    const digest = deferred<string>();
    const { result } = renderHook(() => useEvidenceImport(100, () => digest.promise));
    let pending!: Promise<void>;
    await act(async () => {
      pending = result.current.importFile(file(async () => "{}"));
      await Promise.resolve();
    });
    expect(result.current.loading).toBe(true);
    act(() => result.current.reset());
    await act(async () => { digest.resolve("stale"); await pending; });
    expect(result.current.value).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("unmount prevents delayed file parsing", async () => {
    const read = deferred<string>();
    const parse = vi.fn(() => "parsed");
    const { result, unmount } = renderHook(() => useEvidenceImport(100, parse));
    let pending!: Promise<void>;
    act(() => { pending = result.current.importFile(file(() => read.promise)); });
    unmount();
    read.resolve("{}");
    await pending;
    expect(parse).not.toHaveBeenCalled();
  });

  it("rejects oversize files before reading and checks actual UTF-8 bytes", async () => {
    const text = vi.fn(async () => "{}");
    await expect(readEvidenceFile(file(text, 101), 100)).rejects.toThrow(/size limit/);
    expect(text).not.toHaveBeenCalled();
    await expect(readEvidenceFile(file(async () => "界界"), 4)).rejects.toThrow(/size limit/);
  });

  it("bounds wide graphs as well as deep graphs", () => {
    expect(() => validateEvidenceTree(Array(65537).fill(null), Error)).toThrow(/element count/);
    expect(() => validateEvidenceTree({ value: Infinity }, Error)).toThrow(/finite JSON/);
  });
});
