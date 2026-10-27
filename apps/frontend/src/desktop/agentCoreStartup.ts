import { getAgentCoreStatus, restartAgentCore } from "../features/autonomy/agentCore";

export type AgentCoreStartupState = "checking" | "ready";
let state: AgentCoreStartupState = "checking";
let pending: Promise<void> | null = null;
const listeners = new Set<() => void>();
const RETRY_DELAY_MS = 1_000;

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
    let shouldRestart = restart;
    for (;;) {
      try {
        let status = shouldRestart ? await restartAgentCore() : await getAgentCoreStatus();
        // Poll only while the native host owns an active startup operation.
        while (status.restarting) {
          await new Promise((resolve) => setTimeout(resolve, 250));
          status = await getAgentCoreStatus();
        }
        if (status.available) {
          publish("ready");
          return;
        }
      } catch {
        // Keep the launcher visible while the next native start attempt begins.
      }
      shouldRestart = true;
      await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS));
    }
  })().finally(() => { pending = null; });
  return pending;
}
