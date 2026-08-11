import {
  createClient,
  type SupabaseClient,
  type User,
} from "npm:@supabase/supabase-js@2.110.8";

import {
  BoundedRequestError,
  readBoundedJsonObject,
} from "../_shared/bounded_request.ts";
import {
  sensitiveAllowedOrigins,
  SensitiveCorsError,
  sensitiveCorsHeaders,
} from "../_shared/sensitive_cors.ts";

type JsonRecord = Record<string, unknown>;
export type OrganizationRole = "owner" | "admin" | "member";
export type OrganizationPlan = "plus" | "pro";
export type EditionId = "universal" | "sim" | "lab" | "field";

const DEFAULT_ALLOWED_ORIGINS = [
  "https://getdronedream.com",
  "https://www.getdronedream.com",
  "http://localhost:5173",
  "http://127.0.0.1:5173",
  "http://tauri.localhost",
  "tauri://localhost",
];
const MAX_BODY_BYTES = 8 * 1024;
const MAX_MEMBERS = 500;

export interface OrganizationAccess {
  authorized: boolean;
  organization_id: string | null;
  role: OrganizationRole | null;
}

export interface OrganizationMember {
  id: string;
  display_name: string;
  email: string;
  role: OrganizationRole;
  plan: "free" | OrganizationPlan;
  subscription_status: string;
  created_at: string;
  last_sign_in_at: string | null;
  licenses: EditionId[];
}

export interface OrganizationSnapshot {
  organization: {
    id: string;
    name: string;
    plan: OrganizationPlan;
    status: "active" | "suspended";
    owner_user_id: string;
  };
  actor: {
    user_id: string;
    role: OrganizationRole;
    can_manage_members: boolean;
    can_manage_admins: boolean;
  };
  admin_limit: 3;
  members: OrganizationMember[];
}

export interface OrganizationConsoleDependencies {
  authenticate(token: string): Promise<{ id: string }>;
  access(userId: string): Promise<OrganizationAccess>;
  snapshot(userId: string): Promise<OrganizationSnapshot>;
  findUserIdByEmail(email: string): Promise<string>;
  addMember(
    actorUserId: string,
    targetUserId: string,
    role: Exclude<OrganizationRole, "owner">,
  ): Promise<void>;
  setMemberRole(
    actorUserId: string,
    targetUserId: string,
    role: Exclude<OrganizationRole, "owner">,
  ): Promise<void>;
  removeMember(actorUserId: string, targetUserId: string): Promise<void>;
}

export class OrganizationConsoleError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "OrganizationConsoleError";
    this.code = code;
    this.status = status;
  }
}

function requiredEnv(name: string): string {
  const value = Deno.env.get(name)?.trim();
  if (!value) {
    throw new OrganizationConsoleError(
      "SERVICE_NOT_CONFIGURED",
      "Organization management is not configured.",
      503,
    );
  }
  return value;
}

function allowedOrigins(): Set<string> {
  return sensitiveAllowedOrigins(
    Deno.env.get("ORGANIZATION_CONSOLE_ALLOWED_ORIGINS"),
    DEFAULT_ALLOWED_ORIGINS,
  );
}

function corsHeaders(request: Request): HeadersInit {
  if (!request.headers.get("Origin")) return {};
  try {
    return {
      ...sensitiveCorsHeaders(request, allowedOrigins()),
      "Access-Control-Allow-Headers":
        "authorization, apikey, content-type, x-client-info",
      "Access-Control-Allow-Methods": "GET, POST, PATCH, DELETE, OPTIONS",
    };
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new OrganizationConsoleError(error.code, error.message, error.status);
    }
    throw error;
  }
}

function jsonResponse(
  request: Request,
  status: number,
  body: JsonRecord,
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "private, no-store",
      "X-Content-Type-Options": "nosniff",
      ...corsHeaders(request),
    },
  });
}

