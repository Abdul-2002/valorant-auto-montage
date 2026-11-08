import { PIPELINE_STEPS, pipelineIndex } from "./jobProgress";

type Props = {
  resumePath: string;
  hasOutputs?: boolean;
};

export function PipelineSteps({ resumePath, hasOutputs }: Props) {
  const current = hasOutputs ? PIPELINE_STEPS.length : pipelineIndex(resumePath);
  return (
    <ol className="pipeline-steps" aria-label="Pipeline stages">
      {PIPELINE_STEPS.map((step, index) => {
        let state = "todo";
        if (hasOutputs || index < current) state = "done";
        else if (index === current) state = "current";
        return (
          <li key={step.id} className={`pipeline-step pipeline-step-${state}`}>
            <span className="pipeline-dot" />
            <span className="pipeline-label">{step.label}</span>
          </li>
        );
      })}
    </ol>
  );
}
