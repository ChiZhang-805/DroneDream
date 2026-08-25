export type ModelProvider =
  | "openai"
  | "anthropic"
  | "google"
  | "xai"
  | "qwen"
  | "deepseek"
  | "kimi"
  | "zhipu"
  | "mistral"
  | "cohere"
  | "together"
  | "groq"
  | "perplexity"
  | "openrouter"
  | "azure-openai"
  | "aws-bedrock"
  | "ollama"
  | "custom";

export type ManagedModelProvider = "openai" | "qwen" | "deepseek" | "kimi";

export type ModelApiProtocol =
  | "openai-responses"
  | "openai-chat"
  | "anthropic-messages"
  | "google-generate-content"
  | "aws-bedrock-converse"
  | "ollama-chat"
  | "custom-http";

export interface ModelProviderDefinition {
  id: ModelProvider;
  label: string;
  shortLabel: string;
  color: string;
  defaultBaseUrl: string;
  defaultModel: string;
  defaultProtocol: ModelApiProtocol;
  protocols: readonly ModelApiProtocol[];
  endpointPatterns: readonly RegExp[];
  modelPatterns: readonly RegExp[];
  keyPatterns?: readonly RegExp[];
}

const OPENAI_COMPATIBLE: readonly ModelApiProtocol[] = [
  "openai-responses",
  "openai-chat",
];