function errorResponse(request: Request, error: unknown): Response {
  if (error instanceof BoundedRequestError || error instanceof OrganizationConsoleError) {
    if (
      error instanceof OrganizationConsoleError &&
      ["ORIGIN_NOT_ALLOWED", "ORIGIN_CONFIGURATION_INVALID"].includes(error.code)
    ) {
      return new Response(JSON.stringify({
        error: { code: error.code, message: error.message },
      }), {
        status: error.status,
        headers: {
          "Content-Type": "application/json; charset=utf-8",
          "Cache-Control": "private, no-store",
        },
      });
    }
    return jsonResponse(request, error.status, {
      error: { code: error.code, message: error.message },
    });
  }
  console.error("organization-console unexpected failure", "INTERNAL_ERROR");
  return jsonResponse(request, 500, {
    error: {
      code: "INTERNAL_ERROR",
      message: "The organization request could not be completed.",
    },
  });
}

function bearerToken(request: Request): string {
  const match = /^Bearer\s+(.+)$/iu.exec(
    request.headers.get("Authorization")?.trim() ?? "",
  );
  if (!match?.[1]) {
    throw new OrganizationConsoleError(
      "AUTHENTICATION_REQUIRED",
      "A valid account session is required.",
      401,
    );
  }
  return match[1].trim();
}

function exactKeys(value: JsonRecord, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index]);
}

function validUuid(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu
    .test(value);
}

function validRole(value: unknown): value is "admin" | "member" {
  return value === "admin" || value === "member";
}

function displayName(user: User): string {
  const candidate = user.user_metadata.display_name ??
    user.user_metadata.full_name ?? user.user_metadata.name;
  return typeof candidate === "string" && candidate.trim()
    ? candidate.trim().slice(0, 96)
    : user.email?.split("@")[0] || "DroneDream user";
}

let cachedClient: SupabaseClient | null = null;

function adminClient(): SupabaseClient {
  if (cachedClient) return cachedClient;
  cachedClient = createClient(
    requiredEnv("SUPABASE_URL"),
    requiredEnv("SUPABASE_SERVICE_ROLE_KEY"),
    { auth: { autoRefreshToken: false, persistSession: false } },
  );
  return cachedClient;
}

function mapRpcError(error: { message?: string } | null): never {
  const message = error?.message ?? "";
  const mappings: Array<[string, string, number, string]> = [
    ["ORGANIZATION_PERMISSION_REQUIRED", "ORGANIZATION_PERMISSION_REQUIRED", 403, "Organization administrator permission is required."],
    ["ORGANIZATION_TARGET_PROTECTED", "ORGANIZATION_TARGET_PROTECTED", 403, "This organization member is protected."],
    ["ORGANIZATION_ADMIN_LIMIT", "ORGANIZATION_ADMIN_LIMIT", 409, "An organization can delegate at most three administrators."],
    ["ORGANIZATION_MEMBER_EXISTS", "ORGANIZATION_MEMBER_EXISTS", 409, "This account already belongs to an organization."],
    ["ORGANIZATION_USER_NOT_FOUND", "ORGANIZATION_USER_NOT_FOUND", 404, "No account matches that email address."],
  ];
  for (const [needle, code, status, safeMessage] of mappings) {
    if (message.includes(needle)) {
      throw new OrganizationConsoleError(code, safeMessage, status);
    }
  }
  throw new OrganizationConsoleError(
    "ORGANIZATION_MUTATION_FAILED",
    "The organization change could not be completed.",
    503,
  );
}

