import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { Provider, User } from "@supabase/supabase-js";

import {
  clearBrowserAuthVault,
  isDesktopRuntime,
} from "../../desktop/bridge";
import { clearAllExperimentDrafts } from "../experiment/draftStorage";
import {
  ACTIVATE_DESKTOP_AUTH_EVENT,
  ADOPT_DESKTOP_AUTH_EVENT,
  DESKTOP_AUTH_REFRESH_FAILED_EVENT,
} from "./desktopAuthActivation";
import { clearBrowserAuthSessionRefresh } from "./browserAuth";
import { getAuthAccessToken, setAuthAccessToken } from "./authTokenStore";
import {
  appleAuthEnabled,
  browserAuthConfiguration,
  cloudAuthConfigured,
  googleAuthEnabled,
  supabaseClient,
} from "./supabaseClient";

export interface DroneDreamAccount {
  id: string;
  email: string | null;
  displayName: string;
  avatarUrl: string | null;
}

interface AuthContextValue {
  configured: boolean;
  loading: boolean;
  passwordRecovery: boolean;
  account: DroneDreamAccount | null;
  googleEnabled: boolean;
  appleEnabled: boolean;
  signInWithPassword: (
    email: string,
    password: string,
    captchaToken?: string,
  ) => Promise<void>;
  sendRegistrationCode: (
    email: string,
    captchaToken?: string,
  ) => Promise<void>;
  verifyRegistrationCode: (
    email: string,
    token: string,
    password: string,
  ) => Promise<void>;
  sendRecoveryCode: (
    email: string,
    captchaToken?: string,
  ) => Promise<void>;
  verifyRecoveryCode: (
    email: string,
    token: string,
    newPassword?: string,
  ) => Promise<void>;
  requestPasswordReset: (
    email: string,
    captchaToken?: string,
  ) => Promise<void>;
  updatePassword: (password: string) => Promise<void>;
  signInWithProvider: (provider: "google" | "apple") => Promise<void>;
  updateDisplayName: (displayName: string) => Promise<void>;
  updateAvatar: (avatarDataUrl: string | null) => Promise<void>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);
const unavailableAuthAction = async () => {
  throw new Error("Cloud account access is not configured for this build.");
};
const OPTIONAL_AUTH_FALLBACK: AuthContextValue = {
  configured: false,
  loading: false,
  passwordRecovery: false,
  account: null,
  googleEnabled: false,
  appleEnabled: false,
  signInWithPassword: unavailableAuthAction,
  sendRegistrationCode: unavailableAuthAction,
  verifyRegistrationCode: unavailableAuthAction,
  sendRecoveryCode: unavailableAuthAction,
  verifyRecoveryCode: unavailableAuthAction,
  requestPasswordReset: unavailableAuthAction,
  updatePassword: unavailableAuthAction,
  signInWithProvider: unavailableAuthAction,
  updateDisplayName: unavailableAuthAction,
  updateAvatar: unavailableAuthAction,
  signOut: unavailableAuthAction,
};
const AVATAR_STORAGE_PREFIX = "drone-dream:account-avatar:";
const MAX_AVATAR_DATA_URL_LENGTH = 600_000;
const PROFILE_AVATAR_BUCKET = "profile-avatars";
const PROFILE_AVATAR_FILE = "avatar.jpg";

function shouldDeferDesktopAuth(): boolean {
  // Tauri uses a hash router and initially mounts the provider at `/` before
  // the index redirect selects `#/desktop/setup`.  Looking only at pathname
  // therefore lets account hydration race the environment-only launcher.
  // Desktop auth is always a deliberate second stage and is activated by the
  // single sign-in action after local readiness reaches 100%.
  return isDesktopRuntime();
}

function avatarStorageKey(userId: string): string {
  // Scope optional local presentation data to the authenticated account.
  return `${AVATAR_STORAGE_PREFIX}${userId}`;
}

function avatarObjectPath(userId: string): string {
  // Cloud object ownership is enforced separately by storage policies.
  return `${userId}/${PROFILE_AVATAR_FILE}`;
}

function avatarPublicUrl(supabaseUrl: string, userId: string): string {
  // Derive the project URL; never let a cached URL redirect an authenticated write.
  const url = new URL(
    `/storage/v1/object/public/${PROFILE_AVATAR_BUCKET}/${encodeURIComponent(userId)}/${PROFILE_AVATAR_FILE}`,
    supabaseUrl,
  );
  url.searchParams.set("v", Date.now().toString());
  return url.toString();
}

