export type ArchitectureSectionId = "map" | "drone" | "model";

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
    {
      id: "model",
      label: "The model is not the system",
      anchorId: "architecture-model-title",
      subsections: [
        { id: "architecture-model-transition-one", label: "Understand the request" },
        { id: "architecture-model-transition-two", label: "Call bounded tools" },
        { id: "architecture-model-transition-three", label: "Keep I/O structured" },
        { id: "architecture-model-transition-four", label: "Use visual evidence" },
        { id: "architecture-model-transition-five", label: "Run the Harness" },
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
    {
      id: "model",
      label: "The model is not the system",
      anchorId: "architecture-model-title",
      subsections: [
        { id: "architecture-model-transition-one", label: "理解自然语言任务" },
        { id: "architecture-model-transition-two", label: "调用受限工具" },
        { id: "architecture-model-transition-three", label: "保持结构化输入输出" },
        { id: "architecture-model-transition-four", label: "读取视觉证据" },
        { id: "architecture-model-transition-five", label: "运行 Harness" },
      ],
    },
  ],
};

export function getArchitectureSections(locale: SiteLocale) {
  return sectionLabels[locale];
}