function actualDependencies(): OrganizationConsoleDependencies {
  const client = adminClient();
  const access = async (userId: string): Promise<OrganizationAccess> => {
    const { data, error } = await client.from("organization_members")
      .select("organization_id,role")
      .eq("user_id", userId)
      .maybeSingle();
    if (error) {
      throw new OrganizationConsoleError(
        "ORGANIZATION_ACCESS_FAILED",
        "Organization access could not be verified.",
        503,
      );
    }
    const role = data?.role;
    return {
      authorized: role === "owner" || role === "admin",
      organization_id: typeof data?.organization_id === "string"
        ? data.organization_id
        : null,
      role: role === "owner" || role === "admin" || role === "member"
        ? role
        : null,
    };
  };

  return {
    async authenticate(token) {
      const { data, error } = await client.auth.getUser(token);
      if (error || !data.user) {
        throw new OrganizationConsoleError(
          "AUTHENTICATION_REQUIRED",
          "The account session is invalid.",
          401,
        );
      }
      return { id: data.user.id };
    },
    access,
    async snapshot(userId) {
      const actorAccess = await access(userId);
      if (!actorAccess.authorized || !actorAccess.organization_id || !actorAccess.role) {
        throw new OrganizationConsoleError(
          "ORGANIZATION_PERMISSION_REQUIRED",
          "Organization administrator permission is required.",
          403,
        );
      }
      const [organizationResult, memberResult] = await Promise.all([
        client.from("organizations")
          .select("id,name,plan_id,status,owner_user_id")
          .eq("id", actorAccess.organization_id)
          .single(),
        client.from("organization_members")
          .select("user_id,role")
          .eq("organization_id", actorAccess.organization_id)
          .order("role")
          .limit(MAX_MEMBERS + 1),
      ]);
      if (organizationResult.error || memberResult.error || !organizationResult.data) {
        throw new OrganizationConsoleError(
          "ORGANIZATION_SNAPSHOT_FAILED",
          "Organization data is unavailable.",
          503,
        );
      }
      const rawMembers = memberResult.data ?? [];
      if (rawMembers.length > MAX_MEMBERS) {
        throw new OrganizationConsoleError(
          "ORGANIZATION_MEMBER_LIMIT",
          "The organization member list exceeds the supported limit.",
          409,
        );
      }
      const userIds = rawMembers.map((row) => String(row.user_id));
      const [entitlements, licenses, users] = await Promise.all([
        userIds.length
          ? client.from("account_entitlements")
            .select("user_id,plan_id,status")
            .in("user_id", userIds)
          : Promise.resolve({ data: [], error: null }),
        userIds.length
          ? client.from("user_software_licenses")
            .select("user_id,edition,status")
            .in("user_id", userIds)
            .eq("status", "active")
          : Promise.resolve({ data: [], error: null }),
        Promise.all(userIds.map(async (memberUserId) => {
          const result = await client.auth.admin.getUserById(memberUserId);
          if (result.error || !result.data.user) {
            throw new OrganizationConsoleError(
              "ORGANIZATION_USER_LOOKUP_FAILED",
              "An organization member record is unavailable.",
              503,
            );
          }
          return result.data.user;
        })),
      ]);
      if (entitlements.error || licenses.error) {
        throw new OrganizationConsoleError(
          "ORGANIZATION_PORTFOLIO_FAILED",
          "Organization subscription data is unavailable.",
          503,
        );
      }
      const entitlementByUser = new Map(
        (entitlements.data ?? []).map((row) => [String(row.user_id), row]),
      );
      const licensesByUser = new Map<string, EditionId[]>();
      for (const row of licenses.data ?? []) {
        const edition = String(row.edition);
        if (!["universal", "sim", "lab", "field"].includes(edition)) continue;
        const id = String(row.user_id);
        licensesByUser.set(id, [
          ...(licensesByUser.get(id) ?? []),
          edition as EditionId,
        ]);
      }
      const userById = new Map(users.map((user) => [user.id, user]));
      const members: OrganizationMember[] = rawMembers.map((row) => {
        const id = String(row.user_id);
        const user = userById.get(id);
        if (!user?.email) {
          throw new OrganizationConsoleError(
            "ORGANIZATION_USER_LOOKUP_FAILED",
            "An organization member record is unavailable.",
            503,
          );
        }
        const entitlement = entitlementByUser.get(id);
        const plan = entitlement?.plan_id;
        return {
          id,
          display_name: displayName(user),
          email: user.email,
          role: row.role as OrganizationRole,
          plan: plan === "plus" || plan === "pro" ? plan : "free",
          subscription_status: String(entitlement?.status ?? "active"),
          created_at: user.created_at,
          last_sign_in_at: user.last_sign_in_at ?? null,
          licenses: licensesByUser.get(id) ?? [],
        };
      });
      const organization = organizationResult.data;
      return {
        organization: {
          id: String(organization.id),
          name: String(organization.name),
          plan: organization.plan_id as OrganizationPlan,
          status: organization.status as "active" | "suspended",
          owner_user_id: String(organization.owner_user_id),
        },
        actor: {
          user_id: userId,
          role: actorAccess.role,
          can_manage_members: true,
          can_manage_admins: actorAccess.role === "owner",
        },
        admin_limit: 3,
        members,
      };
    },
    async findUserIdByEmail(email) {
      const { data, error } = await client.rpc("organization_find_user_id_by_email", {
        p_email: email,
      });
      if (error || typeof data !== "string") mapRpcError(error);
      return data as string;
    },
    async addMember(actorUserId, targetUserId, role) {
      const { error } = await client.rpc("organization_add_member", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
        p_role: role,
      });
      if (error) mapRpcError(error);
    },
    async setMemberRole(actorUserId, targetUserId, role) {
      const { error } = await client.rpc("organization_set_member_role", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
        p_role: role,
      });
      if (error) mapRpcError(error);
    },
    async removeMember(actorUserId, targetUserId) {
      const { error } = await client.rpc("organization_remove_member", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
      });
      if (error) mapRpcError(error);
    },
  };
}