function avatarJpegBlob(avatarDataUrl: string): Blob {
  // The photo editor produces JPEG; reject other encodings instead of mislabelling them.
  const prefix = "data:image/jpeg;base64,";
  if (!avatarDataUrl.startsWith(prefix)) {
    throw new Error("The selected profile photo must be a JPEG image.");
  }
  let decoded: string;
  try {
    decoded = window.atob(avatarDataUrl.slice(prefix.length));
  } catch {
    throw new Error("The selected profile photo could not be decoded.");
  }
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) {
    bytes[index] = decoded.charCodeAt(index);
  }
  return new Blob([bytes], { type: "image/jpeg" });
}

function cacheAvatarForUser(userId: string, avatarUrl: string | null): void {
  // Cache only after cloud success; localStorage is optional, not the source of truth.
  try {
    if (avatarUrl) {
      window.localStorage.setItem(avatarStorageKey(userId), avatarUrl);
    } else {
      window.localStorage.removeItem(avatarStorageKey(userId));
    }
  } catch {
    // The server copy and authenticated user metadata are authoritative. A
    // hardened WebView may disable localStorage without blocking the upload.
  }
}

function localAvatarForUser(userId: string): string | null {
  // Read an account-scoped presentation fallback without granting authentication.
  if (typeof window === "undefined") return null;
  try {
    const stored = window.localStorage.getItem(avatarStorageKey(userId));
    return stored?.startsWith("data:image/") || stored?.startsWith("https://")
      ? stored
      : null;
  } catch {
    // Storage can be disabled by a hardened browser or WebView policy. A local
    // avatar is optional and must never prevent the authenticated session from
    // being adopted.
    return null;
  }
}

function metadataAvatar(user: User): string | null {
  // Limit display schemes while preserving provider-supplied profile pictures.
  const candidate = user.user_metadata.avatar_url ?? user.user_metadata.picture;
  return typeof candidate === "string" &&
    (candidate.startsWith("https://") || candidate.startsWith("data:image/"))
    ? candidate
    : null;
}

function resolvedAvatarForUser(user: User): string | null {
  // Prefer current cloud metadata over a possibly stale WebView cache.
  const metadata = metadataAvatar(user);
  const cached = localAvatarForUser(user.id);
  const configuration = browserAuthConfiguration();

  // The public object is the durable source shared by every DroneDream
  // edition. Rebuild its URL from the current Supabase project instead of
  // allowing an old per-WebView cache entry to shadow the uploaded avatar.
  if (
    configuration &&
    [metadata, cached].some((candidate) =>
      candidate?.includes(`/storage/v1/object/public/${PROFILE_AVATAR_BUCKET}/`),
    )
  ) {
    const canonical = avatarPublicUrl(configuration.supabaseUrl, user.id);
    cacheAvatarForUser(user.id, canonical);
    return canonical;
  }

  if (metadata) {
    cacheAvatarForUser(user.id, metadata);
    return metadata;
  }
  return cached;
}

function accountFromUser(user: User | null): DroneDreamAccount | null {
  // Project verified identity to UI fields; this does not infer subscription tier.
  if (!user) return null;
  const rawName =
    user.user_metadata.display_name ??
    user.user_metadata.full_name ??
    user.user_metadata.name ??
    null;
  const displayName =
    typeof rawName === "string" && rawName.trim()
      ? rawName.trim()
      : user.email?.split("@")[0] || "DroneDream user";
  return {
    id: user.id,
    email: user.email ?? null,
    displayName,
    avatarUrl: resolvedAvatarForUser(user),
  };
}

function requireClient() {
  // Missing build configuration is an error, not an offline authenticated account.
  if (!supabaseClient) {
    throw new Error("Cloud account access is not configured for this build.");
  }
  return supabaseClient;
}

function providerRedirectUrl(): string {
  // Retain origin but remove old query/fragment secrets from the OAuth destination.
  const redirect = new URL(window.location.href);
  redirect.pathname = redirect.pathname === "/console"
    || redirect.pathname.startsWith("/console/")
    ? "/console/assistant"
    : "/assistant";
  redirect.search = "";
  redirect.hash = "";
  return redirect.toString();
}

