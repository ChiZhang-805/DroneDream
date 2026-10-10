import type {
  AutonomyClarification,
  AutonomyClarificationOption,
  AutonomyClarificationQuestion,
} from "./workspaceStore";

const FIELD_LABELS: Readonly<Record<string, { zh: string; en: string }>> = {
  target_entity: { zh: "目标地点", en: "destination" },
  start_entity: { zh: "出发地点", en: "starting location" },
  return_entity: { zh: "返回地点", en: "return location" },
  payload_action: { zh: "取件方式", en: "payload action" },
};

const PLACE_LABELS: Readonly<Record<string, { zh: string; en: string }>> = {
  lounge: { zh: "休息室", en: "Lounge" },
  pantry: { zh: "茶水间 / 备餐室", en: "Pantry" },
  supplies: { zh: "物资区", en: "Supplies" },
  office: { zh: "办公室", en: "Office" },
  reception: { zh: "接待处", en: "Reception" },
};

function machineField(value: string): string | null {
  const normalized = value.trim().toLocaleLowerCase("en-US");
  if (FIELD_LABELS[normalized]) return normalized;
  return Object.keys(FIELD_LABELS).find((field) => normalized.includes(field)) ?? null;
}

function englishToken(value: string): string | null {
  const parenthesized = value.match(/\(([a-z][a-z0-9 _-]{1,48})\)/iu)?.[1];
  if (parenthesized) return parenthesized.trim().toLocaleLowerCase("en-US");
  const leading = value.trim().match(/^([a-z][a-z0-9 _-]{1,48})(?=\s|$)/iu)?.[1];
  return leading?.trim().toLocaleLowerCase("en-US") ?? null;
}

function localizedOptionLabel(value: string, chinese: boolean): string {
  const compact = value.replace(/\s+/gu, " ").trim();
  const token = englishToken(compact);
  const known = token ? PLACE_LABELS[token] : undefined;
  if (known) return chinese ? `${known.zh}（${token}）` : `${known.en} (${known.zh})`;
  if (!chinese || /[\u3400-\u9fff]/u.test(compact) === false) return compact;
  const englishFirst = compact.match(/^([a-z][a-z0-9 _-]{1,48})\s+([\u3400-\u9fff].*)$/iu);
  return englishFirst ? `${englishFirst[2]}（${englishFirst[1].trim()}）` : compact;
}

function localizedPrompt(question: AutonomyClarificationQuestion, chinese: boolean): string {
  const field = machineField(question.questionId) ?? machineField(question.prompt);
  if (field === "target_entity") {
    return chinese
      ? "外卖放在哪个位置？请选择地图中的地点，或者填写其他位置。"
      : "Where should the pickup happen? Choose a mapped place or enter another location.";
  }
  if (field) {
    const label = FIELD_LABELS[field];
    return chinese
      ? `请确认${label.zh}。请选择一个地点，或者填写其他位置。`
      : `Please confirm the ${label.en}. Choose a place or enter another location.`;
  }
  if (chinese && !/[\u3400-\u9fff]/u.test(question.prompt)) {
    return "还需要补充一项任务信息，请选择最符合的选项。";
  }
  return question.prompt.trim();
}

export function presentAutonomyClarification(
  clarification: AutonomyClarification | null | undefined,
  chinese: boolean,
): AutonomyClarification | null {
  if (!clarification?.questions.length) return null;
  return {
    questions: clarification.questions.map((question) => ({
      ...question,
      prompt: localizedPrompt(question, chinese),
      options: question.options.map((option) => ({
        ...option,
        label: localizedOptionLabel(option.label, chinese),
      })),
      otherLabel: chinese ? "其他" : "Other",
    })),
  };
}

export function clarificationBrief(
  fields: string[],
  clarification: AutonomyClarification | null | undefined,
  chinese: boolean,
): string {
  const presented = presentAutonomyClarification(clarification, chinese);
  if (presented?.questions.length) {
    return chinese ? "还需要确认一项任务信息。" : "One mission detail still needs confirmation.";
  }
  const labels = fields.map((field) => {
    const key = machineField(field);
    if (key) return chinese ? FIELD_LABELS[key].zh : FIELD_LABELS[key].en;
    return field.trim();
  }).filter(Boolean);
  return chinese
    ? `还需要确认：${labels.join("、") || "任务所需信息"}。`
    : `Please confirm: ${labels.join(", ") || "a required mission detail"}.`;
}

function mapEntityToken(option: AutonomyClarificationOption): string | null {
  const token = option.response.match(/\b(?:[a-z0-9]+-)+(?:[a-z][a-z0-9-]*)\b/iu)?.[0]
    ?? option.response.match(/\b(?:lounge|pantry|supplies|office|reception)\b/iu)?.[0]
    ?? null;
  if (!token) return null;

  // Imported multilevel maps may use `l1-*`, `l2-*`, ... . An older
  // clarification formatter dropped the leading `l` and emitted `1-*`, which
  // made a valid mapped destination fail later in the route tool as an unknown
  // entity. Repair that bounded legacy spelling before it reaches planning.
  return /^\d+-/u.test(token) ? `l${token}` : token;
}

export function clarificationOptionAnswer(
  question: AutonomyClarificationQuestion,
  option: AutonomyClarificationOption,
  chinese: boolean,
): string {
  const label = localizedOptionLabel(option.label, chinese);
  const entity = mapEntityToken(option);
  const field = machineField(question.questionId) ?? machineField(question.prompt);
  // Unknown extension questions own their response wording. Only rewrite
  // fields whose semantics are part of the app contract; this keeps plug-in
  // questions compatible while preventing internal map IDs from being lost.
  if (!field) return option.response.trim();
  if (chinese) {
    const prefix = field === "target_entity" ? "目标地点" : "我的选择";
    return `${prefix}：${label}${entity && !label.toLocaleLowerCase("en-US").includes(entity.toLocaleLowerCase("en-US")) ? `，地图地点 ${entity}` : ""}。`;
  }
  const prefix = field === "target_entity" ? "Destination" : "My choice";
  return `${prefix}: ${label}${entity && !label.toLocaleLowerCase("en-US").includes(entity.toLocaleLowerCase("en-US")) ? `, map entity ${entity}` : ""}.`;
}

export function clarificationOtherAnswer(
  question: AutonomyClarificationQuestion,
  answer: string,
  chinese: boolean,
): string {
  const field = machineField(question.questionId) ?? machineField(question.prompt);
  if (chinese) return `${field === "target_entity" ? "目标地点" : "补充信息"}：${answer.trim()}。`;
  return `${field === "target_entity" ? "Destination" : "Additional detail"}: ${answer.trim()}.`;
}
