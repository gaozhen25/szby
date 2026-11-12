import TagSelectionPanel from "../TagSelectionPanel";
import PromptTemplateShelf from "./PromptTemplateShelf";

export default function KimTagSelectionStep({ categories, selectedTagIds, templates, activeTemplateId, onApplyTemplate, onToggle, onCreateTag, onClear, onBack, onSkip, onNext }) {
  return <div className="wizard-step-content">
    <div className="wizard-step-nav">
      <button className="btn btn-sm" type="button" onClick={onBack}>← 更换素材</button>
    </div>
    <TagSelectionPanel
      categories={categories}
      selectedTagIds={selectedTagIds}
      onToggle={onToggle}
      onCreateTag={onCreateTag}
      onClear={onClear}
      onSkip={onSkip}
      onNext={onNext}
      afterCategories={<PromptTemplateShelf templates={templates} activeTemplateId={activeTemplateId} onApply={onApplyTemplate} />}
    />
  </div>;
}
