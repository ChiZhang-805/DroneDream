import type {
  AgentCoreHarnessCompositionItem,
  AgentCoreHarnessEdge,
  AgentCoreHarnessNode,
} from "./agentCore";

export const PUZZLE_HEIGHT = 132;
export const PUZZLE_TAB_DEPTH = 18;
export const PUZZLE_SQUARE_WIDTH = 132;
export const PUZZLE_WIDE_WIDTH = 198;
export const MODEL_BAR_WIDTH = 286;
export const MODEL_BAR_HEIGHT = 72;

export type ConnectorProfile = "round" | "key" | "wave";
export type FlowCertainty = "definite" | "possible";

export interface PuzzleConnector {
  profile: ConnectorProfile;
  sign: -1 | 0 | 1;
}

export interface HarnessVisualPlacement {
  id: string;
  x: number;
  y: number;
  row: number;
  bodyWidth: number;
  height: number;
  kind: "puzzle" | "model";
  left: PuzzleConnector;
  right: PuzzleConnector;
}

export interface HarnessLayoutOptions {
  maxWidth?: number;
  startX?: number;
  startY?: number;
  rowGap?: number;
  previewIndex?: number | null;
  previewGap?: number;
  breakOnCategory?: boolean;
}

export const harnessCategoryColors: Record<string, string> = {
  input: "#e89a14",
  reasoning: "#7757d9",
  model: "#bb3e95",
  structure: "#168ca8",
  planning: "#3278d4",
  tooling: "#3278d4",
  control: "#6552c7",
  orchestration: "#6552c7",
  safety: "#d94b50",
  memory: "#138c82",
  integration: "#2f7cbd",
  assurance: "#4f9960",
  output: "#4f9960",
};

export const harnessCategoryLabels: Record<string, [string, string]> = {
  input: ["输入", "Input"],
  reasoning: ["推理", "Reasoning"],
  model: ["模型", "Model"],
  structure: ["结构化", "Structure"],
  planning: ["规划", "Planning"],
  tooling: ["工具", "Tools"],
  control: ["控制", "Control"],
  orchestration: ["编排", "Orchestration"],
  safety: ["安全", "Safety"],
  memory: ["记忆", "Memory"],
  integration: ["集成", "Integration"],
  assurance: ["验收", "Assurance"],
  output: ["输出", "Output"],
};

function hashPair(leftId: string, rightId: string): number {
  let value = 2166136261;
  for (const character of `${leftId}>${rightId}`) {
    value ^= character.charCodeAt(0);
    value = Math.imul(value, 16777619);
  }
  return value >>> 0;
}

export function connectorForPair(leftId: string, rightId: string): PuzzleConnector {
  const hash = hashPair(leftId, rightId);
  const profiles: ConnectorProfile[] = ["round", "key", "wave"];
  return { profile: profiles[hash % profiles.length], sign: hash % 2 === 0 ? 1 : -1 };
}

export function puzzleBodyWidth(item: Pick<AgentCoreHarnessCompositionItem, "aspect_ratio">): number {
  return item.aspect_ratio === "1.5:1" ? PUZZLE_WIDE_WIDTH : PUZZLE_SQUARE_WIDTH;
}

function connectorDepth(profile: ConnectorProfile): number {
  if (profile === "key") return 16;
  if (profile === "wave") return 13;
  return 18;
}

function connectorHalf(profile: ConnectorProfile): number {
  if (profile === "key") return 16;
  if (profile === "wave") return 22;
  return 20;
}

function connectorSegment(
  side: "left" | "right",
  x: number,
  centerY: number,
  connector: PuzzleConnector,
): string {
  const half = connectorHalf(connector.profile);
  if (connector.sign === 0) return `L ${x} ${centerY - half}`;
  const outward = side === "right" ? connector.sign : -connector.sign;
  const depth = connectorDepth(connector.profile) * outward;
  if (connector.profile === "key") {
    return side === "right"
      ? `L ${x} ${centerY - half} C ${x} ${centerY - 10} ${x + depth} ${centerY - 12} ${x + depth} ${centerY - 5} L ${x + depth} ${centerY + 5} C ${x + depth} ${centerY + 12} ${x} ${centerY + 10} ${x} ${centerY + half}`
      : `L ${x} ${centerY + half} C ${x} ${centerY + 10} ${x + depth} ${centerY + 12} ${x + depth} ${centerY + 5} L ${x + depth} ${centerY - 5} C ${x + depth} ${centerY - 12} ${x} ${centerY - 10} ${x} ${centerY - half}`;
  }
  if (connector.profile === "wave") {
    return side === "right"
      ? `L ${x} ${centerY - half} C ${x + depth * 0.2} ${centerY - 15} ${x + depth} ${centerY - 13} ${x + depth} ${centerY - 4} C ${x + depth} ${centerY + 8} ${x + depth * 0.25} ${centerY + 10} ${x} ${centerY + half}`
      : `L ${x} ${centerY + half} C ${x + depth * 0.25} ${centerY + 10} ${x + depth} ${centerY + 8} ${x + depth} ${centerY - 4} C ${x + depth} ${centerY - 13} ${x + depth * 0.2} ${centerY - 15} ${x} ${centerY - half}`;
  }
  return side === "right"
    ? `L ${x} ${centerY - half} C ${x + depth} ${centerY - half} ${x + depth} ${centerY + half} ${x} ${centerY + half}`
    : `L ${x} ${centerY + half} C ${x + depth} ${centerY + half} ${x + depth} ${centerY - half} ${x} ${centerY - half}`;
}

