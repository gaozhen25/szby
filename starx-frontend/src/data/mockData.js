import { DEFAULT_IMAGE_RATIO } from "../utils/imageAspectRatio.js";

// Mock data for image generation module - all interactive

const MOCK_IMAGE_URLS = [
  "https://picsum.photos/seed/ai1/512/680",
  "https://picsum.photos/seed/ai2/512/680",
  "https://picsum.photos/seed/ai3/512/680",
  "https://picsum.photos/seed/ai4/512/680",
  "https://picsum.photos/seed/ai5/512/680",
  "https://picsum.photos/seed/ai6/512/680",
  "https://picsum.photos/seed/ai7/512/680",
  "https://picsum.photos/seed/ai8/512/680",
  "https://picsum.photos/seed/ai9/512/680",
  "https://picsum.photos/seed/ai10/512/680",
  "https://picsum.photos/seed/ai11/512/680",
  "https://picsum.photos/seed/ai12/512/680",
];

const MOCK_THUMB_URLS = [
  "https://picsum.photos/seed/t1/200/200",
  "https://picsum.photos/seed/t2/200/200",
  "https://picsum.photos/seed/t3/200/200",
  "https://picsum.photos/seed/t4/200/200",
  "https://picsum.photos/seed/t5/200/200",
  "https://picsum.photos/seed/t6/200/200",
  "https://picsum.photos/seed/t7/200/200",
  "https://picsum.photos/seed/t8/200/200",
  "https://picsum.photos/seed/t9/200/200",
  "https://picsum.photos/seed/t10/200/200",
  "https://picsum.photos/seed/t11/200/200",
  "https://picsum.photos/seed/t12/200/200",
];

export const MOCK_MATERIAL_CATEGORIES = [
  { id: "all", name: "全部", icon: "📁", system: true },
  { id: "uncategorized", name: "未分类", icon: "📂", system: true },
  { id: "portrait", name: "人物", icon: "👤", system: true },
  { id: "landscape", name: "风景", icon: "🏔️", system: true },
  { id: "design", name: "设计素材", icon: "🎨", system: true },
];

export const MOCK_MATERIALS = [
  { id: "m1", name: "AI作品_封面_001", category: "portrait", tags: ["封面", "摄影"], date: "2026-06-28", thumb: MOCK_THUMB_URLS[0], imageUrl: MOCK_IMAGE_URLS[0], prompt: "少女站在花丛中，柔和光线，8K高清", ratio: DEFAULT_IMAGE_RATIO, isFavorite: true },
  { id: "m2", name: "AI作品_产品图_002", category: "design", tags: ["产品白底图", "商业"], date: "2026-06-27", thumb: MOCK_THUMB_URLS[1], imageUrl: MOCK_IMAGE_URLS[1], prompt: "护肤品白底产品图，3D渲染", ratio: "1:1", isFavorite: false },
  { id: "m3", name: "AI作品_美食_003", category: "uncategorized", tags: ["美食", "随手拍"], date: "2026-06-26", thumb: MOCK_THUMB_URLS[2], imageUrl: MOCK_IMAGE_URLS[2], prompt: "咖啡店桌面，拿铁和甜点", ratio: "1:1", isFavorite: true },
  { id: "m4", name: "AI作品_风景_004", category: "landscape", tags: ["黄昏日落", "风景"], date: "2026-06-25", thumb: MOCK_THUMB_URLS[3], imageUrl: MOCK_IMAGE_URLS[3], prompt: "海边黄昏日落，橙红色天空", ratio: "16:9", isFavorite: false },
  { id: "m5", name: "AI作品_人设_005", category: "portrait", tags: ["人设日常", "卧室被窝"], date: "2026-06-24", thumb: MOCK_THUMB_URLS[4], imageUrl: MOCK_IMAGE_URLS[4], prompt: "少女在卧室自拍，iPhone质感", ratio: DEFAULT_IMAGE_RATIO, isFavorite: false },
  { id: "m6", name: "AI作品_海报_006", category: "design", tags: ["海报", "手绘科普"], date: "2026-06-23", thumb: MOCK_THUMB_URLS[5], imageUrl: MOCK_IMAGE_URLS[5], prompt: "健康科普海报，手绘风格", ratio: "9:16", isFavorite: true },
];

export const MOCK_TEMPLATES = [
  {
    id: "tpl1",
    name: "小红书封面通用",
    description: "适用于小红书竖版封面图的通用模板",
    prompt: "小红书竖版封面，简约高级感",
    selectedTagIds: ["cover", "4k_photo", "afternoon_sun"],
    createdAt: "2026-06-20",
    useCount: 12,
  },
  {
    id: "tpl2",
    name: "美食随手拍",
    description: "iPhone质感的美食日常拍摄风格",
    prompt: "",
    selectedTagIds: ["food", "cafe", "blurry_snap"],
    createdAt: "2026-06-18",
    useCount: 8,
  },
  {
    id: "tpl3",
    name: "产品白底图",
    description: "电商产品白底精修图模板",
    prompt: "护肤品产品图",
    selectedTagIds: ["product_white_bg", "8k"],
    createdAt: "2026-06-15",
    useCount: 5,
  },
];

