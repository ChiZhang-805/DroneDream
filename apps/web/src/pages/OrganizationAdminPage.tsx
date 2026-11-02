import { useAuth } from "../features/auth/AuthContext";
import { useI18n } from "../i18n/I18nProvider";
import { OrganizationPage } from "../site/OrganizationPage";
import "../site/site.css";

export function OrganizationAdminPage() {
  const auth = useAuth();
  const { locale } = useI18n();
  return (
    <OrganizationPage
      locale={locale}
      accountId={auth.account?.id ?? null}
      accountAvatarUrl={auth.account?.avatarUrl ?? null}
      accountAvatarFallbackUrl={auth.account?.avatarFallbackUrl ?? null}
    />
  );
}
