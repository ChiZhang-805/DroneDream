import { getAgentCoreStatus, restartAgentCore } from "../features/autonomy/agentCore";

export type AgentCoreStartupState = "checking" | "ready" | "failed";
let state: AgentCoreStartupState = "checking";
let pending: Promise<void> | null = null;
const listeners = new Set<() => void>();

export const getAgentCoreStartupState = () => state;
export function subscribeAgentCoreStartup(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
function publish(next: AgentCoreStartupState) {
  state = next;
  for (const listener of listeners) listener();
}

export function checkAgentCoreStartup(restart = false): Promise<void> {
  if (pending) return pending;
  publish("checking");
  pending = (async () => {
    try {
      let status = restart ? await restartAgentCore() : await getAgentCoreStatus();
      // Poll only while the native host owns an active startup operation.
      while (status.restarting) {
        await new Promise((resolve) => setTimeout(resolve, 250));
        status = await getAgentCoreStatus();
      }
      publish(status.available ? "ready" : "failed");
    } catch {
      publish("failed");
    }
  })().finally(() => { pending = null; });
  return pending;
}
