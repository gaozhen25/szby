export const IMAGE_STEPS = Object.freeze([
  { id: "reference", label: "素材参考", description: "上传或粘贴素材" },
  { id: "style", label: "风格选择", description: "选择标签" },
  { id: "prompt", label: "提示词输入", description: "输入提示词生成" },
]);

export const IMAGE_LINK_STEPS = Object.freeze([
  { id: "reference", label: "链接解析", description: "解析图文素材" },
  { id: "prompt_table", label: "提示词反推", description: "逐图编辑提示词" },
  { id: "generate_table", label: "生成图片", description: "逐图生成改写" },
]);

export const VIDEO_STEPS = Object.freeze([
  { id: "reference", label: "素材参考", description: "上传视频链接" },
  { id: "script", label: "脚本创作", description: "改写脚本" },
]);

export function getKimCreationSteps(flow) {
  if (flow === "image-link") return IMAGE_LINK_STEPS;
  if (flow === "video") return VIDEO_STEPS;
  return IMAGE_STEPS;
}
