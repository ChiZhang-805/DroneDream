import { Check, ChevronDown, Plus } from "lucide-react";
import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";

import type { ModelAccessProfile, ModelProvider } from "../features/settings/ModelAccessContext";
import type { ManagedModelCatalogEntry } from "../features/settings/cloudModelAccess";

const PROVIDER_COLORS: Record<ModelProvider, string> = {
  openai: "#111827",
  deepseek: "#4d6bfe",
  kimi: "#111827",
  qwen: "#615ced",
  custom: "#a53bc1",
};

const PROVIDER_PATHS: Partial<Record<ModelProvider, string>> = {
  openai: "M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.872zm16.5963 3.8558L13.1038 8.364 15.1192 7.2a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.407-.667zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z",
  deepseek: "M23.748 4.651c-.254-.124-.364.113-.512.233-.051.04-.094.09-.137.137-.372.397-.806.657-1.373.626-.829-.046-1.537.214-2.163.848-.133-.782-.575-1.248-1.247-1.548-.352-.155-.708-.311-.955-.65-.172-.24-.219-.509-.305-.774-.055-.16-.11-.323-.293-.35-.2-.031-.278.136-.356.276-.313.572-.434 1.202-.422 1.84.027 1.436.633 2.58 1.838 3.393.137.094.172.187.129.323-.082.28-.18.553-.266.833-.055.179-.137.218-.328.14a5.5 5.5 0 0 1-1.737-1.179c-.857-.828-1.631-1.743-2.597-2.46a12 12 0 0 0-.689-.47c-.985-.957.13-1.743.387-1.836.27-.098.094-.433-.778-.428-.872.003-1.67.295-2.687.685a3 3 0 0 1-.465.136 9.6 9.6 0 0 0-2.883-.101c-1.885.21-3.39 1.1-4.497 2.622C.082 8.776-.231 10.854.152 13.02c.403 2.284 1.568 4.175 3.36 5.653 1.857 1.533 3.997 2.284 6.438 2.14 1.482-.085 3.132-.284 4.994-1.86.47.234.962.328 1.78.398.629.058 1.235-.031 1.705-.129.735-.155.684-.836.418-.961-2.155-1.004-1.682-.595-2.112-.926 1.095-1.295 2.768-3.598 3.284-6.733.05-.346.115-.834.108-1.114-.004-.171.035-.238.23-.257a4.2 4.2 0 0 0 1.545-.475c1.397-.763 1.96-2.016 2.093-3.517.02-.23-.004-.467-.247-.588M11.58 18.168c-2.088-1.642-3.101-2.183-3.52-2.16-.39.024-.32.472-.234.763.09.288.207.487.371.74.114.167.192.416-.113.603-.673.416-1.842-.14-1.897-.168-1.361-.801-2.5-1.86-3.301-3.306-.775-1.393-1.225-2.888-1.299-4.482-.02-.385.094-.522.477-.592a4.7 4.7 0 0 1 1.53-.038c2.131.311 3.946 1.264 5.467 2.774.868.86 1.525 1.887 2.202 2.89.72 1.066 1.494 2.082 2.48 2.915.348.291.626.513.892.677-.802.09-2.14.109-3.055-.615z",
  kimi: "M21.765.351C22.998.351 24 1.353 24 2.586S22.998 4.82 21.765 4.82h-1.974c-.15 0-.26-.12-.26-.26V2.586A2.237 2.237 0 0 1 21.765.35M9.41 13.388l8.447-8.377c.16-.16.07-.471-.14-.471h-4.55s-.1.02-.14.06l-9.099 9.029c-.14.14-.35.02-.35-.21V4.81c0-.15-.1-.27-.221-.27H.22c-.12 0-.22.12-.22.27v18.57c0 .15.1.27.22.27h3.137c.12 0 .22-.12.22-.27v-3.79c0-.08.03-.16.08-.21l2.826-2.796c.07-.07.16-.08.241-.03l7.546 5.551a8.9 8.9 0 0 0 4.018 1.493c.12.01.23-.11.23-.27V19.76c0-.14-.08-.25-.19-.26a5.8 5.8 0 0 1-2.355-.942l-6.533-4.73c-.14-.09-.15-.32-.03-.441",
  qwen: "M23.919 14.545 20.817 9.17l1.47-2.544a.56.56 0 0 0 0-.566l-1.633-2.83a.57.57 0 0 0-.49-.283h-6.207L12.487.402a.57.57 0 0 0-.49-.284H8.732a.56.56 0 0 0-.49.284L5.139 5.775h-2.94a.56.56 0 0 0-.49.284L.077 8.887a.56.56 0 0 0 0 .567L3.18 14.83l-1.47 2.545a.56.56 0 0 0 0 .566l1.634 2.83a.57.57 0 0 0 .49.283h6.205l1.47 2.545a.57.57 0 0 0 .49.284h3.266a.57.57 0 0 0 .49-.284l3.104-5.375h2.94a.57.57 0 0 0 .49-.283l1.634-2.828a.55.55 0 0 0-.004-.568M8.733.686l1.634 2.828-1.634 2.828H21.8L20.164 9.17H7.425L5.63 6.06Zm1.306 19.801-6.205-.002 1.634-2.83h3.265L2.201 6.344h3.267q3.182 5.517 6.367 11.032 3.186 5.516 6.367 11.032zm10.124-5.66L18.53 12l-6.532 11.315-1.634-2.83c2.129-3.673 4.25-7.351 6.373-11.028h3.592l3.102 5.374z",
};

