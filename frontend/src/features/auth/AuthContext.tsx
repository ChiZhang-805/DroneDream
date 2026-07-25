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

import { isDesktopRuntime } from "../../desktop/bridge";
import { clearAllExperimentDrafts } from "../experiment/draftStorage";
import { setAuthAccessToken } from "./authTokenStore";
import {
  appleAuthEnabled,
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
  account: DroneDreamAccount | null;
  googleEnabled: boolean;
  appleEnabled: boolean;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  sendRegistrationCode: (email: string) => Promise<void>;
  verifyRegistrationCode: (
    email: string,
    token: string,
    password: string,
  ) => Promise<void>;
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
  account: null,
  googleEnabled: false,
  appleEnabled: false,
  signInWithPassword: unavailableAuthAction,
  sendRegistrationCode: unavailableAuthAction,
  verifyRegistrationCode: unavailableAuthAction,
  signInWithProvider: unavailableAuthAction,
  updateDisplayName: unavailableAuthAction,
  updateAvatar: unavailableAuthAction,
  signOut: unavailableAuthAction,
};
const AVATAR_STORAGE_PREFIX = "drone-dream:account-avatar:";
const MAX_AVATAR_DATA_URL_LENGTH = 600_000;

function avatarStorageKey(userId: string): string {
  return `${AVATAR_STORAGE_PREFIX}${userId}`;
}

function localAvatarForUser(userId: string): string | null {
  if (typeof window === "undefined") return null;
  const stored = window.localStorage.getItem(avatarStorageKey(userId));
  return stored?.startsWith("data:image/") ? stored : null;
}

function metadataAvatar(user: User): string | null {
  const candidate = user.user_metadata.avatar_url ?? user.user_metadata.picture;
  return typeof candidate === "string" &&
    (candidate.startsWith("https://") || candidate.startsWith("data:image/"))
    ? candidate
    : null;
}

function accountFromUser(user: User | null): DroneDreamAccount | null {
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
    avatarUrl: localAvatarForUser(user.id) ?? metadataAvatar(user),
  };
}

function requireClient() {
  if (!supabaseClient) {
    throw new Error("Cloud account access is not configured for this build.");
  }
  return supabaseClient;
}

function providerRedirectUrl(): string {
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
  const docsPreview = import.meta.env.DEV &&
    new URLSearchParams(window.location.search).has("docsPreview");
  const [loading, setLoading] = useState(cloudAuthConfigured && !docsPreview);
  const [account, setAccount] = useState<DroneDreamAccount | null>(
    docsPreview
      ? {
          id: "docs-preview",
          email: "pilot@example.com",
          displayName: "DroneDream Pilot",
          avatarUrl: null,
        }
      : null,
  );
  const previousAccountId = useRef<string | null>(null);

  const adoptUser = useCallback((user: User | null, accessToken: string | null) => {
    const next = accountFromUser(user);
    const previousId = previousAccountId.current;
    if (previousId && previousId !== next?.id) {
      clearAllExperimentDrafts();
    }
    previousAccountId.current = next?.id ?? null;
    setAuthAccessToken(accessToken);
    setAccount(next);
  }, []);

  useEffect(() => {
    if (docsPreview) return undefined;
    if (!supabaseClient) {
      setLoading(false);
      return undefined;
    }
    let active = true;
    void supabaseClient.auth.getSession().then(({ data, error }) => {
      if (!active) return;
      if (error) {
        setAuthAccessToken(null);
        setAccount(null);
      } else {
        adoptUser(data.session?.user ?? null, data.session?.access_token ?? null);
      }
      setLoading(false);
    });
    const { data } = supabaseClient.auth.onAuthStateChange((_event, session) => {
      if (!active) return;
      adoptUser(session?.user ?? null, session?.access_token ?? null);
      setLoading(false);
    });
    return () => {
      active = false;
      data.subscription.unsubscribe();
    };
  }, [adoptUser, docsPreview]);

  const signInWithPassword = useCallback(async (
    email: string,
    password: string,
  ) => {
    const { error } = await requireClient().auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) throw error;
  }, []);

  const sendRegistrationCode = useCallback(async (email: string) => {
    const { error } = await requireClient().auth.signInWithOtp({
      email: email.trim(),
      options: { shouldCreateUser: true },
    });
    if (error) throw error;
  }, []);

  const verifyRegistrationCode = useCallback(async (
    email: string,
    token: string,
    password: string,
  ) => {
    const client = requireClient();
    const { error } = await client.auth.verifyOtp({
      email: email.trim(),
      token: token.trim(),
      type: "email",
    });
    if (error) throw error;
    const { error: passwordError } = await client.auth.updateUser({ password });
    if (passwordError) throw passwordError;
  }, []);

  const signInWithProvider = useCallback(
    async (provider: "google" | "apple") => {
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

    const client = requireClient();
    const { data, error } = await client.auth.updateUser({
      data: { display_name: normalized },
    });
    if (error) throw error;

    const { data: sessionData, error: sessionError } =
      await client.auth.getSession();
    if (sessionError) throw sessionError;
    adoptUser(data.user, sessionData.session?.access_token ?? null);
  }, [adoptUser]);

  const updateAvatar = useCallback(async (avatarDataUrl: string | null) => {
    const currentAccount = account;
    if (!currentAccount) {
      throw new Error("Sign in before changing the profile photo.");
    }
    if (
      avatarDataUrl !== null &&
      (
        !/^data:image\/(?:jpeg|png|webp);base64,/i.test(avatarDataUrl) ||
        avatarDataUrl.length > MAX_AVATAR_DATA_URL_LENGTH
      )
    ) {
      throw new Error("The selected profile photo could not be saved.");
    }

    const key = avatarStorageKey(currentAccount.id);
    if (avatarDataUrl) {
      window.localStorage.setItem(key, avatarDataUrl);
    } else {
      window.localStorage.removeItem(key);
    }
    setAccount((current) =>
      current ? { ...current, avatarUrl: avatarDataUrl } : current,
    );
  }, [account]);

  const signOut = useCallback(async () => {
    clearAllExperimentDrafts();
    const { error } = await requireClient().auth.signOut();
    if (error) throw error;
    adoptUser(null, null);
  }, [adoptUser]);

  const value = useMemo<AuthContextValue>(
    () => ({
      configured: cloudAuthConfigured || docsPreview,
      loading,
      account,
      googleEnabled: googleAuthEnabled && !isDesktopRuntime(),
      appleEnabled: appleAuthEnabled && !isDesktopRuntime(),
      signInWithPassword,
      sendRegistrationCode,
      verifyRegistrationCode,
      signInWithProvider,
      updateDisplayName,
      updateAvatar,
      signOut,
    }),
    [
      account,
      docsPreview,
      loading,
      sendRegistrationCode,
      signInWithProvider,
      signInWithPassword,
      signOut,
      updateAvatar,
      updateDisplayName,
      verifyRegistrationCode,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used inside AuthProvider.");
  }
  return context;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useOptionalAuth(): AuthContextValue | null {
  return useContext(AuthContext);
}

// Standalone component previews and focused unit tests do not always mount the
// application root provider. Treat those isolated renders as an explicitly
// unconfigured local build without weakening the provider-backed production UI.
// eslint-disable-next-line react-refresh/only-export-components
export function useAuthOrLocal(): AuthContextValue {
  return useContext(AuthContext) ?? OPTIONAL_AUTH_FALLBACK;
}