export async function handleOrganizationConsoleRequest(
  request: Request,
  dependencies?: OrganizationConsoleDependencies,
): Promise<Response> {
  try {
    const cors = corsHeaders(request);
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: cors });
    }
    const deps = dependencies ?? actualDependencies();
    const actor = await deps.authenticate(bearerToken(request));
    const pathname = new URL(request.url).pathname.replace(/\/+$/u, "");
    const marker = "/organization-console";
    const index = pathname.lastIndexOf(marker);
    const route = index >= 0 ? pathname.slice(index + marker.length) || "/" : pathname;

    if (request.method === "GET" && route === "/access") {
      return jsonResponse(request, 200, { data: await deps.access(actor.id) });
    }
    if (request.method === "GET" && route === "/") {
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "POST" && route === "/members") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["email", "role"]) ||
        typeof body.email !== "string" || !validRole(body.role) ||
        body.email.trim().length < 3 || body.email.trim().length > 320) {
        throw new OrganizationConsoleError(
          "INVALID_REQUEST",
          "A valid member email and role are required.",
          400,
        );
      }
      const targetUserId = await deps.findUserIdByEmail(body.email.trim());
      await deps.addMember(actor.id, targetUserId, body.role);
      return jsonResponse(request, 201, { data: await deps.snapshot(actor.id) });
    }
    const memberMatch = /^\/members\/([0-9a-f-]{36})$/iu.exec(route);
    if (memberMatch?.[1] && !validUuid(memberMatch[1])) {
      throw new OrganizationConsoleError(
        "INVALID_MEMBER_ID",
        "The member id is invalid.",
        400,
      );
    }
    if (memberMatch?.[1] && request.method === "PATCH") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["role"]) || !validRole(body.role)) {
        throw new OrganizationConsoleError(
          "INVALID_REQUEST",
          "A valid member role is required.",
          400,
        );
      }
      await deps.setMemberRole(actor.id, memberMatch[1], body.role);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (memberMatch?.[1] && request.method === "DELETE") {
      await deps.removeMember(actor.id, memberMatch[1]);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    return jsonResponse(request, 404, {
      error: { code: "NOT_FOUND", message: "The organization route was not found." },
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve((request) => handleOrganizationConsoleRequest(request));
}
