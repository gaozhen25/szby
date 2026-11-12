import { useCallback, useState } from "react";

import { DEFAULT_IMAGE_RATIO } from "../utils/imageAspectRatio.js";
import { reindexPromptCards } from "../utils/imagePromptPlan";

const preferencesFromPlan = (plan, previous = {}) => ({
  ...previous,
  targetPlatform: plan.targetPlatform,
  imageCount: plan.cards.length,
  collectionMode: plan.collectionMode,
  ratio: plan.ratio,
  creativityLevel: plan.creativityLevel,
  visualStyle: plan.visualStyle,
  customRequirements: plan.customRequirements,
});

export default function useImagePromptPlanEditor({
  initialPlan = null,
  initialPreferences = null,
  onSinglePromptChange,
  onNegativePromptChange,
  onPublishCopyChange,
  onHashtagsChange,
  onCountChange,
  onRatioChange,
  onCreativityChange,
}) {
  const [imagePromptPlan, setImagePromptPlan] = useState(initialPlan);
  const [imageCreationPreferences, setImageCreationPreferences] = useState(initialPreferences);

  const commitImagePromptPlan = useCallback((nextPlan) => {
    if (!nextPlan) return;
    const normalized = { ...nextPlan, imageCount: nextPlan.cards.length };
    setImagePromptPlan(normalized);
    setImageCreationPreferences((current) => preferencesFromPlan(normalized, current || {}));
    onCountChange(normalized.cards.length);
    if (normalized.cards.length === 1) onSinglePromptChange(normalized.cards[0].prompt);
  }, [onCountChange, onSinglePromptChange]);

  const applyImagePromptPlan = useCallback((nextPlan) => {
    commitImagePromptPlan(nextPlan);
    onRatioChange(nextPlan.ratio);
    onCreativityChange(nextPlan.creativityLevel);
    onNegativePromptChange(nextPlan.negativePrompt);
    onPublishCopyChange(nextPlan.publishCopy);
    onHashtagsChange(nextPlan.hashtags);
  }, [commitImagePromptPlan, onCreativityChange, onHashtagsChange, onNegativePromptChange, onPublishCopyChange, onRatioChange]);

  const restoreImagePromptPlan = useCallback((plan, preferences) => {
    setImagePromptPlan(plan);
    setImageCreationPreferences(preferences);
    onCountChange(plan?.cards?.length || preferences?.imageCount || 1);
    onRatioChange(plan?.ratio || preferences?.ratio || DEFAULT_IMAGE_RATIO);
    onCreativityChange(plan?.creativityLevel || preferences?.creativityLevel || "中");
    onNegativePromptChange(plan?.negativePrompt || "");
    if (plan) {
      onPublishCopyChange(plan.publishCopy || "");
      onHashtagsChange(plan.hashtags || []);
      if (plan.cards?.length === 1) onSinglePromptChange(plan.cards[0].prompt || "");
    }
  }, [onCountChange, onCreativityChange, onHashtagsChange, onNegativePromptChange, onPublishCopyChange, onRatioChange, onSinglePromptChange]);

  const clearImagePromptPlan = useCallback(() => {
    setImagePromptPlan(null);
  }, []);

  const changeImagePromptPlanField = useCallback((field, value) => {
    if (!imagePromptPlan) return;
    commitImagePromptPlan({ ...imagePromptPlan, [field]: value });
    if (field === "negativePrompt") onNegativePromptChange(value);
    if (field === "publishCopy") onPublishCopyChange(value);
    if (field === "hashtags") onHashtagsChange(value);
  }, [commitImagePromptPlan, imagePromptPlan, onHashtagsChange, onNegativePromptChange, onPublishCopyChange]);

  const changeImageRatio = useCallback((value) => {
    onRatioChange(value);
    setImageCreationPreferences((current) => current ? { ...current, ratio: value } : current);
    setImagePromptPlan((current) => current ? { ...current, ratio: value } : current);
  }, [onRatioChange]);

  const changeImageCreativityLevel = useCallback((value) => {
    onCreativityChange(value);
    setImageCreationPreferences((current) => current ? { ...current, creativityLevel: value } : current);
    setImagePromptPlan((current) => current ? { ...current, creativityLevel: value } : current);
  }, [onCreativityChange]);

  const changeImagePromptCard = useCallback((index, field, value) => {
    if (!imagePromptPlan) return;
    const cards = imagePromptPlan.cards.map((card, cardIndex) => cardIndex === index ? { ...card, [field]: value } : card);
    commitImagePromptPlan({ ...imagePromptPlan, cards });
  }, [commitImagePromptPlan, imagePromptPlan]);

  const moveImagePromptCard = useCallback((fromIndex, toIndex) => {
    if (!imagePromptPlan || toIndex < 0 || toIndex >= imagePromptPlan.cards.length) return;
    const cards = [...imagePromptPlan.cards];
    const [moved] = cards.splice(fromIndex, 1);
    cards.splice(toIndex, 0, moved);
    commitImagePromptPlan({ ...imagePromptPlan, ...reindexPromptCards(cards, imagePromptPlan.collectionMode) });
  }, [commitImagePromptPlan, imagePromptPlan]);

  const removeImagePromptCard = useCallback((index) => {
    if (!imagePromptPlan || imagePromptPlan.cards.length <= 1) return;
    const indexed = reindexPromptCards(imagePromptPlan.cards.filter((_, cardIndex) => cardIndex !== index), imagePromptPlan.collectionMode);
    commitImagePromptPlan({
      ...imagePromptPlan,
      ...indexed,
      sharedStyle: indexed.collectionMode === "series" ? imagePromptPlan.sharedStyle : "",
    });
  }, [commitImagePromptPlan, imagePromptPlan]);

  const addImagePromptCard = useCallback(() => {
    if (!imagePromptPlan || imagePromptPlan.cards.length >= 4) return;
    const usedIds = new Set(imagePromptPlan.cards.map((card) => card.slotId));
    let suffix = 1;
    while (usedIds.has(`topic_${suffix}`)) suffix += 1;
    const indexed = reindexPromptCards([
      ...imagePromptPlan.cards,
      { slotId: `topic_${suffix}`, role: "standalone", title: `图片 ${imagePromptPlan.cards.length + 1}`, prompt: "" },
    ], imagePromptPlan.collectionMode);
    commitImagePromptPlan({ ...imagePromptPlan, ...indexed });
  }, [commitImagePromptPlan, imagePromptPlan]);

  return {
    imagePromptPlan,
    imageCreationPreferences,
    applyImagePromptPlan,
    restoreImagePromptPlan,
    clearImagePromptPlan,
    changeImagePromptPlanField,
    changeImageRatio,
    changeImageCreativityLevel,
    changeImagePromptCard,
    moveImagePromptCard,
    removeImagePromptCard,
    addImagePromptCard,
  };
}
