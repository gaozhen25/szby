export const TAG_CATEGORY_UI_CONFIG = {
  purpose: { label: "功能标签", emoji: "❤️", color: "#FF4F9A", description: "产品功效与使用目的" },
  style: { label: "风格标签", emoji: "🎨", color: "#9B5CFF", description: "内容风格与视觉调性" },
  scene: { label: "场景标签", emoji: "🏙️", color: "#FF9D2E", description: "使用场景与拍摄环境" },
  quality: { label: "画质标签", emoji: "📷", color: "#22D3EE", description: "画面质量与表现效果" },
};

export const TAG_EMOJI_MAP = {
  cover: "🖼️", detail: "📋", product: "🛍️", poster: "📰", price: "💰",
  mirror_selfie: "🪞", daily_report: "📸", ui_screenshot: "💻", social_screenshot: "📱", livestream: "📡", character_poster: "🎭", character_daily: "👤",
  chinese_classical: "🏯", four_panel_comic: "🗯️", child_drawing: "🖍️", hand_drawn_infographic: "✏️", photography: "📷", handwritten_annotation: "✍️", doodle: "🎨", ugly_cute: "🤪",
  beauty_photo: "💄", beauty_retouch: "✨", product_white_bg: "⬜", food: "🍜",
  photo_restore: "🧑‍🔧", embroidery: "🧵", film_portrait: "🎞️",
  blurry_snap: "🌫️", back_view: "🔙", bedroom: "🛏️", rental_room: "🏠", elevator: "🛗", convenience_store: "🏪",
  gym: "🏋️", night_market: "🌃", park_bench: "🌳", subway: "🚇", workout_checkin: "💪", takeout: "🥡", snack_binge: "🍿", dog_walk: "🐕", reading_slack: "📖", gaming: "🎮", cooking_fail: "🍳", dawn_light: "🌅", desk_lamp: "💡", rainy_day: "🌧️", no_person: "🚫",
  afternoon_sun: "☀️", sunset: "🌇", cafe: "☕", office_desk: "🏢", fitting_room: "💃",
  "8k": "💎", "4k_photo": "💎", hd_render: "🌈", cinema: "🎞️",
};

const TAG_NAME_EMOJI_MAP = {
  "封面": "🖼️", "详情介绍": "📋", "产品介绍": "🛍️", "海报": "📰", "价格页": "💰", "对镜自拍": "🪞", "美食": "🍜", "日常报备": "📸", "UI界面": "💻", "截图": "📱", "直播": "📡", "人物海报": "🎭", "人设日常": "👤",
  "古风": "🏯", "四格漫画": "🗯️", "儿童手绘": "🖍️", "手绘科普": "✏️", "摄影": "📷", "手写标注": "✍️", "个性涂鸦": "🎨", "丑萌": "🤪", "美妆实拍": "💄", "产品白底图": "⬜", "人物修复": "🧑‍🔧", "刺绣": "🧵", "美颜": "✨", "胶片人像": "🎞️",
  "随手糊拍": "🌫️", "背影": "🔙", "卧室被窝": "🛏️", "出租屋": "🏠", "电梯间": "🛗", "便利店": "🏪", "咖啡店": "☕", "健身房": "🏋️", "办公室工位": "🏢", "夜市街头": "🌃", "公园长椅": "🌳", "地铁车厢": "🚇", "健身打卡": "💪", "外卖干饭": "🥡", "追剧零食": "🍿", "遛狗遛弯": "🐕", "看书摸鱼": "📖", "打游戏": "🎮", "做饭翻车": "🍳", "逛街试衣": "💃", "清晨微光": "🌅", "午后阳光": "☀️", "黄昏日落": "🌇", "深夜台灯": "💡", "阴雨天": "🌧️", "真实没有人": "🚫",
  "8K超清": "💎", "4K摄影": "💎", "高清渲染": "🌈", "电影画质": "🎞️",
};

export const getTagEmoji = (tag) => tag?.emoji || TAG_EMOJI_MAP[tag?.id] || TAG_NAME_EMOJI_MAP[tag?.name] || "";
