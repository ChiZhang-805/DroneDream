import { useRef, useState, type FormEvent } from "react";
import { useAuthOrLocal } from "../features/auth/AuthContext";
import { AuthCaptcha } from "../features/auth/AuthCaptcha";
import { captchaProtectionConfigured, turnstileSiteKey } from "../features/auth/supabaseClient";

const COPY = {
  en: { title: "Welcome to DroneDream", login: "Sign in", register: "Create account", email: "Email", password: "Password", code: "Email code", send: "Send code", verify: "Verify & continue", busy: "Please wait…", sent: "Check your email for a code.", failed: "Sign-in failed. Try again.", codeFailed: "Code not sent. Try again.", verifyFailed: "Check the code and try again.", unavailable: "Account access is unavailable.", forgot: "Forgot password?", recovery: "Reset your password", newPassword: "New password", back: "Back to sign in", reset: "Reset & sign in", passwordHint: "At least 8 characters" },
  "zh-CN": { title: "欢迎使用 DroneDream", login: "登录", register: "注册", email: "邮箱", password: "密码", code: "邮箱验证码", send: "发送验证码", verify: "验证并继续", busy: "请稍候…", sent: "验证码已发送，请查看邮箱。", failed: "登录失败，请重试。", codeFailed: "发送失败，请重试。", verifyFailed: "验证码有误，请重试。", unavailable: "账户服务暂不可用。", forgot: "忘记密码？", recovery: "找回密码", newPassword: "新密码", back: "返回登录", reset: "重置并登录", passwordHint: "至少 8 位字符" },
} as const;

/** Shared by all launchers; account operations stay in the existing provider. */
export function LauncherAccountForm({ locale, onAuthenticated }: {
  locale: "en" | "zh-CN";
  onAuthenticated?: () => void;
}) {
  const auth = useAuthOrLocal();
  const copy = COPY[locale];
  const [mode, setMode] = useState<"login" | "register" | "recovery">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [captcha, setCaptcha] = useState<string | null>(null);
  const [captchaAttempt, setCaptchaAttempt] = useState(0);
  const submitting = useRef(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError("");
    try {
      if (mode === "login") {
        await auth.signInWithPassword(email, password, captcha ?? undefined);
        setPassword("");
        onAuthenticated?.();
      } else if (!sent) {
        if (mode === "recovery") await auth.sendRecoveryCode(email, captcha ?? undefined);
        else await auth.sendRegistrationCode(email, captcha ?? undefined);
        setSent(true);
      } else {
        if (mode === "recovery") await auth.verifyRecoveryCode(email, code, password);
        else await auth.verifyRegistrationCode(email, code, password);
        setPassword("");
        onAuthenticated?.();
      }
    } catch {
      setError(mode === "login" ? copy.failed : sent ? copy.verifyFailed : copy.codeFailed);
    } finally {
      submitting.current = false;
      setBusy(false);
      setCaptcha(null);
      setCaptchaAttempt((value) => value + 1);
    }
  };
  const message = error || (!auth.configured ? copy.unavailable : sent ? copy.sent : "");
  const caption = <span className="launcher-auth-message" role={error ? "alert" : "status"} aria-live="polite" title={message}>{message}</span>;
  return (
    <form className="launcher-account-form" onSubmit={(event) => void submit(event)}>
      <h2>{mode === "recovery" ? copy.recovery : copy.title}</h2>
      <div role="tablist" className="launcher-auth-tabs" hidden={mode === "recovery"} aria-label={copy.title}>
        {(["login", "register"] as const).map((value) => <button role="tab" key={value} type="button" disabled={busy}
          aria-selected={mode === value} onClick={() => { setMode(value); setError(""); setSent(false); setCode(""); setPassword(""); }}>
          {copy[value]}
        </button>)}
      </div>
      <label>{copy.email}<input type="email" autoComplete="username" required value={email} disabled={busy || sent}
        onChange={(event) => setEmail(event.target.value)} /></label>
      <label hidden={sent}><span className="launcher-auth-caption">{mode === "recovery" ? copy.newPassword : copy.password}{!sent ? caption : null}</span><input aria-label={mode === "recovery" ? copy.newPassword : copy.password} aria-invalid={Boolean(error)} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"}
        required minLength={mode !== "login" ? 8 : undefined} placeholder={mode !== "login" ? copy.passwordHint : undefined}
        value={password} disabled={busy} onChange={(event) => setPassword(event.target.value)} /></label>
      <div className="launcher-auth-verification" hidden={!sent && !captchaProtectionConfigured}>
        {sent ? <label><span className="launcher-auth-caption">{copy.code}{caption}</span><input aria-label={copy.code} aria-invalid={Boolean(error)} autoComplete="one-time-code" inputMode="numeric" required value={code}
          onChange={(event) => setCode(event.target.value)} disabled={busy} /></label>
          : captchaProtectionConfigured ? <AuthCaptcha key={captchaAttempt} siteKey={turnstileSiteKey} locale={locale} onTokenChange={setCaptcha} /> : null}
      </div>
      <button className="btn btn-primary" type="submit" disabled={busy || !auth.configured || (captchaProtectionConfigured && !sent && !captcha)}>
        {busy ? copy.busy : mode === "login" ? copy.login : sent ? mode === "recovery" ? copy.reset : copy.verify : copy.send}
      </button>
      <button className="launcher-auth-secondary" type="button" disabled={busy} onClick={() => {
        setMode(mode === "login" ? "recovery" : "login"); setSent(false); setCode(""); setPassword(""); setError("");
      }}>{mode === "login" ? copy.forgot : copy.back}</button>
    </form>
  );
}
