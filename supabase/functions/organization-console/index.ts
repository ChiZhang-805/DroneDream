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
export type OrganizationPlan = "free" | "plus" | "pro";
export type OrganizationStructure = "flat" | "department_single" | "department_dual";
export type EditionId = "universal" | "sim" | "lab" | "field" | "autonomy";

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
  avatar_url: string | null;
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
    public_code: string;
    description: string;
    structure_model: OrganizationStructure;
    join_password_configured: boolean;
    join_password: string | null;
  };
  actor: {
    user_id: string;
    role: OrganizationRole;
    can_manage_members: boolean;
    can_manage_admins: boolean;
    can_transfer_founder: boolean;
  };
  admin_limit: 3;
  members: OrganizationMember[];
  departments: Array<{
    id: string;
    name: string;
    manager_user_ids: string[];
    member_user_ids: string[];
  }>;
  join_requests: Array<{ id: string; user_id: string; email: string; display_name: string; avatar_url: string | null; requested_plan: OrganizationPlan }>;
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
  setMemberPlan(actorUserId: string, targetUserId: string, plan: OrganizationPlan): Promise<void>;
  transferFounder(actorUserId: string, targetUserId: string): Promise<void>;
  setFounderPlan(actorUserId: string, plan: OrganizationPlan): Promise<void>;
  updateOrganization(actorUserId: string, name: string, plan: OrganizationPlan): Promise<void>;
  setJoinPassword(actorUserId: string, password: string): Promise<void>;
  createOrganization(
    founderUserId: string,
    name: string,
    description: string,
    structure: OrganizationStructure,
    plan: OrganizationPlan,
    password: string,
  ): Promise<void>;
  createDepartment(actorUserId: string, name: string): Promise<void>;
  assignDepartment(actorUserId: string, targetUserId: string, departmentId: string): Promise<void>;
  searchOrganizations(query: string): Promise<Array<{ public_code: string; name: string; description: string; plan: OrganizationPlan; structure_model: OrganizationStructure }>>;
  requestJoin(userId: string, publicCode: string, plan: OrganizationPlan, password: string): Promise<void>;
  reviewJoin(actorUserId: string, requestId: string, approved: boolean): Promise<void>;
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
      "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    };
  } catch (error) {
    if (error instanceof SensitiveCorsError) {
      throw new OrganizationConsoleError(
        error.code,
        error.message,
        error.status,
      );
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
  if (
    error instanceof BoundedRequestError ||
    error instanceof OrganizationConsoleError
  ) {
    if (
      error instanceof OrganizationConsoleError &&
      ["ORIGIN_NOT_ALLOWED", "ORIGIN_CONFIGURATION_INVALID"].includes(
        error.code,
      )
    ) {
      return new Response(
        JSON.stringify({
          error: { code: error.code, message: error.message },
        }),
        {
          status: error.status,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "private, no-store",
          },
        },
      );
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

function validPlan(value: unknown): value is OrganizationPlan {
  return value === "free" || value === "plus" || value === "pro";
}

function validStructure(value: unknown): value is OrganizationStructure {
  return value === "flat" || value === "department_single" || value === "department_dual";
}

function displayName(user: User): string {
  const candidate = user.user_metadata.display_name ??
    user.user_metadata.full_name ?? user.user_metadata.name;
  return typeof candidate === "string" && candidate.trim()
    ? candidate.trim().slice(0, 96)
    : user.email?.split("@")[0] || "DroneDream user";
}

function avatarUrl(user: User): string | null {
  const candidate = user.user_metadata.avatar_url ?? user.user_metadata.picture;
  return typeof candidate === "string" &&
    (candidate.startsWith("https://") || candidate.startsWith("data:image/"))
    ? candidate
    : null;
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function base64ToBytes(value: string): Uint8Array {
  const binary = atob(value);
  return Uint8Array.from(binary, (character) => character.charCodeAt(0));
}

async function organizationPasswordKey(): Promise<CryptoKey> {
  const raw = base64ToBytes(requiredEnv("ORGANIZATION_PASSWORD_KEY"));
  if (raw.byteLength !== 32) throw new Error("ORGANIZATION_PASSWORD_KEY must decode to 32 bytes");
  return await crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function encryptOrganizationPassword(password: string): Promise<string> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ciphertext = new Uint8Array(await crypto.subtle.encrypt(
    { name: "AES-GCM", iv }, await organizationPasswordKey(), new TextEncoder().encode(password),
  ));
  return `v1.${bytesToBase64(iv)}.${bytesToBase64(ciphertext)}`;
}

async function decryptOrganizationPassword(value: unknown): Promise<string | null> {
  if (typeof value !== "string") return null;
  const [version, iv, ciphertext] = value.split(".");
  if (version !== "v1" || !iv || !ciphertext) return null;
  try {
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(iv) },
      await organizationPasswordKey(),
      base64ToBytes(ciphertext),
    );
    return new TextDecoder().decode(plaintext);
  } catch {
    return null;
  }
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
    [
      "ORGANIZATION_PERMISSION_REQUIRED",
      "ORGANIZATION_PERMISSION_REQUIRED",
      403,
      "Organization administrator permission is required.",
    ],
    [
      "ORGANIZATION_TARGET_PROTECTED",
      "ORGANIZATION_TARGET_PROTECTED",
      403,
      "This organization member is protected.",
    ],
    [
      "ORGANIZATION_FOUNDER_REQUIRES_ADMIN",
      "ORGANIZATION_FOUNDER_REQUIRES_ADMIN",
      409,
      "Founder can only be transferred to an existing administrator.",
    ],
    [
      "ORGANIZATION_MEMBER_PLAN_EXCEEDS_FOUNDER",
      "ORGANIZATION_MEMBER_PLAN_EXCEEDS_FOUNDER",
      409,
      "The selected plan exceeds the organization plan.",
    ],
    [
      "ORGANIZATION_DEPARTMENT_PERMISSION_REQUIRED",
      "ORGANIZATION_DEPARTMENT_PERMISSION_REQUIRED",
      403,
      "This member is outside the administrator's department.",
    ],
    [
      "ORGANIZATION_DEPARTMENT_MANAGER_LIMIT",
      "ORGANIZATION_DEPARTMENT_MANAGER_LIMIT",
      409,
      "This department already has the maximum number of administrators.",
    ],
    [
      "ORGANIZATION_ADMIN_LIMIT",
      "ORGANIZATION_ADMIN_LIMIT",
      409,
      "An organization can delegate at most three administrators.",
    ],
    [
      "ORGANIZATION_MEMBER_EXISTS",
      "ORGANIZATION_MEMBER_EXISTS",
      409,
      "This account already belongs to an organization.",
    ],
    [
      "ORGANIZATION_USER_NOT_FOUND",
      "ORGANIZATION_USER_NOT_FOUND",
      404,
      "No account matches that email address.",
    ],
    [
      "ORGANIZATION_NOT_FOUND",
      "ORGANIZATION_NOT_FOUND",
      404,
      "No organization matches that code.",
    ],
    [
      "ORGANIZATION_PASSWORD_INCORRECT",
      "ORGANIZATION_PASSWORD_INCORRECT",
      403,
      "The organization password is incorrect.",
    ],
    [
      "ORGANIZATION_JOIN_REQUEST_NOT_FOUND",
      "ORGANIZATION_JOIN_REQUEST_NOT_FOUND",
      404,
      "This join request is no longer pending.",
    ],
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
      .eq("status", "active")
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
      if (
        !actorAccess.authorized || !actorAccess.organization_id ||
        !actorAccess.role
      ) {
        throw new OrganizationConsoleError(
          "ORGANIZATION_PERMISSION_REQUIRED",
          "Organization administrator permission is required.",
          403,
        );
      }
      const [organizationResult, memberResult, departmentResult, assignmentResult, joinRequestResult] = await Promise.all([
        client.from("organizations")
          .select("organization_id,name,plan,status,owner_user_id,public_code,description,structure_model,join_password_hash,join_password_ciphertext")
          .eq("organization_id", actorAccess.organization_id)
          .single(),
        client.from("organization_members")
          .select("user_id,role")
          .eq("organization_id", actorAccess.organization_id)
          .eq("status", "active")
          .order("role")
          .limit(MAX_MEMBERS + 1),
        client.from("organization_departments")
          .select("department_id,name")
          .eq("organization_id", actorAccess.organization_id)
          .order("created_at"),
        client.from("organization_department_assignments")
          .select("department_id,user_id,assignment_role")
          .eq("organization_id", actorAccess.organization_id),
        client.from("organization_join_requests")
          .select("request_id,user_id,requested_plan")
          .eq("organization_id", actorAccess.organization_id)
          .eq("status", "pending")
          .order("created_at"),
      ]);
      if (
        organizationResult.error || memberResult.error || departmentResult.error || assignmentResult.error || joinRequestResult.error ||
        !organizationResult.data
      ) {
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
      const joinUserIds = (joinRequestResult.data ?? []).map((row) => String(row.user_id));
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
        if (
          !["universal", "sim", "lab", "field", "autonomy"].includes(edition)
        ) continue;
        const id = String(row.user_id);
        licensesByUser.set(id, [
          ...(licensesByUser.get(id) ?? []),
          edition as EditionId,
        ]);
      }
      const userById = new Map(users.map((user) => [user.id, user]));
      const joinUsers = await Promise.all(joinUserIds.map(async (joinUserId) => {
        const result = await client.auth.admin.getUserById(joinUserId);
        if (result.error || !result.data.user) throw new OrganizationConsoleError("ORGANIZATION_USER_LOOKUP_FAILED", "An organization join request is unavailable.", 503);
        return result.data.user;
      }));
      const joinUserById = new Map(joinUsers.map((user) => [user.id, user]));
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
          avatar_url: avatarUrl(user),
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
          id: String(organization.organization_id),
          name: String(organization.name),
          plan: organization.plan as OrganizationPlan,
          status: organization.status as "active" | "suspended",
          owner_user_id: String(organization.owner_user_id),
          public_code: String(organization.public_code),
          description: String(organization.description ?? ""),
          structure_model: organization.structure_model as OrganizationStructure,
          join_password_configured: typeof organization.join_password_hash === "string" && organization.join_password_hash.length > 0,
          join_password: await decryptOrganizationPassword(organization.join_password_ciphertext),
        },
        actor: {
          user_id: userId,
          role: actorAccess.role,
          can_manage_members: true,
          can_manage_admins: actorAccess.role === "owner",
          can_transfer_founder: actorAccess.role === "owner",
        },
        admin_limit: 3,
        members,
        departments: (departmentResult.data ?? []).map((department) => {
          const assignments = (assignmentResult.data ?? []).filter((row) => String(row.department_id) === String(department.department_id));
          return {
            id: String(department.department_id),
            name: String(department.name),
            manager_user_ids: assignments.filter((row) => row.assignment_role === "manager").map((row) => String(row.user_id)),
            member_user_ids: assignments.filter((row) => row.assignment_role === "member").map((row) => String(row.user_id)),
          };
        }),
        join_requests: (joinRequestResult.data ?? []).map((row) => {
          const joinUser = joinUserById.get(String(row.user_id));
          return {
            id: String(row.request_id), user_id: String(row.user_id),
            email: joinUser?.email ?? "", display_name: joinUser ? displayName(joinUser) : "DroneDream user",
            avatar_url: joinUser ? avatarUrl(joinUser) : null,
            requested_plan: row.requested_plan as OrganizationPlan,
          };
        }),
      };
    },
    async findUserIdByEmail(email) {
      const { data, error } = await client.rpc(
        "organization_find_user_id_by_email",
        {
          p_email: email,
        },
      );
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
    async setMemberPlan(actorUserId, targetUserId, plan) {
      const { error } = await client.rpc("organization_set_member_plan", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
        p_plan_id: plan,
      });
      if (error) mapRpcError(error);
    },
    async transferFounder(actorUserId, targetUserId) {
      const { error } = await client.rpc("organization_transfer_founder", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
      });
      if (error) mapRpcError(error);
    },
    async setFounderPlan(actorUserId, plan) {
      const { error } = await client.rpc("organization_set_founder_plan", {
        p_actor_user_id: actorUserId,
        p_plan_id: plan,
      });
      if (error) mapRpcError(error);
    },
    async updateOrganization(actorUserId, name, plan) {
      const { error } = await client.rpc("organization_update_profile", {
        p_actor_user_id: actorUserId,
        p_name: name,
        p_plan_id: plan,
      });
      if (error) mapRpcError(error);
    },
    async setJoinPassword(actorUserId, password) {
      const ciphertext = await encryptOrganizationPassword(password);
      const { error } = await client.rpc("organization_set_join_password", {
        p_actor_user_id: actorUserId,
        p_password: password,
        p_password_ciphertext: ciphertext,
      });
      if (error) mapRpcError(error);
    },
    async createOrganization(founderUserId, name, description, structure, plan, password) {
      const ciphertext = await encryptOrganizationPassword(password);
      const { error } = await client.rpc("organization_create_v4", {
        p_founder_user_id: founderUserId,
        p_name: name,
        p_description: description,
        p_structure_model: structure,
        p_founder_plan: plan,
        p_password: password,
        p_password_ciphertext: ciphertext,
      });
      if (error) mapRpcError(error);
    },
    async createDepartment(actorUserId, name) {
      const { error } = await client.rpc("organization_create_department", {
        p_actor_user_id: actorUserId,
        p_name: name,
      });
      if (error) mapRpcError(error);
    },
    async assignDepartment(actorUserId, targetUserId, departmentId) {
      const { error } = await client.rpc("organization_assign_department", {
        p_actor_user_id: actorUserId,
        p_target_user_id: targetUserId,
        p_department_id: departmentId,
      });
      if (error) mapRpcError(error);
    },
    async searchOrganizations(query) {
      const normalized = query.trim();
      let builder = client.from("organizations")
        .select("public_code,name,description,plan,structure_model")
        .eq("status", "active")
        .limit(12);
      builder = /^DD[0-9]{1,5}$/iu.test(normalized)
        ? builder.ilike("public_code", `${normalized}%`)
        : builder.ilike("name", `%${normalized.replace(/[%_]/gu, "")}%`);
      const { data, error } = await builder;
      if (error) throw new OrganizationConsoleError("ORGANIZATION_SEARCH_FAILED", "Organizations could not be searched.", 503);
      return (data ?? []) as Array<{ public_code: string; name: string; description: string; plan: OrganizationPlan; structure_model: OrganizationStructure }>;
    },
    async requestJoin(userId, publicCode, plan, password) {
      const { error } = await client.rpc("organization_request_join", { p_user_id: userId, p_public_code: publicCode, p_plan_id: plan, p_password: password });
      if (error) mapRpcError(error);
    },
    async reviewJoin(actorUserId, requestId, approved) {
      const { error } = await client.rpc("organization_review_join_request", { p_actor_user_id: actorUserId, p_request_id: requestId, p_approved: approved });
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
    const route = index >= 0
      ? pathname.slice(index + marker.length) || "/"
      : pathname;

    if (request.method === "GET" && route === "/access") {
      return jsonResponse(request, 200, { data: await deps.access(actor.id) });
    }
    if (request.method === "GET" && route === "/organizations/search") {
      const query = new URL(request.url).searchParams.get("q")?.trim() ?? "";
      if (query.length < 2 || query.length > 80) throw new OrganizationConsoleError("INVALID_REQUEST", "Enter an organization name or code.", 400);
      return jsonResponse(request, 200, { data: await deps.searchOrganizations(query) });
    }
    if (request.method === "POST" && route === "/join-requests") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["public_code", "plan", "password"]) || typeof body.public_code !== "string" || !/^DD[0-9]{5}$/u.test(body.public_code.toUpperCase()) || !validPlan(body.plan) || typeof body.password !== "string" || body.password.length < 1 || body.password.length > 72) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "A valid organization code, password, and Business plan are required.", 400);
      }
      await deps.requestJoin(actor.id, body.public_code.toUpperCase(), body.plan, body.password);
      return jsonResponse(request, 201, { data: { requested: true } });
    }
    if (request.method === "GET" && route === "/") {
      return jsonResponse(request, 200, {
        data: await deps.snapshot(actor.id),
      });
    }
    if (request.method === "POST" && route === "/organizations") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (
        !exactKeys(body, ["name", "description", "structure", "plan", "password"]) ||
        typeof body.name !== "string" || typeof body.description !== "string" ||
        body.name.trim().length < 1 || body.name.trim().length > 120 ||
        body.description.trim().length > 500 || !validStructure(body.structure) ||
        !validPlan(body.plan) || typeof body.password !== "string" || body.password.length < 8 || body.password.length > 72
      ) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "Valid organization details are required.", 400);
      }
      await deps.createOrganization(actor.id, body.name.trim(), body.description.trim(), body.structure, body.plan, body.password);
      return jsonResponse(request, 201, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "PATCH" && route === "/organization") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["name", "plan"]) || typeof body.name !== "string" || body.name.trim().length < 1 || body.name.trim().length > 120 || !validPlan(body.plan)) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "A valid organization name and Business plan are required.", 400);
      }
      await deps.updateOrganization(actor.id, body.name.trim(), body.plan);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "PUT" && route === "/join-password") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["password"]) || typeof body.password !== "string" || body.password.length < 8 || body.password.length > 72) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "The organization password must contain 8 to 72 characters.", 400);
      }
      await deps.setJoinPassword(actor.id, body.password);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "PATCH" && route === "/plan") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["plan"]) || !validPlan(body.plan)) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "A valid Business plan is required.", 400);
      }
      await deps.setFounderPlan(actor.id, body.plan);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "POST" && route === "/departments") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!exactKeys(body, ["name"]) || typeof body.name !== "string" || body.name.trim().length < 1 || body.name.trim().length > 80) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "A valid department name is required.", 400);
      }
      await deps.createDepartment(actor.id, body.name.trim());
      return jsonResponse(request, 201, { data: await deps.snapshot(actor.id) });
    }
    const joinReviewMatch = /^\/join-requests\/([0-9a-f-]{36})$/iu.exec(route);
    if (joinReviewMatch?.[1] && request.method === "PATCH") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (!validUuid(joinReviewMatch[1]) || !exactKeys(body, ["approved"]) || typeof body.approved !== "boolean") throw new OrganizationConsoleError("INVALID_REQUEST", "A valid join decision is required.", 400);
      await deps.reviewJoin(actor.id, joinReviewMatch[1], body.approved);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    const departmentAssignmentMatch = /^\/departments\/([0-9a-f-]{36})\/members\/([0-9a-f-]{36})$/iu.exec(route);
    if (departmentAssignmentMatch?.[1] && departmentAssignmentMatch?.[2] && request.method === "PUT") {
      if (!validUuid(departmentAssignmentMatch[1]) || !validUuid(departmentAssignmentMatch[2])) {
        throw new OrganizationConsoleError("INVALID_REQUEST", "The department assignment is invalid.", 400);
      }
      await deps.assignDepartment(actor.id, departmentAssignmentMatch[2], departmentAssignmentMatch[1]);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (request.method === "POST" && route === "/members") {
      const body = await readBoundedJsonObject(request, MAX_BODY_BYTES);
      if (
        !exactKeys(body, ["email", "role"]) ||
        typeof body.email !== "string" || !validRole(body.role) ||
        body.email.trim().length < 3 || body.email.trim().length > 320
      ) {
        throw new OrganizationConsoleError(
          "INVALID_REQUEST",
          "A valid member email and role are required.",
          400,
        );
      }
      const targetUserId = await deps.findUserIdByEmail(body.email.trim());
      await deps.addMember(actor.id, targetUserId, body.role);
      return jsonResponse(request, 201, {
        data: await deps.snapshot(actor.id),
      });
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
      if (exactKeys(body, ["plan"]) && validPlan(body.plan)) {
        await deps.setMemberPlan(actor.id, memberMatch[1], body.plan);
        return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
      }
      if (!exactKeys(body, ["role"]) || !validRole(body.role)) {
        throw new OrganizationConsoleError(
          "INVALID_REQUEST",
          "A valid member role is required.",
          400,
        );
      }
      await deps.setMemberRole(actor.id, memberMatch[1], body.role);
      return jsonResponse(request, 200, {
        data: await deps.snapshot(actor.id),
      });
    }
    const transferMatch = /^\/founder\/transfer\/([0-9a-f-]{36})$/iu.exec(route);
    if (transferMatch?.[1] && request.method === "POST") {
      if (!validUuid(transferMatch[1])) {
        throw new OrganizationConsoleError("INVALID_MEMBER_ID", "The member id is invalid.", 400);
      }
      await deps.transferFounder(actor.id, transferMatch[1]);
      return jsonResponse(request, 200, { data: await deps.snapshot(actor.id) });
    }
    if (memberMatch?.[1] && request.method === "DELETE") {
      await deps.removeMember(actor.id, memberMatch[1]);
      return jsonResponse(request, 200, {
        data: await deps.snapshot(actor.id),
      });
    }
    return jsonResponse(request, 404, {
      error: {
        code: "NOT_FOUND",
        message: "The organization route was not found.",
      },
    });
  } catch (error) {
    return errorResponse(request, error);
  }
}

if (import.meta.main) {
  Deno.serve((request) => handleOrganizationConsoleRequest(request));
}
