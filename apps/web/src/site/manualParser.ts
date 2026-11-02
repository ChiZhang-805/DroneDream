export interface ManualHeading {
  id: string;
  level: 1 | 2 | 3;
  label: string;
  plainLabel: string;
  majorIndex: number;
}

function stripInlineMarkdown(value: string): string {
  return value
    .replace(/!\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/[`*_~]/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function stripManualFrontmatter(source: string): string {
  return source.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, "").trim();
}

export function extractManualHeadings(source: string): ManualHeading[] {
  let majorIndex = -1;
  let headingIndex = 0;
  return stripManualFrontmatter(source)
    .split(/\r?\n/)
    .flatMap((line) => {
      const match = /^(#{1,3})\s+(.+?)\s*$/.exec(line);
      if (!match) return [];
      const level = match[1].length as 1 | 2 | 3;
      if (level === 1) majorIndex += 1;
      const label = match[2].trim();
      const heading: ManualHeading = {
        id: `manual-heading-${headingIndex}`,
        level,
        label,
        plainLabel: stripInlineMarkdown(label),
        majorIndex: Math.max(0, majorIndex),
      };
      headingIndex += 1;
      return [heading];
    });
}
