import { useEffect, useRef, useState, type AnchorHTMLAttributes } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import codeSigningPolicy from "../../../CODE_SIGNING_POLICY.md?raw";
import privacyPolicy from "../../../PRIVACY.md?raw";

type PolicySection = "privacy" | "code-signing";

interface PolicyDialogProps {
  onClose: () => void;
}

const GITHUB_DOCUMENT_ROOT = "https://github.com/ChiZhang-805/DroneDream/blob/main/";

const policySections: Array<{
  id: PolicySection;
  label: string;
  source: string;
}> = [
  { id: "privacy", label: "Privacy", source: privacyPolicy },
  { id: "code-signing", label: "Code signing", source: codeSigningPolicy },
];

function policyBody(source: string): string {
  return source.replace(/^#\s+[^\r\n]+\r?\n+/u, "");
}

function policyHref(href: string | undefined): string | undefined {
  if (!href || /^(?:https?:|mailto:|#)/iu.test(href)) return href;
  return `${GITHUB_DOCUMENT_ROOT}${href.replace(/^\.\//u, "")}`;
}

function PolicyLink(props: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <a
      {...props}
      href={policyHref(props.href)}
      target="_blank"
      rel="noreferrer"
    />
  );
}

export default function PolicyDialog({ onClose }: PolicyDialogProps) {
  const [activeSection, setActiveSection] = useState<PolicySection>("privacy");
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const selectedPolicy = policySections.find((section) => section.id === activeSection)
    ?? policySections[0];

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeButtonRef.current?.focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [onClose]);

  return (
    <div
      className="site-policy-backdrop"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <section
        className="site-policy-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="site-policy-title"
      >
        <header className="site-policy-header">
          <div>
            <span>DroneDream</span>
            <h2 id="site-policy-title">Policies</h2>
          </div>
          <button ref={closeButtonRef} type="button" aria-label="Close policies" onClick={onClose}>
            <span aria-hidden="true">×</span>
          </button>
        </header>

        <div className="site-policy-tabs" role="tablist" aria-label="Policy sections">
          {policySections.map((section) => (
            <button
              key={section.id}
              id={`site-policy-tab-${section.id}`}
              type="button"
              role="tab"
              aria-selected={section.id === activeSection}
              aria-controls="site-policy-panel"
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </button>
          ))}
        </div>

        <article
          id="site-policy-panel"
          className="site-policy-content"
          role="tabpanel"
          aria-labelledby={`site-policy-tab-${selectedPolicy.id}`}
          tabIndex={0}
        >
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ a: PolicyLink }}>
            {policyBody(selectedPolicy.source)}
          </ReactMarkdown>
        </article>
      </section>
    </div>
  );
}
