import { useContext, useEffect, useRef, useState } from "react";
import { Check, LoaderCircle, ScanSearch } from "lucide-react";
import type { BrandEditionId } from "../../brand/edition-brand.generated";
import { useOptionalAuth } from "../auth/AuthContext";
import { ModelAccessContext } from "../settings/ModelAccessContext";
import { interpretAgentCoreAsset } from "./agentCorePlanning";

// 功能：
//   为资产卡片提供无背景解析图标，抑制重复点击并隔离换选后的旧回包。
// 输入：
//   props：卡片资产、版本与界面语言。
// 输出：
//   button：带键盘名称和忙碌状态的解析按钮。
export function AssetInterpretButton(props: { edition: BrandEditionId; chinese: boolean; kind: "map" | "vehicle"; assetId: string | null; contentSha256: string | null; name: string }) {
  const auth = useOptionalAuth();
  const access = useContext(ModelAccessContext);
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const generation = useRef(0);
  const pending = useRef(false);
  const settings = access?.settings;
  const identity = JSON.stringify([props.edition, props.kind, props.assetId, props.contentSha256, auth?.account?.id, settings?.accessMode, settings?.managedProvider, settings?.managedModel, settings?.provider, settings?.agentCoreProfileId, settings?.agentCoreSelectionId, settings?.model, props.chinese]);
  useEffect(() => {
    generation.current += 1;
    pending.current = false;
    setState("idle");
    return () => { generation.current += 1; };
  }, [identity]);
  const label = state === "busy" ? (props.chinese ? "正在解析" : "Interpreting")
    : state === "done" ? (props.chinese ? "已解析" : "Interpreted")
      : state === "error" ? (props.chinese ? "解析失败，检查资产与模型后重试" : "Interpretation failed; check the asset and model, then retry")
        : props.chinese ? "解析" : "Interpret";
  const run = async () => {
    if (!settings || !auth?.account || pending.current) return;
    pending.current = true;
    const current = generation.current;
    setState("busy");
    try {
      await interpretAgentCoreAsset({
        edition: props.edition, accountId: auth.account.id, locale: props.chinese ? "zh-CN" : "en-US",
        accessMode: settings.accessMode, provider: settings.accessMode === "platform" ? settings.managedProvider : settings.provider,
        model: settings.accessMode === "platform" ? settings.managedModel : settings.model,
        agentCoreProfileId: settings.agentCoreProfileId, agentCoreSelectionId: settings.agentCoreSelectionId,
        kind: props.kind, assetId: props.assetId, contentSha256: props.contentSha256,
      });
      if (current === generation.current) setState("done");
    } catch {
      if (current === generation.current) setState("error");
    } finally {
      if (current === generation.current) pending.current = false;
    }
  };
  return <button type="button" className="autonomy-repository-interpret" data-state={state}
    aria-label={`${label} ${props.name}`} title={`${label} ${props.name}`} aria-busy={state === "busy"}
    disabled={!settings || !auth?.account || !props.assetId || state === "busy"} onClick={() => void run()}>
    {state === "busy" ? <LoaderCircle aria-hidden="true" /> : state === "done" ? <Check aria-hidden="true" /> : <ScanSearch aria-hidden="true" />}
  </button>;
}
