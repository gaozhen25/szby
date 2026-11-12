export default function StepWizard({ steps, currentStep, onStepClick, completedSteps = [] }) {
  const denominator = Math.max(steps.length - 1, 1);
  const progress = Math.min(100, Math.max(0, (currentStep / denominator) * 100));

  return (
    <nav className="step-wizard" aria-label="创作进度">
      <div className="step-wizard-line-bg" aria-hidden="true">
        <span className="step-wizard-line-fill" style={{ "--progress": progress / 100 }} />
      </div>
      <div className="step-wizard-nodes">
        {steps.map((step, index) => {
          const isCurrent = index === currentStep;
          const isCompleted = completedSteps.includes(index) || index < currentStep;
          const isClickable = isCompleted || index <= currentStep;
          return (
            <button
              type="button"
              className={`step-wizard-node ${isCurrent ? "current" : ""} ${isCompleted ? "completed" : ""}`}
              disabled={!isClickable}
              aria-current={isCurrent ? "step" : undefined}
              key={step.id}
              onClick={() => isClickable && onStepClick?.(index)}
            >
              <span className="step-wizard-circle" aria-hidden="true">
                {isCompleted && !isCurrent ? "✓" : index + 1}
              </span>
              <span className="step-wizard-label">
                <strong>{step.label}</strong>
                {step.description ? <small>{step.description}</small> : null}
              </span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