export const MODEL_PROVIDER_CATALOG: readonly ModelProviderDefinition[] = [
  {
    id: "openai",
    label: "OpenAI",
    shortLabel: "OA",
    color: "#111827",
    defaultBaseUrl: "https://api.openai.com/v1",
    defaultModel: "gpt-5.4",
    defaultProtocol: "openai-responses",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.openai\.com/i],
    modelPatterns: [/^(gpt|o\d|chatgpt|text-embedding|dall-e|whisper)/i],
    keyPatterns: [/^sk-(?!or-)(proj-|svcacct-)?/i],
  },
  {
    id: "anthropic",
    label: "Anthropic",
    shortLabel: "AI",
    color: "#d97757",
    defaultBaseUrl: "https://api.anthropic.com",
    defaultModel: "claude-sonnet-4-6",
    defaultProtocol: "anthropic-messages",
    protocols: ["anthropic-messages"],
    endpointPatterns: [/api\.anthropic\.com/i],
    modelPatterns: [/^claude-/i],
    keyPatterns: [/^sk-ant-/i],
  },
  {
    id: "google",
    label: "Google Gemini",
    shortLabel: "G",
    color: "#4285f4",
    defaultBaseUrl: "https://generativelanguage.googleapis.com/v1beta",
    defaultModel: "gemini-2.5-pro",
    defaultProtocol: "google-generate-content",
    protocols: ["google-generate-content", "openai-chat"],
    endpointPatterns: [/generativelanguage\.googleapis\.com/i, /aiplatform\.googleapis\.com/i],
    modelPatterns: [/^gemini-/i],
    keyPatterns: [/^AIza[0-9A-Za-z_-]+$/],
  },
  {
    id: "xai",
    label: "xAI",
    shortLabel: "xAI",
    color: "#111111",
    defaultBaseUrl: "https://api.x.ai/v1",
    defaultModel: "grok-4",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.x\.ai/i],
    modelPatterns: [/^grok-/i],
    keyPatterns: [/^xai-/i],
  },
  {
    id: "qwen",
    label: "Qwen",
    shortLabel: "Q",
    color: "#615ced",
    defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    defaultModel: "qwen-plus",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/dashscope\.aliyuncs\.com/i, /bailian\./i],
    modelPatterns: [/^qwen/i, /^qwq/i],
  },
  {
    id: "deepseek",
    label: "DeepSeek",
    shortLabel: "DS",
    color: "#4d6bfe",
    defaultBaseUrl: "https://api.deepseek.com",
    defaultModel: "deepseek-chat",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.deepseek\.com/i],
    modelPatterns: [/^deepseek-/i],
  },
  {
    id: "kimi",
    label: "Kimi",
    shortLabel: "K",
    color: "#111827",
    defaultBaseUrl: "https://api.moonshot.ai/v1",
    defaultModel: "kimi-k2.5",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.moonshot\.(ai|cn)/i, /api\.kimi\./i],
    modelPatterns: [/^kimi-/i, /^moonshot-/i],
  },
  {
    id: "zhipu",
    label: "Zhipu GLM",
    shortLabel: "GLM",
    color: "#246bfd",
    defaultBaseUrl: "https://open.bigmodel.cn/api/paas/v4",
    defaultModel: "glm-4.5",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/open\.bigmodel\.cn/i, /api\.zhipuai\.cn/i],
    modelPatterns: [/^glm-/i, /^codegeex-/i],
  },
  {
    id: "mistral",
    label: "Mistral AI",
    shortLabel: "M",
    color: "#f7a600",
    defaultBaseUrl: "https://api.mistral.ai/v1",
    defaultModel: "mistral-large-latest",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.mistral\.ai/i],
    modelPatterns: [/^(mistral|ministral|codestral|pixtral)/i],
  },
  {
    id: "cohere",
    label: "Cohere",
    shortLabel: "C",
    color: "#39594d",
    defaultBaseUrl: "https://api.cohere.com/v2",
    defaultModel: "command-a-03-2025",
    defaultProtocol: "custom-http",
    protocols: ["custom-http", "openai-chat"],
    endpointPatterns: [/api\.cohere\.(com|ai)/i],
    modelPatterns: [/^command-/i, /^embed-/i, /^rerank-/i],
  },
  {
    id: "together",
    label: "Together AI",
    shortLabel: "T",
    color: "#ec33c2",
    defaultBaseUrl: "https://api.together.xyz/v1",
    defaultModel: "meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.together\.xyz/i, /api\.together\.ai/i],
    modelPatterns: [/^(meta-llama|Qwen\/|deepseek-ai\/|mistralai\/)/i],
  },
  {
    id: "groq",
    label: "Groq",
    shortLabel: "GQ",
    color: "#f55036",
    defaultBaseUrl: "https://api.groq.com/openai/v1",
    defaultModel: "llama-3.3-70b-versatile",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.groq\.com/i],
    modelPatterns: [/versatile$/i],
    keyPatterns: [/^gsk_/i],
  },
  {
    id: "perplexity",
    label: "Perplexity",
    shortLabel: "P",
    color: "#20808d",
    defaultBaseUrl: "https://api.perplexity.ai",
    defaultModel: "sonar-pro",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/api\.perplexity\.ai/i],
    modelPatterns: [/^sonar/i],
    keyPatterns: [/^pplx-/i],
  },
  {
    id: "openrouter",
    label: "OpenRouter",
    shortLabel: "OR",
    color: "#6366f1",
    defaultBaseUrl: "https://openrouter.ai/api/v1",
    defaultModel: "openai/gpt-4.1",
    defaultProtocol: "openai-chat",
    protocols: OPENAI_COMPATIBLE,
    endpointPatterns: [/openrouter\.ai/i],
    modelPatterns: [/^[\w.-]+\/[\w./:-]+$/i],
    keyPatterns: [/^sk-or-/i],
  },
  {
    id: "azure-openai",
    label: "Azure OpenAI",
    shortLabel: "Az",
    color: "#0078d4",
    defaultBaseUrl: "",
    defaultModel: "",
    defaultProtocol: "openai-chat",
    protocols: ["openai-responses", "openai-chat"],
    endpointPatterns: [/\.openai\.azure\.com/i, /\.services\.ai\.azure\.com/i],
    modelPatterns: [],
  },
  {
    id: "aws-bedrock",
    label: "Amazon Bedrock",
    shortLabel: "AWS",
    color: "#ff9900",
    defaultBaseUrl: "",
    defaultModel: "",
    defaultProtocol: "aws-bedrock-converse",
    protocols: ["aws-bedrock-converse"],
    endpointPatterns: [/bedrock-runtime\.[\w-]+\.amazonaws\.com/i],
    modelPatterns: [/^(anthropic|amazon|meta|mistral|cohere)\./i],
  },
  {
    id: "ollama",
    label: "Ollama",
    shortLabel: "O",
    color: "#111111",
    defaultBaseUrl: "http://127.0.0.1:11434",
    defaultModel: "llama3.3",
    defaultProtocol: "ollama-chat",
    protocols: ["ollama-chat", "openai-chat"],
    endpointPatterns: [/^(https?:\/\/)?(localhost|127\.0\.0\.1|\[::1\])(?::11434)?/i, /\/api\/chat/i],
    modelPatterns: [/^(llama|gemma|phi|qwen|deepseek-r1)(:|$)/i],
  },
  {
    id: "custom",
    label: "Custom",
    shortLabel: "+",
    color: "#a53bc1",
    defaultBaseUrl: "",
    defaultModel: "",
    defaultProtocol: "openai-chat",
    protocols: [
      "openai-responses",
      "openai-chat",
      "anthropic-messages",
      "google-generate-content",
      "aws-bedrock-converse",
      "ollama-chat",
      "custom-http",
    ],
    endpointPatterns: [],
    modelPatterns: [],
  },
] as const;

