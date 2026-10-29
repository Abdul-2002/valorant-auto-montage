import { getHighlights, getOutput, getStatus } from "../../api/montage";
import type { Highlight, Layout, WatchKind } from "../../api/types";
import { failureText, phaseText, TERMINAL_STATES } from "./text";

type Stop = { current: boolean };

type Handlers = {
  stop: Stop;
  kind: WatchKind;
  detectId: string;
  layout: Layout;
  schedule: () => void;
  onPhase: (text: string) => void;
  onFailed: (message: string) => void;
  onHighlights: (items: Highlight[]) => void;
  onOutput: (path: string) => void;
  onFinished: () => void;
};

export async function pollTask(taskId: string, handlers: Handlers): Promise<void> {
  const status = await getStatus(taskId);
  if (handlers.stop.current) return;
  handlers.onPhase(phaseText(status.state, status.phase));
  if (!TERMINAL_STATES.has(status.state)) {
    handlers.schedule();
    return;
  }
  if (status.state !== "SUCCESS") {
    handlers.onFailed(failureText(status.state));
    handlers.onFinished();
    return;
  }
  await applySuccess(handlers);
  if (!handlers.stop.current) handlers.onFinished();
}

async function applySuccess(handlers: Handlers): Promise<void> {
  if (handlers.stop.current || !handlers.detectId) return;
  if (handlers.kind === "detect") {
    const body = await getHighlights(handlers.detectId);
    if (!handlers.stop.current) handlers.onHighlights(body.highlights);
    return;
  }
  const body = await getOutput(handlers.detectId, handlers.layout);
  if (!handlers.stop.current) handlers.onOutput(body.path);
}
