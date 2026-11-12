export default function KimStepWizard({ steps, currentStep, onStepClick, completedSteps = [] }) {
  return (
    <nav className="step-wizard" aria-label="创作进度">
      <ol className="step-wizard-nodes">
        {steps.map((step, index) => {
          const isCompleted = completedSteps.includes(index) || index < currentStep;
          const isCurrent = index === currentStep;
          const isClickable = isCompleted || index <= currentStep;
          const connectorDone = index > 0 && index <= currentStep;

          return (
            <li className="step-wizard-item" key={step.id}>
              {index > 0 ? (
                <span
                  className={`step-wizard-connector ${connectorDone ? "is-done" : ""}`}
                  aria-hidden="true"
                />
              ) : null}
              <button
                type="button"
                className={`step-wizard-node ${isCurrent ? "current" : ""} ${isCompleted ? "completed" : ""} ${isClickable ? "clickable" : ""}`}
                onClick={() => isClickable && onStepClick?.(index)}
                disabled={!isClickable}
                aria-current={isCurrent ? "step" : undefined}
                title={step.description || step.label}
              >
                <span className="step-wizard-circle" aria-hidden="true">
                  {isCompleted && !isCurrent ? (
                    <span className="step-check">✓</span>
                  ) : (
                    <span className="step-number">{index + 1}</span>
                  )}
                </span>
                <span className="step-wizard-label">
                  <span className="step-wizard-title">{step.label}</span>
                  {step.description ? <span className="step-wizard-desc">{step.description}</span> : null}
                </span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
