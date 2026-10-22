export type ArchitectureSectionId = "map" | "drone";

type SiteLocale = "en" | "zh-CN";

const sectionLabels: Record<
  SiteLocale,
  readonly {
    id: ArchitectureSectionId;
    label: string;
    anchorId: string;
    subsections: readonly { id: string; label: string }[];
  }[]
> = {
  en: [
    {
      id: "map",
      label: "Map is not a map",
      anchorId: "architecture-map-title",
      subsections: [
        { id: "architecture-map-transition-one", label: "Recognize the scene" },
        { id: "architecture-map-transition-two", label: "Build the graph" },
        { id: "architecture-map-transition-three", label: "Structure each place" },
      ],
    },
    {
      id: "drone",
      label: "Drone is not a drone",
      anchorId: "architecture-drone-title",
      subsections: [
        { id: "architecture-drone-transition-one", label: "Read the aircraft" },
        { id: "architecture-drone-transition-two", label: "Build its contract" },
        { id: "architecture-drone-transition-three", label: "Fit it to the map" },
      ],
    },
  ],
  "zh-CN": [
    {
      id: "map",
      label: "Map is not a map",
      anchorId: "architecture-map-title",
      subsections: [
        { id: "architecture-map-transition-one", label: "识别视觉场景" },
        { id: "architecture-map-transition-two", label: "构建连通网络" },
        { id: "architecture-map-transition-three", label: "结构化每个地点" },
      ],
    },
    {
      id: "drone",
      label: "Drone is not a drone",
      anchorId: "architecture-drone-title",
      subsections: [
        { id: "architecture-drone-transition-one", label: "读懂无人机" },
        { id: "architecture-drone-transition-two", label: "建立机型契约" },
        { id: "architecture-drone-transition-three", label: "适配地图空域" },
      ],
    },
  ],
};

export function getArchitectureSections(locale: SiteLocale) {
  return sectionLabels[locale];
}
