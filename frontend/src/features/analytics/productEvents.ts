import { getAuthAccessToken } from "../auth/authTokenStore";
import { fetchWithDeadline } from "../../api/fetchWithDeadline";
import { isWebConsolePreviewRuntime } from "../demo/publicDemo";

export type ProductEventName =
  | "assistant_turn_succeeded"
  | "assistant_turn_failed"
  | "fixed_scenario_selected"
  | "job_created";

type EventProperty = string | number | boolean | null;
export type ProductEventProperties = Readonly<Record<string, EventProperty>>;

const EVENT_TIMEOUT_MS = 5_000;
const MAX_PROPERTIES = 12;
const MAX_PROPERTY_STRING_LENGTH = 96;
const PROPERTY_KEY = /^[a-z][a-z0-9_]{0,47}$/u;

function deriveProductEventsUrl(): string {
  const explicit = (
    import.meta.env.VITE_PRODUCT_EVENTS_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  if (explicit) return explicit;
  const supabaseUrl = (
    import.meta.env.VITE_SUPABASE_URL as string | undefined
  )?.trim().replace(/\/+$/u, "");
  return supabaseUrl ? `${supabaseUrl}/functions/v1/product-events` : "";
}

export const productEventsUrl = deriveProductEventsUrl();

function boundedProperties(
  properties: ProductEventProperties,
): Record<string, EventProperty> | null {
  const entries = Object.entries(properties);
  if (entries.length > MAX_PROPERTIES) return null;
  const bounded: Record<string, EventProperty> = {};
  for (const [key, value] of entries) {
    if (!PROPERTY_KEY.test(key)) return null;
    if (typeof value === "string" && value.length > MAX_PROPERTY_STRING_LENGTH) {
      return null;
    }
    if (typeof value === "number" && !Number.isFinite(value)) return null;
    bounded[key] = value;
  }
  return bounded;
}

/**
 * Sends a deliberately small, privacy-safe product event. The server derives
 * the account identity from the bearer token. Delivery is best-effort so
 * analytics can never block a user's simulation or conversation workflow.
 */
export async function recordProductEvent(
  name: ProductEventName,
  properties: ProductEventProperties = {},
): Promise<boolean> {
  if (isWebConsolePreviewRuntime()) return false;
  if (import.meta.env.DEV && new URLSearchParams(window.location.search).has("docsPreview")) {
    return false;
  }
  const token = getAuthAccessToken();
  const safeProperties = boundedProperties(properties);
  if (!productEventsUrl || !token || !safeProperties) return false;
  try {
    const response = await fetchWithDeadline(
      productEventsUrl,
      {
        method: "POST",
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          Accept: "application/json",
        },
        body: JSON.stringify({
          schema_version: 1,
          event_id: crypto.randomUUID(),
          name,
          occurred_at: new Date().toISOString(),
          properties: safeProperties,
        }),
        keepalive: true,
      },
      EVENT_TIMEOUT_MS,
    );
    return response.ok;
  } catch {
    return false;
  }
}
