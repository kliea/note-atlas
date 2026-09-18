import type { PillState } from "../types";

type StatusPillsProps = {
  backend: PillState;
  model: PillState;
  modelName: string | null;
};

function labelFor(kind: "backend" | "model", state: PillState): string {
  if (kind === "backend") {
    if (state === "loading") return "checking";
    if (state === "ok") return "ok";
    return "down";
  }
  if (state === "loading") return "checking";
  if (state === "ok") return "reachable";
  return "unreachable";
}

export function StatusPills({ backend, model, modelName }: StatusPillsProps) {
  return (
    <div className="pills" role="status" aria-live="polite">
      <span className={`pill pill-${backend}`}>
        backend = {labelFor("backend", backend)}
      </span>
      <span className={`pill pill-${model}`} title={modelName ?? undefined}>
        model = {labelFor("model", model)}
      </span>
    </div>
  );
}