export function AuthProvider({ children }: { children: ReactNode }) {
  // Own account transitions centrally so caches, drafts and async profile writes
  // cannot silently migrate from one account to the next.
  const desktopVisualQa = isDesktopRuntime()
    && import.meta.env.VITE_DESKTOP_VISUAL_QA === "true";
  const docsPreview = desktopVisualQa || (import.meta.env.DEV &&
    new URLSearchParams(window.location.search).has("docsPreview"));
  const deferDesktopAuth = useRef(shouldDeferDesktopAuth()).current;
  const [authActivated, setAuthActivated] = useState(!deferDesktopAuth);
  const [loading, setLoading] = useState(
    cloudAuthConfigured && !docsPreview && !deferDesktopAuth,
  );
  const [passwordRecovery, setPasswordRecovery] = useState(false);
  const [account, setAccount] = useState<DroneDreamAccount | null>(
    docsPreview
      ? {
          id: desktopVisualQa ? "desktop-visual-qa" : "docs-preview",
          email: "pilot@example.com",
          displayName: "DroneDream Pilot",
          avatarUrl: null,
        }
      : null,
  );
  const previousAccountId = useRef<string | null>(account?.id ?? null);
  const accountGeneration = useRef(0);

  useEffect(() => () => { accountGeneration.current += 1; }, []);

  const assertProfileOwner = useCallback((ownerId: string, generation: number) => {
    if (previousAccountId.current !== ownerId || accountGeneration.current !== generation) {
      throw new Error("The account changed while the profile was being saved. Try again.");
    }
  }, []);

  const adoptUser = useCallback((user: User | null, accessToken: string | null) => {
    const next = accountFromUser(user);
    const previousId = previousAccountId.current;
    if (previousId !== (next?.id ?? null)) accountGeneration.current += 1;
    if (previousId && previousId !== next?.id) {
      clearAllExperimentDrafts();
    }
    previousAccountId.current = next?.id ?? null;
    setAuthAccessToken(accessToken);
    setAccount(next);
  }, []);

  useEffect(() => {
    if (!deferDesktopAuth) return undefined;
    const adopt = (event: Event) => {
      const detail = (event as CustomEvent<{ user: User; accessToken: string }>).detail;
      if (!detail?.user || !detail.accessToken) return;
      adoptUser(detail.user, detail.accessToken);
      setLoading(false);
    };
    window.addEventListener(ADOPT_DESKTOP_AUTH_EVENT, adopt);
    return () => window.removeEventListener(ADOPT_DESKTOP_AUTH_EVENT, adopt);
  }, [adoptUser, deferDesktopAuth]);

  useEffect(() => {
    const expire = () => {
      adoptUser(null, null);
      setLoading(false);
    };
    window.addEventListener(DESKTOP_AUTH_REFRESH_FAILED_EVENT, expire);
    return () => window.removeEventListener(DESKTOP_AUTH_REFRESH_FAILED_EVENT, expire);
  }, [adoptUser]);

  useEffect(() => {
    if (!deferDesktopAuth || authActivated) return undefined;
    const activate = () => {
      // The caller owns the visible restore/browser/adoption transaction.
      // Toggling the provider-wide loading state here would unmount a required
      // account dialog and orphan its cancellation controller mid-flight.
      setLoading(false);
      setAuthActivated(true);
    };
    window.addEventListener(ACTIVATE_DESKTOP_AUTH_EVENT, activate, { once: true });
    return () => window.removeEventListener(ACTIVATE_DESKTOP_AUTH_EVENT, activate);
  }, [authActivated, deferDesktopAuth, docsPreview]);

  useEffect(() => {
    if (docsPreview || !authActivated) return undefined;
    if (deferDesktopAuth) {
      setLoading(false);
      return undefined;
    }
    if (!supabaseClient) {
      setLoading(false);
      return undefined;
    }
    let active = true;
    let authEventReceived = false;
    void supabaseClient.auth.getSession().then(({ data, error }) => {
      // An auth event is newer than the startup snapshot, even if its request
      // completes first. A late snapshot must not resurrect a signed-out account.
      if (!active || authEventReceived) return;
      if (error) {
        adoptUser(null, null);
      } else {
        adoptUser(data.session?.user ?? null, data.session?.access_token ?? null);
      }
      setLoading(false);
    }).catch(() => {
      if (!active || authEventReceived) return;
      adoptUser(null, null);
      setLoading(false);
    });
    const { data } = supabaseClient.auth.onAuthStateChange((event, session) => {
      if (!active) return;
      authEventReceived = true;
      if (event === "PASSWORD_RECOVERY") {
        setPasswordRecovery(true);
      } else if (event === "SIGNED_OUT") {
        setPasswordRecovery(false);
      }
      adoptUser(session?.user ?? null, session?.access_token ?? null);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [adoptUser, authActivated, deferDesktopAuth, docsPreview]);

  const signInWithPassword = useCallback(async (
    email: string,
    password: string,
    captchaToken?: string,
  ) => {
    // Send credentials only through the configured SDK; auth events adopt the result.
    const { error } = await requireClient().auth.signInWithPassword({
      email: email.trim(),
      password,
      ...(captchaToken ? { options: { captchaToken } } : {}),
    });
    if (error) throw error;
  }, []);

  const sendRegistrationCode = useCallback(async (
    email: string,
    captchaToken?: string,
  ) => {
    // Registration may create an identity; recovery below deliberately may not.
    const { error } = await requireClient().auth.signInWithOtp({
      email: email.trim(),
      options: {
        shouldCreateUser: true,
        ...(captchaToken ? { captchaToken } : {}),
      },
    });
    if (error) throw error;
  }, []);

  const verifyRegistrationCode = useCallback(async (
    email: string,
    token: string,
    password: string,
  ) => {
    // Verification must succeed before setting a password; roll back local login
    // if the second step fails so a partial registration is not presented as done.
    const client = requireClient();
    const { error } = await client.auth.verifyOtp({
      email: email.trim(),
      token: token.trim(),
      type: "email",
    });
    if (error) throw error;
    try {
      const { error: passwordError } = await client.auth.updateUser({ password });
      if (passwordError) throw passwordError;
    } catch (passwordError) {
      const { error: rollbackError } = await client.auth.signOut({ scope: "local" });
      if (rollbackError) throw rollbackError;
      throw passwordError;
    }
  }, []);

  const sendRecoveryCode = useCallback(async (
    email: string,
    captchaToken?: string,
  ) => {
    // Never create a new account as a side effect of recovering an existing one.
    const { error } = await requireClient().auth.signInWithOtp({
      email: email.trim(),
      options: {
        shouldCreateUser: false,
        ...(captchaToken ? { captchaToken } : {}),
      },
    });
    if (error) throw error;
  }, []);

  const verifyRecoveryCode = useCallback(async (
    email: string,
    token: string,
    newPassword?: string,
  ) => {
    // A code-only login and a requested password reset share verification, not intent.
    const client = requireClient();
    const { error } = await client.auth.verifyOtp({
      email: email.trim(),
      token: token.trim(),
      type: "email",
    });
    if (error) throw error;
    if (newPassword === undefined) return;
    try {
      const { error: passwordError } = await client.auth.updateUser({
        password: newPassword,
      });
      if (passwordError) throw passwordError;
    } catch (passwordError) {
      const { error: rollbackError } = await client.auth.signOut({ scope: "local" });
      if (rollbackError) throw rollbackError;
      throw passwordError;
    }
  }, []);

  const requestPasswordReset = useCallback(async (
    email: string,
    captchaToken?: string,
  ) => {
    // A recovery email returns to this origin, not a URL supplied by account metadata.
    const redirectTo = new URL("/", window.location.origin).toString();
    const { error } = await requireClient().auth.resetPasswordForEmail(
      email.trim(),
      {
        redirectTo,
        ...(captchaToken ? { captchaToken } : {}),
      },
    );
    if (error) throw error;
  }, []);

  const updatePassword = useCallback(async (password: string) => {
    // Leave recovery mode only after the account service confirms the write.
    const { error } = await requireClient().auth.updateUser({ password });
    if (error) throw error;
    setPasswordRecovery(false);
  }, []);

  const signInWithProvider = useCallback(
    async (provider: "google" | "apple") => {
      // Desktop uses the native browser ceremony; do not start a WebView OAuth flow.
      if (isDesktopRuntime()) {
        throw new Error(
          "Social sign-in needs the signed desktop deep-link callback before it can be enabled.",
        );
      }
      const { error } = await requireClient().auth.signInWithOAuth({
        provider: provider as Provider,
        options: { redirectTo: providerRedirectUrl() },
      });
      if (error) throw error;
    },
    [],
  );

  const updateDisplayName = useCallback(async (displayName: string) => {
    // Bind every asynchronous step to the initiating account, including UI adoption.
    const currentAccount = account;
    if (!currentAccount) throw new Error("Sign in before changing the username.");
    const generation = accountGeneration.current;
    assertProfileOwner(currentAccount.id, generation);
    const normalized = displayName.trim().replace(/\s+/g, " ");
    if (!normalized) {
      throw new Error("Username cannot be empty.");
    }
    if (normalized.length > 48) {
      throw new Error("Username must be 48 characters or fewer.");
    }
    if ([...normalized].some((character) => {
      const code = character.charCodeAt(0);
      return code < 32 || code === 127;
    })) {
      throw new Error("Username contains unsupported characters.");
    }

    if (docsPreview) {
      setAccount((current) => current?.id === currentAccount.id
        ? { ...current, displayName: normalized } : current);
      return;
    }

    if (isDesktopRuntime()) {
      const configuration = browserAuthConfiguration();
      const accessToken = getAuthAccessToken();
      if (!configuration || !accessToken) {
        throw new Error("Sign in before changing the username.");
      }
      const response = await fetch(`${configuration.supabaseUrl}/auth/v1/user`, {
        method: "PUT",
        headers: {
          apikey: configuration.publishableKey,
          Authorization: `Bearer ${accessToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ data: { display_name: normalized } }),
      });
      if (!response.ok) {
        throw new Error("The username could not be saved.");
      }
      assertProfileOwner(currentAccount.id, generation);
      setAccount((current) =>
        current?.id === currentAccount.id ? { ...current, displayName: normalized } : current,
      );
      return;
    }

    const client = requireClient();
    const { data, error } = await client.auth.updateUser({
      data: { display_name: normalized },
    });
    if (error) throw error;
    assertProfileOwner(currentAccount.id, generation);

    const { data: sessionData, error: sessionError } =
      await client.auth.getSession();
    if (sessionError) throw sessionError;
    assertProfileOwner(currentAccount.id, generation);
    if (data.user.id !== currentAccount.id || sessionData.session?.user.id !== currentAccount.id) {
      throw new Error("The account changed while the username was being saved. Try again.");
    }
    adoptUser(data.user, sessionData.session?.access_token ?? null);
  }, [account, adoptUser, assertProfileOwner, docsPreview]);

  const updateAvatar = useCallback(async (avatarDataUrl: string | null) => {
    // Storage then metadata is a two-step cloud operation, not an atomic transaction.
    // If the account changes after upload, do not write metadata into the new account.
    const currentAccount = account;
    if (!currentAccount) {
      throw new Error("Sign in before changing the profile photo.");
    }
    const generation = accountGeneration.current;
    assertProfileOwner(currentAccount.id, generation);
    if (
      avatarDataUrl !== null &&
      (
        !/^data:image\/(?:jpeg|png|webp);base64,/i.test(avatarDataUrl) ||
        avatarDataUrl.length > MAX_AVATAR_DATA_URL_LENGTH
      )
    ) {
      throw new Error("The selected profile photo could not be saved.");
    }

    if (docsPreview) {
      cacheAvatarForUser(currentAccount.id, avatarDataUrl);
      setAccount((current) =>
        current ? { ...current, avatarUrl: avatarDataUrl } : current,
      );
      return;
    }

    const configuration = browserAuthConfiguration();
    if (!configuration) {
      throw new Error("Cloud account access is not configured for this build.");
    }
    const objectPath = avatarObjectPath(currentAccount.id);
    const nextAvatarUrl = avatarDataUrl
      ? avatarPublicUrl(configuration.supabaseUrl, currentAccount.id)
      : null;

    if (isDesktopRuntime()) {
      const accessToken = getAuthAccessToken();
      if (!accessToken) {
        throw new Error("Sign in before changing the profile photo.");
      }
      const objectUrl = new URL(
        `/storage/v1/object/${PROFILE_AVATAR_BUCKET}/${encodeURIComponent(currentAccount.id)}/${PROFILE_AVATAR_FILE}`,
        configuration.supabaseUrl,
      ).toString();
      let objectResponse: Response;
      try {
        objectResponse = await fetch(objectUrl, {
          method: avatarDataUrl ? "POST" : "DELETE",
          headers: {
            apikey: configuration.publishableKey,
            Authorization: `Bearer ${accessToken}`,
            ...(avatarDataUrl
              ? { "Content-Type": "image/jpeg", "x-upsert": "true" }
              : {}),
          },
          ...(avatarDataUrl ? { body: avatarJpegBlob(avatarDataUrl) } : {}),
        });
      } catch {
        throw new Error(
          "The profile photo could not be uploaded. Check your connection and try again.",
        );
      }
      if (!objectResponse.ok && !(avatarDataUrl === null && objectResponse.status === 404)) {
        throw new Error("The profile photo could not be uploaded.");
      }
      assertProfileOwner(currentAccount.id, generation);
      let metadataResponse: Response;
      try {
        metadataResponse = await fetch(
          `${configuration.supabaseUrl}/auth/v1/user`,
          {
            method: "PUT",
            headers: {
              apikey: configuration.publishableKey,
              Authorization: `Bearer ${accessToken}`,
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ data: { avatar_url: nextAvatarUrl } }),
          },
        );
      } catch {
        throw new Error(
          "The profile photo was uploaded, but the account could not be updated. Try saving it again.",
        );
      }
      if (!metadataResponse.ok) {
        throw new Error("The profile photo metadata could not be saved.");
      }
      assertProfileOwner(currentAccount.id, generation);
    } else {
      const client = requireClient();
      if (avatarDataUrl) {
        const { error: uploadError } = await client.storage
          .from(PROFILE_AVATAR_BUCKET)
          .upload(objectPath, avatarJpegBlob(avatarDataUrl), {
            cacheControl: "3600",
            contentType: "image/jpeg",
            upsert: true,
          });
        if (uploadError) throw uploadError;
      } else {
        const { error: removeError } = await client.storage
          .from(PROFILE_AVATAR_BUCKET)
          .remove([objectPath]);
        if (removeError) throw removeError;
      }
      assertProfileOwner(currentAccount.id, generation);
      const { data, error } = await client.auth.updateUser({
        data: { avatar_url: nextAvatarUrl },
      });
      if (error) throw error;
      assertProfileOwner(currentAccount.id, generation);
      const { data: sessionData, error: sessionError } =
        await client.auth.getSession();
      if (sessionError) throw sessionError;
      assertProfileOwner(currentAccount.id, generation);
      if (data.user.id !== currentAccount.id || sessionData.session?.user.id !== currentAccount.id) {
        throw new Error("The account changed while the profile photo was being saved. Try again.");
      }
      cacheAvatarForUser(currentAccount.id, nextAvatarUrl);
      adoptUser(data.user, sessionData.session?.access_token ?? null);
      return;
    }

    cacheAvatarForUser(currentAccount.id, nextAvatarUrl);
    setAccount((current) =>
      current?.id === currentAccount.id ? { ...current, avatarUrl: nextAvatarUrl } : current,
    );
  }, [account, adoptUser, assertProfileOwner, docsPreview]);

  const signOut = useCallback(async () => {
    // Stop native refresh first; preserve drafts if the actual local sign-out fails.
    let vaultClearFailed = false;
    if (isDesktopRuntime()) {
      clearBrowserAuthSessionRefresh();
      try {
        await clearBrowserAuthVault();
      } catch {
        vaultClearFailed = true;
      }
    }
    // This action means "sign out of this app". It must not revoke the shared
    // account sessions belonging to the website or another desktop edition.
    const { error } = await requireClient().auth.signOut({ scope: "local" });
    if (error) throw error;
    adoptUser(null, null);
    if (vaultClearFailed) {
      throw new Error("The desktop session closed, but its saved sign-in could not be removed.");
    }
  }, [adoptUser]);

  const value = useMemo<AuthContextValue>(
    () => ({
      configured: cloudAuthConfigured || docsPreview,
      loading,
      passwordRecovery,
      account,
      googleEnabled: googleAuthEnabled && !isDesktopRuntime(),
      appleEnabled: appleAuthEnabled && !isDesktopRuntime(),
      signInWithPassword,
      sendRegistrationCode,
      verifyRegistrationCode,
      sendRecoveryCode,
      verifyRecoveryCode,
      requestPasswordReset,
      updatePassword,
      signInWithProvider,
      updateDisplayName,
      updateAvatar,
      signOut,
    }),
    [
      account,
      docsPreview,
      loading,
      passwordRecovery,
      requestPasswordReset,
      sendRecoveryCode,
      sendRegistrationCode,
      signInWithProvider,
      signInWithPassword,
      signOut,
      updateAvatar,
      updateDisplayName,
      updatePassword,
      verifyRecoveryCode,
      verifyRegistrationCode,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  // Production consumers require the provider rather than a fabricated account.
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useOptionalAuth(): AuthContextValue | null {
  // Optional consumers can distinguish absent context from a signed-out provider.
  return useContext(AuthContext);
}

// Standalone component previews and focused unit tests do not always mount the
// application root provider. Treat those isolated renders as an explicitly
// unconfigured local build without weakening the provider-backed production UI.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuthOrLocal(): AuthContextValue {
  return useContext(AuthContext) ?? OPTIONAL_AUTH_FALLBACK;
}