const PROVIDER_BY_ID = new Map(MODEL_PROVIDER_CATALOG.map((provider) => [provider.id, provider]));

export function isModelProvider(value: unknown): value is ModelProvider {
  return typeof value === "string" && PROVIDER_BY_ID.has(value as ModelProvider);
}

export function isManagedModelProvider(value: unknown): value is ManagedModelProvider {
  return value === "openai" || value === "qwen" || value === "deepseek" || value === "kimi";
}

export function modelProviderDefinition(provider: ModelProvider): ModelProviderDefinition {
  return PROVIDER_BY_ID.get(provider) ?? PROVIDER_BY_ID.get("custom")!;
}

export function modelProviderLabel(provider: ModelProvider): string {
  return modelProviderDefinition(provider).label;
}

export function modelProviderDefaults(provider: ModelProvider) {
  const definition = modelProviderDefinition(provider);
  return {
    model: definition.defaultModel,
    baseUrl: definition.defaultBaseUrl,
    protocol: definition.defaultProtocol,
    displayName: "",
  } as const;
}

export interface ModelProviderDetectionInput {
  baseUrl?: string;
  model?: string;
  apiKey?: string;
}

export interface ModelProviderDetectionResult {
  provider: ModelProvider;
  confidence: "high" | "medium" | "low";
  matchedBy: readonly ("endpoint" | "model" | "key")[];
}

export function detectModelProvider({
  baseUrl = "",
  model = "",
  apiKey = "",
}: ModelProviderDetectionInput): ModelProviderDetectionResult {
  const candidates = MODEL_PROVIDER_CATALOG
    .filter((provider) => provider.id !== "custom")
    .map((provider) => {
      const matchedBy: Array<"endpoint" | "model" | "key"> = [];
      if (baseUrl && provider.endpointPatterns.some((pattern) => pattern.test(baseUrl.trim()))) {
        matchedBy.push("endpoint");
      }
      if (model && provider.modelPatterns.some((pattern) => pattern.test(model.trim()))) {
        matchedBy.push("model");
      }
      if (apiKey && provider.keyPatterns?.some((pattern) => pattern.test(apiKey.trim()))) {
        matchedBy.push("key");
      }
      const score = matchedBy.reduce((total, signal) => total + ({ endpoint: 5, key: 4, model: 2 }[signal]), 0);
      return { provider: provider.id, matchedBy, score };
    })
    .filter((candidate) => candidate.score > 0)
    .sort((left, right) => right.score - left.score);

  const best = candidates[0];
  if (!best) {
    return { provider: "custom", confidence: "low", matchedBy: [] };
  }
  return {
    provider: best.provider,
    confidence: best.score >= 7 ? "high" : best.score >= 4 ? "medium" : "low",
    matchedBy: best.matchedBy,
  };
}

export const MODEL_API_PROTOCOL_LABELS: Record<ModelApiProtocol, string> = {
  "openai-responses": "OpenAI Responses",
  "openai-chat": "OpenAI Chat Completions",
  "anthropic-messages": "Anthropic Messages",
  "google-generate-content": "Google GenerateContent",
  "aws-bedrock-converse": "AWS Bedrock Converse",
  "ollama-chat": "Ollama Chat",
  "custom-http": "Custom HTTP",
};