export function puzzlePath(
  bodyWidth: number,
  left: PuzzleConnector,
  right: PuzzleConnector,
): string {
  const x0 = PUZZLE_TAB_DEPTH;
  const x1 = x0 + bodyWidth;
  const y0 = 4;
  const y1 = PUZZLE_HEIGHT - 4;
  const radius = 12;
  const centerY = PUZZLE_HEIGHT / 2;
  return [
    `M ${x0 + radius} ${y0}`,
    `L ${x1 - radius} ${y0} Q ${x1} ${y0} ${x1} ${y0 + radius}`,
    connectorSegment("right", x1, centerY, right),
    `L ${x1} ${y1 - radius} Q ${x1} ${y1} ${x1 - radius} ${y1}`,
    `L ${x0 + radius} ${y1} Q ${x0} ${y1} ${x0} ${y1 - radius}`,
    connectorSegment("left", x0, centerY, left),
    `L ${x0} ${y0 + radius} Q ${x0} ${y0} ${x0 + radius} ${y0} Z`,
  ].join(" ");
}

export function layoutHarnessItems(
  items: AgentCoreHarnessCompositionItem[],
  options: HarnessLayoutOptions = {},
): HarnessVisualPlacement[] {
  const maxWidth = options.maxWidth ?? 940;
  const startX = options.startX ?? 52;
  const startY = options.startY ?? 74;
  const rowGap = options.rowGap ?? 164;
  const previewGap = options.previewGap ?? 26;
  const output: HarnessVisualPlacement[] = [];
  let row = 0;
  let boundaryX = startX;
  let previousCategory: string | null = null;

  items.forEach((item, index) => {
    const isModel = item.visual_kind === "model";
    const bodyWidth = isModel ? MODEL_BAR_WIDTH : puzzleBodyWidth(item);
    const occupiedWidth = isModel ? bodyWidth + 42 : bodyWidth;
    const insertionGap = options.previewIndex === index ? previewGap : 0;
    const categoryBreak = Boolean(
      options.breakOnCategory
      && previousCategory !== null
      && previousCategory !== item.category_id,
    );
    if (boundaryX > startX && (categoryBreak || boundaryX + insertionGap + occupiedWidth > startX + maxWidth)) {
      row += 1;
      boundaryX = startX;
    }
    boundaryX += insertionGap;
    const x = isModel ? boundaryX : boundaryX - PUZZLE_TAB_DEPTH;
    output.push({
      id: item.item_id,
      x,
      y: startY + row * rowGap + (isModel ? (PUZZLE_HEIGHT - MODEL_BAR_HEIGHT) / 2 : 0),
      row,
      bodyWidth,
      height: isModel ? MODEL_BAR_HEIGHT : PUZZLE_HEIGHT,
      kind: isModel ? "model" : "puzzle",
      left: { profile: "round", sign: 0 },
      right: { profile: "round", sign: 0 },
    });
    boundaryX += occupiedWidth;
    if (isModel) boundaryX += 18;
    previousCategory = item.category_id;
  });

  for (let index = 0; index < output.length - 1; index += 1) {
    const current = output[index];
    const next = output[index + 1];
    if (current.row !== next.row || current.kind !== "puzzle" || next.kind !== "puzzle") continue;
    const connector = connectorForPair(current.id, next.id);
    current.right = connector;
    next.left = { profile: connector.profile, sign: connector.sign === 1 ? -1 : 1 };
  }
  return output;
}

export function validatePuzzleJoin(
  left: HarnessVisualPlacement,
  right: HarnessVisualPlacement,
): { boundaryGap: number; connectorDelta: number } {
  const leftBoundary = left.x + PUZZLE_TAB_DEPTH + left.bodyWidth;
  const rightBoundary = right.x + PUZZLE_TAB_DEPTH;
  const leftDepth = connectorDepth(left.right.profile) * left.right.sign;
  const rightDepth = connectorDepth(right.left.profile) * -right.left.sign;
  return {
    boundaryGap: rightBoundary - leftBoundary,
    connectorDelta: rightDepth - leftDepth,
  };
}

export function flowCertainty(
  edge: AgentCoreHarnessEdge,
  source: AgentCoreHarnessNode | undefined,
  target: AgentCoreHarnessNode | undefined,
): FlowCertainty {
  void edge;
  if (!source || !target) return "possible";
  if (source.capabilities.removable || target.capabilities.removable) return "possible";
  if (["branch", "bounded_loop"].includes(source.node_kind)) return "possible";
  return "definite";
}

export function categoryLabel(categoryId: string, chinese: boolean): string {
  const value = harnessCategoryLabels[categoryId];
  return value?.[chinese ? 0 : 1] ?? categoryId;
}
