import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function loadAdminExport() {
  const admin = await import("../features/admin/adminConsole");
  const auth = await import("../features/auth/authTokenStore");
  return { admin, auth };
}

function csvResponse(
  body: string,
  headers: Record<string, string> = {},
): Response {
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/csv;charset=utf-8",
      "Content-Disposition": 'attachment; filename="DroneDream-users-2026-08-02.csv"',
      "Cache-Control": "private, no-store",
      "X-Export-Row-Count": "1",
      ...headers,
    },
  });
}

describe("admin user export client", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubEnv(
      "VITE_ADMIN_CONSOLE_URL",
      "https://cloud.example.test/functions/v1/admin-console",
    );
    window.history.replaceState({}, "", "/admin");
  });

  afterEach(async () => {
    const { auth } = await loadAdminExport();
    auth.setAuthAccessToken(null);
    window.history.replaceState({}, "", "/");
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("posts the applied search outside the URL and accepts a non-cacheable CSV attachment", async () => {
    const { admin, auth } = await loadAdminExport();
    auth.setAuthAccessToken("owner-session-token");
    const fetchMock = vi.fn().mockResolvedValue(csvResponse(
      '\ufeff"id","email"\r\n"user-1","pilot@example.test"\r\n',
    ));
    vi.stubGlobal("fetch", fetchMock);

    const exported = await admin.exportAdminUsers("  pilot@example.test  ");

    expect(exported.file_name).toBe("DroneDream-users-2026-08-02.csv");
    expect(exported.row_count).toBe(1);
    expect(await exported.blob.text()).toContain("pilot@example.test");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(
      "https://cloud.example.test/functions/v1/admin-console/users/export",
    );
    expect(url).not.toContain("pilot@example.test");
    expect(init).toEqual(expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer owner-session-token",
        Accept: "text/csv",
        "Content-Type": "application/json",
      }),
      body: JSON.stringify({
        format: "csv",
        search: "pilot@example.test",
      }),
    }));
    expect(JSON.stringify(fetchMock.mock.calls)).not.toMatch(
      /password|api[_ -]?key|raw[_ -]?conversation/iu,
    );
  });

  it("rejects a downloadable response that can be cached", async () => {
    const { admin, auth } = await loadAdminExport();
    auth.setAuthAccessToken("owner-session-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(csvResponse(
      '"id"\r\n"user-1"\r\n',
      { "Cache-Control": "private, max-age=60" },
    )));

    await expect(admin.exportAdminUsers("")).rejects.toMatchObject({
      name: "AdminConsoleError",
      code: "INSECURE_EXPORT_RESPONSE",
      status: 200,
    });
  });

  it("fails closed before consuming an export larger than 20 MiB", async () => {
    const { admin, auth } = await loadAdminExport();
    auth.setAuthAccessToken("owner-session-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(csvResponse(
      '"id"\r\n',
      { "Content-Length": String(20 * 1024 * 1024 + 1) },
    )));

    await expect(admin.exportAdminUsers("")).rejects.toMatchObject({
      name: "AdminConsoleError",
      code: "EXPORT_TOO_LARGE",
      status: 200,
      message: "Response exceeded the 20 MiB safety limit.",
    });
  });

  it("maps a chunked export that crosses the 20 MiB limit to the typed admin error", async () => {
    const { admin, auth } = await loadAdminExport();
    auth.setAuthAccessToken("owner-session-token");
    const firstChunk = new Uint8Array(20 * 1024 * 1024);
    const response = new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(firstChunk);
        controller.enqueue(new Uint8Array([1]));
        controller.close();
      },
    }), {
      status: 200,
      headers: {
        "Content-Type": "text/csv;charset=utf-8",
        "Content-Disposition": 'attachment; filename="DroneDream-users.csv"',
        "Cache-Control": "private, no-store",
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));

    await expect(admin.exportAdminUsers("")).rejects.toMatchObject({
      name: "AdminConsoleError",
      code: "EXPORT_TOO_LARGE",
      status: 200,
      message: "Response exceeded the 20 MiB safety limit.",
    });
  });

  it("ignores an export row-count header outside the safe integer range", async () => {
    const { admin, auth } = await loadAdminExport();
    auth.setAuthAccessToken("owner-session-token");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(csvResponse(
      '"id"\r\n"user-1"\r\n',
      { "X-Export-Row-Count": "9007199254740992" },
    )));

    const exported = await admin.exportAdminUsers("");

    expect(exported.row_count).toBeNull();
  });
});