let _materialIdCounter = MOCK_MATERIALS.length + 1;
let _templateIdCounter = MOCK_TEMPLATES.length + 1;
let _jobIdCounter = 1;

export function generateMockImageGroups(prompt, count = 1) {
  const groups = [];
  for (let i = 0; i < count; i++) {
    const slotId = `gen_${Date.now()}_${i}`;
    const baseSeed = Math.floor(Math.random() * 1000);
    groups.push({
      slotId,
      sourceType: "manual",
      sourceUrl: "",
      sourcePrompt: prompt,
      refinement: "",
      variants: [
        {
          variantId: `${slotId}_main`,
          variantIndex: 0,
          url: `https://picsum.photos/seed/main${baseSeed}/512/680`,
        },
        {
          variantId: `${slotId}_a`,
          variantIndex: 1,
          url: `https://picsum.photos/seed/varA${baseSeed}/512/680`,
        },
        {
          variantId: `${slotId}_b`,
          variantIndex: 2,
          url: `https://picsum.photos/seed/varB${baseSeed}/512/680`,
        },
      ],
    });
  }
  return groups;
}

export function generateMockVariants(existingSlotId, seed) {
  const baseSeed = seed || Math.floor(Math.random() * 1000);
  return [
    {
      variantId: `${existingSlotId}_new_main`,
      variantIndex: 0,
      url: `https://picsum.photos/seed/re${baseSeed}/512/680`,
    },
    {
      variantId: `${existingSlotId}_new_a`,
      variantIndex: 1,
      url: `https://picsum.photos/seed/reA${baseSeed}/512/680`,
    },
    {
      variantId: `${existingSlotId}_new_b`,
      variantIndex: 2,
      url: `https://picsum.photos/seed/reB${baseSeed}/512/680`,
    },
  ];
}

export function createMockMaterial(data) {
  _materialIdCounter++;
  return {
    id: `m${_materialIdCounter}`,
    name: data.name || `AI作品_${new Date().toISOString().slice(0, 10)}_${_materialIdCounter}`,
    category: data.category || "uncategorized",
    tags: data.tags || [],
    date: new Date().toISOString().slice(0, 10),
    thumb: data.thumb || data.imageUrl || MOCK_THUMB_URLS[0],
    imageUrl: data.imageUrl || MOCK_IMAGE_URLS[0],
    prompt: data.prompt || "",
    ratio: data.ratio || DEFAULT_IMAGE_RATIO,
    isFavorite: false,
  };
}

export function createMockTemplate(data) {
  _templateIdCounter++;
  return {
    id: `tpl${_templateIdCounter}`,
    name: data.name || "新模板",
    description: data.description || "",
    prompt: data.prompt || "",
    selectedTagIds: data.selectedTagIds || [],
    createdAt: new Date().toISOString().slice(0, 10),
    useCount: 0,
  };
}

export function nextMockJobId() {
  return `mock_job_${Date.now()}_${_jobIdCounter++}`;
}

// Simulate reverse prompt from image
export function mockReversePrompt(imageDescription) {
  const prompts = [
    {
      positive: "一位年轻女性站在樱花树下，柔和的自然光线，微微侧身回眸，长发随风飘动，背景虚化，日系清新风格，8K高清摄影",
      negative: "低质量, 模糊, 变形, 多余肢体",
      styleTags: ["摄影", "午后阳光"],
      keyParams: { cfg: 7, steps: 30, sampler: "Euler a" },
    },
    {
      positive: "精致的咖啡拉花特写，木质桌面，暖黄色调，浅景深，Instagram风格美食摄影",
      negative: "低质量, 过曝, 噪点过多",
      styleTags: ["美食", "咖啡店"],
      keyParams: { cfg: 7.5, steps: 25, sampler: "DPM++ 2M" },
    },
    {
      positive: "极简风格产品展示，白色背景，护肤品瓶身3D渲染，柔和光影，商业广告质感",
      negative: "杂乱背景, 阴影过重, 文字扭曲",
      styleTags: ["产品白底图", "美妆实拍"],
      keyParams: { cfg: 8, steps: 35, sampler: "Euler a" },
    },
  ];
  return prompts[Math.floor(Math.random() * prompts.length)];
}

// Simulate link extraction
export function mockExtractLink(url) {
  const isXiaohongshu = url.includes("xiaohongshu") || url.includes("xhs");
  const isDouyin = url.includes("douyin") || url.includes("tiktok");
  const platform = isXiaohongshu ? "小红书" : isDouyin ? "抖音" : "未知平台";

  return {
    url,
    platform,
    type: isDouyin ? "视频" : "图文",
    title: "探索城市中的治愈系咖啡馆 ☕",
    description: "周末不知道去哪？推荐这家隐藏在巷子里的宝藏咖啡馆，氛围感拉满！环境超好出片，拿铁和提拉米苏绝配～ #咖啡馆 #周末去哪 #探店",
    hashtags: ["#咖啡馆", "#周末去哪", "#探店"],
    images: [
      { url: "https://picsum.photos/seed/extract1/600/800" },
      { url: "https://picsum.photos/seed/extract2/600/800" },
      { url: "https://picsum.photos/seed/extract3/600/800" },
    ],
    videos: isDouyin ? [{ url: "https://www.w3schools.com/html/mov_bbb.mp4" }] : [],
  };
}
