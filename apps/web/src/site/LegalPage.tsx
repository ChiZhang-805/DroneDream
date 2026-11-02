import type { AnchorHTMLAttributes } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import privacyPolicy from "../../../../docs/legal/privacy.md?raw";
import termsOfService from "../../../../docs/legal/terms.md?raw";

export type LegalDocument = "privacy" | "terms";

const GITHUB_DOCUMENT_ROOT = "https://github.com/ChiZhang-805/DroneDream/blob/main/";

const legalDocuments: Record<LegalDocument, {
  eyebrow: string;
  source: string;
}> = {
  privacy: {
    eyebrow: "PRIVACY",
    source: privacyPolicy,
  },
  terms: {
    eyebrow: "TERMS",
    source: termsOfService,
  },
};

function legalHref(href: string | undefined): string | undefined {
  if (!href || /^(?:https?:|mailto:|#|\/)/iu.test(href)) return href;
  return `${GITHUB_DOCUMENT_ROOT}${href.replace(/^\.\//u, "")}`;
}

function LegalLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  const href = legalHref(props.href);
  const external = Boolean(href && /^https?:/iu.test(href));
  return (
    <a
      {...props}
      href={href}
      target={external ? "_blank" : undefined}
      rel={external ? "noreferrer" : undefined}
    />
  );
}

export function LegalPage({ document }: { document: LegalDocument }) {
  const selected = legalDocuments[document];
  return (
    <div className="site-legal-page">
      <article className="site-legal-document">
        <p className="site-eyebrow">{selected.eyebrow}</p>
        <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: LegalLink }}>
          {selected.source}
        </ReactMarkdown>
        <nav className="site-legal-document-links" aria-label="Legal documents">
          <a aria-current={document === "privacy" ? "page" : undefined} href="/privacy/">
            Privacy Policy
          </a>
          <a aria-current={document === "terms" ? "page" : undefined} href="/terms/">
            Terms of Service
          </a>
        </nav>
      </article>
    </div>
  );
}
