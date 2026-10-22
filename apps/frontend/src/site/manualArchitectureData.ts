export type ArchitectureSectionId = "map" | "places" | "execution";

type SiteLocale = "en" | "zh-CN";

const sectionLabels: Record<
  SiteLocale,
  readonly { id: ArchitectureSectionId; label: string }[]
> = {
  en: [
    { id: "map", label: "Map is not a map" },
    { id: "places", label: "A place becomes a node" },
    { id: "execution", label: "From intent to flight" },
  ],
  "zh-CN": [
    { id: "map", label: "Map is not a map" },
    { id: "places", label: "地点如何成为节点" },
    { id: "execution", label: "从意图到飞行" },
  ],
};

export function getArchitectureSections(locale: SiteLocale) {
  return sectionLabels[locale];
}
