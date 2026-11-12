const cleanVariant = (variant = {}, fallbackIndex = 0) => ({
  ...variant,
  variantId: variant.variantId || `${variant.url || "variant"}_${fallbackIndex}`,
  variantIndex: Number.isFinite(variant.variantIndex) ? variant.variantIndex : fallbackIndex,
  url: variant.url || "",
});

export function buildGenerationSlots({
  files = [],
  imagePreviews = [],
  linkReferenceImages = [],
  count = "same",
  fallbackCount = 1,
}) {
  const uploadSlots = files.map((file, index) => ({
    slotId: `upload_${index + 1}`,
    sourceType: "upload",
    sourceUrl: imagePreviews[index] || "",
    sourcePrompt: "",
    fileName: file.name || `upload-${index + 1}`,
  }));
  const linkSlots = linkReferenceImages.map((image, index) => ({
    slotId: `link_${index + 1}`,
    sourceType: "link_reference",
    sourceUrl: image.url || "",
    sourcePrompt: image.analysis || image.prompt || "",
  }));
  const referenceSlots = [...uploadSlots, ...linkSlots];
  if (referenceSlots.length) return referenceSlots;
  const manualCount = count === "same" ? fallbackCount : Number(count || fallbackCount);
  return Array.from({ length: Math.max(1, manualCount) }, (_, index) => ({
    slotId: `manual_${index + 1}`,
    sourceType: "manual",
    sourceUrl: "",
    sourcePrompt: "",
  }));
}

export function normalizeImageGroups(job) {
  const groups = Array.isArray(job?.resultPayload?.imageGroups) ? job.resultPayload.imageGroups : [];
  if (groups.length) {
    return groups.map((group) => ({
      slotId: group.slotId || "",
      sourceType: group.sourceType || "manual",
      sourceUrl: group.sourceUrl || "",
      sourcePrompt: group.sourcePrompt || "",
      refinement: group.refinement || "",
      variants: (group.variants || []).map(cleanVariant),
    }));
  }
  const images = Array.isArray(job?.resultPayload?.images) ? job.resultPayload.images : [];
  return images
    .map((image) => (typeof image === "string" ? { url: image } : image))
    .filter((image) => image?.url)
    .map((image, index) => ({
      slotId: image.slotId || `legacy_${index + 1}`,
      sourceType: "manual",
      sourceUrl: "",
      sourcePrompt: "",
      refinement: "",
      variants: [cleanVariant(image, 0)],
    }));
}

export function mergeImageGroups(currentGroups, incomingGroups) {
  const incomingBySlot = new Map(incomingGroups.map((group) => [group.slotId, group]));
  let changed = false;
  const merged = currentGroups.map((group) => {
    const incoming = incomingBySlot.get(group.slotId);
    if (!incoming) return group;

    let groupChanged = false;
    const variants = [...(group.variants || [])];
    const variantIndexes = new Map(
      variants.map((variant, index) => [variant.variantId || variant.url, index]),
    );
    (incoming.variants || []).forEach((variant) => {
      const key = variant.variantId || variant.url;
      const existingIndex = variantIndexes.get(key);
      if (existingIndex === undefined) {
        variantIndexes.set(key, variants.length);
        variants.push(variant);
        groupChanged = true;
        return;
      }
      const existing = variants[existingIndex];
      if (JSON.stringify(existing) !== JSON.stringify(variant)) {
        variants[existingIndex] = variant;
        groupChanged = true;
      }
    });

    const nextGroup = { ...group, ...incoming, variants };
    const groupMetadataChanged = Object.keys(nextGroup).some(
      (key) => key !== "variants" && JSON.stringify(nextGroup[key]) !== JSON.stringify(group[key]),
    );
    if (!groupChanged && !groupMetadataChanged) return group;
    changed = true;
    return nextGroup;
  });
  const existing = new Set(merged.map((group) => group.slotId));
  incomingGroups.forEach((group) => {
    if (!existing.has(group.slotId)) {
      merged.push(group);
      changed = true;
    }
  });
  return changed ? merged : currentGroups;
}

export function getSelectedVariantAssets(imageGroups, selectedVariants) {
  return imageGroups.flatMap((group) => {
    const selectedId = selectedVariants[group.slotId];
    const variant = (group.variants || []).find((item) => item.variantId === selectedId);
    return variant ? [{ ...variant, slotId: group.slotId }] : [];
  });
}

export function buildImagePublishMediaCandidates(imageGroups, selectedVariants) {
  return getSelectedVariantAssets(imageGroups, selectedVariants)
    .filter((asset) => asset?.url)
    .map((asset, index) => ({
      url: asset.url,
      kind: "image",
      label: `生成图片 ${index + 1}`,
    }));
}

export function selectFirstVariants(imageGroups, currentSelections = {}) {
  const next = imageGroups.reduce((selections, group) => {
    const currentVariantId = currentSelections[group.slotId];
    const currentVariantStillExists = (group.variants || []).some(
      (variant) => variant.variantId === currentVariantId,
    );
    selections[group.slotId] = currentVariantStillExists
      ? currentVariantId
      : group.variants?.[0]?.variantId || "";
    return selections;
  }, {});
  const unchanged = Object.keys(next).length === Object.keys(currentSelections).length
    && Object.entries(next).every(([slotId, variantId]) => currentSelections[slotId] === variantId);
  return unchanged ? currentSelections : next;
}