export function ModelProviderLogo({ provider }: { provider: ModelProvider }) {
  const path = PROVIDER_PATHS[provider];
  const style = { "--model-provider-color": PROVIDER_COLORS[provider] } as CSSProperties;
  if (!path) {
    return <span className="model-provider-custom-logo" style={style} aria-hidden="true">+</span>;
  }
  return (
    <svg
      className={`model-provider-logo model-provider-logo-${provider}`}
      style={style}
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <path d={path} />
    </svg>
  );
}

interface AssistantModelPickerProps {
  ariaLabel: string;
  defaultModels: readonly ManagedModelCatalogEntry[];
  customProfiles: readonly ModelAccessProfile[];
  selectedDefault: ManagedModelCatalogEntry | null;
  selectedCustomId: string | null;
  disabled?: boolean;
  onSelectDefault: (model: ManagedModelCatalogEntry) => void;
  onSelectCustom: (profileId: string) => void;
  onOpenSettings: () => void;
}

export function AssistantModelPicker({
  ariaLabel,
  defaultModels,
  customProfiles,
  selectedDefault,
  selectedCustomId,
  disabled = false,
  onSelectDefault,
  onSelectCustom,
  onOpenSettings,
}: AssistantModelPickerProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selectedCustom = customProfiles.find((profile) => profile.id === selectedCustomId) ?? null;
  const selectedProvider = selectedDefault?.provider ?? selectedCustom?.provider ?? "custom";
  const selectedLabel = selectedDefault?.display_name
    ?? selectedCustom?.model.trim()
    ?? "Choose model";

  useEffect(() => {
    if (!open) return undefined;
    const closeOnOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOnOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOnOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div className="assistant-model-picker" ref={rootRef}>
      <button
        type="button"
        role="combobox"
        className="assistant-model-button"
        aria-label={ariaLabel}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <ModelProviderLogo provider={selectedProvider} />
        <span>{selectedLabel}</span>
        <ChevronDown aria-hidden="true" />
      </button>
      {open ? (
        <div className="assistant-model-menu" role="listbox" aria-label={ariaLabel}>
          <div className="assistant-model-group-label">Default</div>
          {defaultModels.map((model) => {
            const selected = selectedDefault?.provider === model.provider
              && selectedDefault.model === model.model;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                data-model-type="default"
                data-model-id={`${model.provider}:${model.model}`}
                key={`${model.provider}:${model.model}`}
                onClick={() => {
                  onSelectDefault(model);
                  setOpen(false);
                }}
              >
                <ModelProviderLogo provider={model.provider} />
                <span><strong>{model.display_name}</strong></span>
                {selected ? <Check aria-hidden="true" /> : null}
              </button>
            );
          })}
          <div className="assistant-model-group-label assistant-model-custom-heading">Custom</div>
          {customProfiles.map((profile) => {
            const selected = selectedCustomId === profile.id;
            return (
              <button
                type="button"
                role="option"
                aria-selected={selected}
                data-model-type="custom"
                key={profile.id}
                onClick={() => {
                  onSelectCustom(profile.id);
                  setOpen(false);
                }}
              >
                <ModelProviderLogo provider={profile.provider} />
                <span><strong>{profile.model.trim() || "Provider default"}</strong></span>
                {selected ? <Check aria-hidden="true" /> : null}
              </button>
            );
          })}
          <button
            type="button"
            className="assistant-model-settings-link"
            onClick={() => {
              setOpen(false);
              onOpenSettings();
            }}
          >
            <Plus aria-hidden="true" />
            <span><strong>Add custom model</strong></span>
          </button>
        </div>
      ) : null}
    </div>
  );
}
