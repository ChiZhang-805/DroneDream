import {
  BarChart3,
  BookOpen,
  Bot,
  CheckSquare2,
  CircleHelp,
  ClipboardCheck,
  CloudCog,
  FileCheck2,
  Gauge,
  History,
  LayoutDashboard,
  ListChecks,
  MessageSquareText,
  PlayCircle,
  Route,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import {
  stripManualFrontmatter,
  type ManualHeading,
} from "./manualParser";

const chapterIcons: LucideIcon[] = [
  BookOpen,
  Gauge,
  LayoutDashboard,
  MessageSquareText,
  Route,
  SlidersHorizontal,
  CloudCog,
  Settings2,
  ClipboardCheck,
  BarChart3,
  ShieldCheck,
  Wrench,
  CheckSquare2,
  Sparkles,
  FileCheck2,
  CircleHelp,
  ListChecks,
];

function textFromReactNode(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(textFromReactNode).join("");
  if (node && typeof node === "object" && "props" in node) {
    return textFromReactNode((node as { props?: { children?: ReactNode } }).props?.children);
  }
  return "";
}

function resolveManualImage(src: string | undefined): string | undefined {
  if (!src) return src;
  if (src.startsWith("manual-assets/")) return `/docs/downloads/${src}`;
  return src;
}

interface ManualDocumentProps {
  source: string;
  headings: ManualHeading[];
}

export default function ManualDocument({ source, headings }: ManualDocumentProps) {
  let headingCursor = 0;

  const nextHeading = (level: 1 | 2 | 3, children: ReactNode) => {
    const expected = headings[headingCursor];
    const plainLabel = textFromReactNode(children).trim();
    if (expected?.level === level && expected.plainLabel === plainLabel) {
      headingCursor += 1;
      return expected;
    }
    const fallback: ManualHeading = {
      id: `manual-heading-runtime-${headingCursor}`,
      level,
      label: plainLabel,
      plainLabel,
      majorIndex: Math.max(0, expected?.majorIndex ?? 0),
    };
    headingCursor += 1;
    return fallback;
  };

  const headingProps = (heading: ManualHeading) => ({
    id: heading.id,
    "data-manual-heading": "true",
    "data-manual-heading-level": heading.level,
    tabIndex: -1,
  });

  return (
    <div className="manual-markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          h1({ children }) {
            const heading = nextHeading(1, children);
            const Icon = chapterIcons[heading.majorIndex % chapterIcons.length];
            return (
              <h1 {...headingProps(heading)}>
                <span className="manual-chapter-icon" aria-hidden="true">
                  <Icon />
                </span>
                <span>{children}</span>
                <i aria-hidden="true" />
              </h1>
            );
          },
          h2({ children }) {
            const heading = nextHeading(2, children);
            return (
              <h2 {...headingProps(heading)}>
                <span aria-hidden="true" />
                {children}
              </h2>
            );
          },
          h3({ children }) {
            const heading = nextHeading(3, children);
            return (
              <h3 {...headingProps(heading)}>
                <span aria-hidden="true" />
                {children}
              </h3>
            );
          },
          p({ node, children }) {
            const containsImage = node?.children.some(
              (child) => child.type === "element" && child.tagName === "img",
            );
            if (containsImage) return <>{children}</>;
            return <p>{children}</p>;
          },
          a({ href, children }) {
            const external = href?.startsWith("http");
            return (
              <a
                href={href}
                {...(external ? { target: "_blank", rel: "noreferrer" } : {})}
              >
                {children}
              </a>
            );
          },
          img({ src, alt }) {
            return (
              <figure className="manual-native-figure">
                <img
                  src={resolveManualImage(src)}
                  alt={alt ?? ""}
                  loading="lazy"
                />
                {alt ? <figcaption>{alt}</figcaption> : null}
              </figure>
            );
          },
          table({ children }) {
            return (
              <div className="manual-table-scroll" tabIndex={0}>
                <table>{children}</table>
              </div>
            );
          },
          blockquote({ children }) {
            return (
              <blockquote>
                <ShieldCheck aria-hidden="true" />
                <div>{children}</div>
              </blockquote>
            );
          },
          code({ className, children }) {
            return (
              <code className={className}>
                {children}
              </code>
            );
          },
          hr() {
            return (
              <div className="manual-rule" aria-hidden="true">
                <span />
                <Sparkles />
                <span />
              </div>
            );
          },
          ul({ children }) {
            return <ul>{children}</ul>;
          },
          ol({ children }) {
            return <ol>{children}</ol>;
          },
          li({ children }) {
            return <li>{children}</li>;
          },
          strong({ children }) {
            return <strong>{children}</strong>;
          },
          pre({ children }) {
            return <pre>{children}</pre>;
          },
        }}
      >
        {stripManualFrontmatter(source)}
      </ReactMarkdown>
      <footer className="manual-document-end">
        <PlayCircle aria-hidden="true" />
        <span>DroneDream 1.0.0</span>
        <Bot aria-hidden="true" />
        <span>AURORA Harness</span>
        <History aria-hidden="true" />
        <span>Reproducible evidence</span>
      </footer>
    </div>
  );
}
