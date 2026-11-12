export const TAG_CATEGORIES = [
  {
    id: "purpose",
    name: "作用标签",
    description: "决定图片的用途和结构",
    tags: [
      { id: "cover", name: "封面", prompt: "生成小红书竖版9:16商业宣传海报，整体简洁大气极简轻奢风，低饱和柔和配色，干净纯色背景；画面构图：人物居中放置，半身人像，人物侧对镜头/背影，完全不露出完整正脸；画面分区细节：画面四周分布圆角标签框作为卖点展示区，标签悬浮不遮挡主体人物，标签大小统一、排版均匀；文字规范：全部卖点文字放入独立标签内，无大面积段落文字，字体纤细高级，标题醒目，小字辅助说明，文字无扭曲错乱；光影：柔和均匀室内漫射光，无硬阴影，画面干净通透；画质：8K高清商业摄影质感，边缘干净无杂色，无水印、无多余涂鸦" },
      { id: "detail", name: "详情介绍", prompt: "生成小红书9:16竖版科普宣传海报，简约高级商务风，低对比度干净底色；画面构图：左右或上下二分布局，一侧实景素材图，一侧文字信息区，图文占比均衡；文字规范：短句分行展示，大标题加粗突出，配套小字辅助，文字层级清晰，字体统一简约；光影：平面均匀柔光，无强烈明暗对比；画质：高清商用海报质感，元素边缘清晰，背景纯色无噪点" },
      { id: "product", name: "产品介绍", prompt: "多张同类产品图片去背景后拼贴在同一画布上，错落有致但整齐排列；白底/浅色底干净背景，信息标注风，菜单/图鉴质感；每张图配简短文字标注，字体统一，标注线清晰；网格布局/自由错落布局，图片大小有层次；统一明亮色调，竖版9:16，去背景干净无白边" },
      { id: "poster", name: "海报", prompt: "生成9:16竖版卖点信息海报，简约商务质感，纯色浅底色；顶部超大概括性主标题居中，下方分点编号展示卖点，从上至下纵向排布；标题粗体醒目，正文纤细规整，分行简短描述；平面柔和灯光，整体干净清爽；高清平面设计图，无模糊、无文字扭曲" },
      { id: "price", name: "价格页", prompt: "生成小红书9:16竖版促销价格海报，活力吸睛商业广告风，高对比柔和配色；画面视觉重心放置超大价格数字，主体素材居中辅助衬托；顶部品牌名称，中部突出价格套餐，下方配套服务权益短句；价格字号为画面最大，加粗醒目；明亮通透柔光，高清商业海报质感" },
      { id: "mirror_selfie", name: "对镜自拍", prompt: "人物站在镜子前举手机自拍，手机遮挡住脸部，不露脸；第一人称对镜视角，镜子中反射出人物全身/半身；生活化场景（电梯/卫生间/卧室/试衣间），真实日常感；iPhone手机随手拍质感，画质中等不过于高清，轻微噪点，真实感强；自然室内光/暖黄灯光，色调真实，竖版9:16" },
      { id: "food", name: "美食", prompt: "iPhone室内随手拍摄美食图，4:3方形生活化实拍，治愈日常纪实风；随性俯拍/45°侧拍，随意摆放餐具，不刻意规整摆盘；普通居家餐桌环境，室内无明显时间光线；室内柔和顶光，无浓重阴影，轻微画面模糊虚化；原生手机拍摄质感，无美食商业精修滤镜" },
      { id: "daily_report", name: "日常报备", prompt: "生成这个人随手拍的照片，注意是用iphone随意拍的，注意必须是真实的，看起来非常真，看起来是手机拍的" },
      { id: "ui_screenshot", name: "UI界面", prompt: "高保真UI截图，信息层级清晰，留白充足，文字清晰可读" },
      { id: "social_screenshot", name: "截图", prompt: "生成一张社交平台内容截图，手机截图风格，文字必须准确显示指定的中文，禁止乱码和占位文本" },
      { id: "livestream", name: "直播", prompt: "生成一张直播界面截图，UI叠加层完整，文字清晰可读，弹幕内容合理，界面元素不遮挡主播面部" },
      { id: "character_poster", name: "人物海报", prompt: "生成一张水墨双重曝光人物海报，9:16竖版，高级电影海报构图；东方水墨美学+写实电影感，克制、高级、留白充足，层次丰富但不杂乱" },
      { id: "character_daily", name: "人设日常", prompt: "iPhone 13/14手机随手拍摄质感，绝对不能是专业相机画质；画面轻微模糊、对焦不完美，有真实手持拍摄的抖动感；皮肤保留真实质感；光线自然不完美；环境有生活痕迹；色彩偏真实原生，无过度滤镜；构图随意不刻意；有轻微噪点、有镜头畸变" },
    ],
  },
  {
    id: "style",
    name: "风格标签",
    description: "决定图片的美术风格",
    tags: [
      { id: "chinese_classical", name: "古风", prompt: "古风题材画面，美术风格：工笔/写意/影视写实，东方美学，历史氛围准确" },
      { id: "four_panel_comic", name: "四格漫画", prompt: "色彩丰富的漫画风格，加入幽默元素，四格漫画排版" },
      { id: "child_drawing", name: "儿童手绘", prompt: "就像一个开朗的6岁孩子在白色笔记本纸上画的那样，使用粗蜡笔笔触、摇晃的轮廓和简单的扁平形状，颜色明亮大胆，略微超出线条" },
      { id: "hand_drawn_infographic", name: "手绘科普", prompt: "9:16竖屏比例的手绘风格信息图卡片，米色背景带纸张纹理，简洁友好的手绘美学，毛笔草书字体，红黑交替" },
      { id: "photography", name: "摄影", prompt: "超现实、高分辨率的照片，皮肤完美光滑，眼睛细节丰富，光线自然，专业影棚布光，电影级画质，超细节，4K" },
      { id: "handwritten_annotation", name: "手写标注", prompt: "手机拍摄质感照片，画面中添加手绘标注，白色画笔绘制的纤细手绘线条，英文手写体文字，Instagram快拍风格" },
      { id: "doodle", name: "个性涂鸦", prompt: "图生图，完全保留人物相似度，个性涂鸦艺术风格，手绘质感" },
      { id: "ugly_cute", name: "丑萌", prompt: "稚气未脱、笔触粗糙的数字涂鸦肖像，纯浅灰色背景，刻意追求凌乱、业余、像小孩子涂鸦般的质感，迷人的丑萌感" },
      { id: "beauty_photo", name: "美妆实拍", prompt: "高端编辑工作室照片，逼真的材质和自然的纹理，3D写实、奢华产品摄影、浅景深" },
      { id: "product_white_bg", name: "产品白底图", prompt: "产品精修，置于纯净的纯白背景上，正视图，平视视角，3D渲染，精修，颜色通透感，自然柔和光影，高级商业摄影" },
      { id: "photo_restore", name: "人物修复", prompt: "将照片恢复并增强到专业肖像质量，修复划痕、褶皱、污渍、变色和缺失的细节，保留自然面部特征" },
      { id: "embroidery", name: "刺绣", prompt: "超精细的手工刺绣艺术品，逼真的缎面绣、长短针绣和密实的填充绣，可见的绣线、精确针迹方向，博物馆级纺织工艺" },
      { id: "beauty_retouch", name: "美颜", prompt: "对人像进行修饰，肤色白皙细腻，无痘无瑕，肤质光滑紧致，眼眸明亮有神，面部轮廓自然，保持自然真实感" },
      { id: "film_portrait", name: "胶片人像", prompt: "经典35mm胶片人像摄影作品，焦点在人物自然肤质与真实发丝细节，伦勃朗光或窗口侧光，富士400H或柯达Portra 400胶片色调，低对比度奶油感中间调" },
    ],
  },
  {
    id: "scene",
    name: "场景标签",
    description: "决定图片的环境和氛围",
    tags: [
      { id: "blurry_snap", name: "随手糊拍", prompt: "没对焦好、有点糊、真实抓拍感，画面整体偏模糊，对焦不准，有运动模糊，像随手一拍没拍清楚的感觉" },
      { id: "back_view", name: "背影", prompt: "只拍背影/后脑勺、氛围感，完全不露面，只拍背影和后脑勺，头发和身形是重点，配合环境营造氛围感" },
      { id: "bedroom", name: "卧室被窝", prompt: "床上、枕头、被子、居家感，普通卧室环境，床单有点乱，床头有手机和水杯，真实的年轻人卧室样子" },
      { id: "rental_room", name: "出租屋", prompt: "普通年轻人租房、有点乱但真实，空间不大，家具简单，地上有鞋子，桌上有杂物，有生活气息的出租屋环境" },
      { id: "elevator", name: "电梯间", prompt: "电梯镜子、金属质感、对镜拍场景，不锈钢电梯内壁，有楼层按钮和镜子，灯光偏冷白" },
      { id: "convenience_store", name: "便利店", prompt: "711/全家风格、冷柜、便当，明亮的便利店灯光，货架上有零食饮料，冷柜里有饭团三明治" },
      { id: "cafe", name: "咖啡店", prompt: "木质桌椅、咖啡杯、暖光，温馨的咖啡店环境，桌上有拿铁和甜点，暖黄色调，氛围感强的咖啡馆场景" },
      { id: "gym", name: "健身房", prompt: "器械、镜子、运动装备，健身房环境，有哑铃、跑步机、力量器械，墙上有大镜子，地面是橡胶地" },
      { id: "office_desk", name: "办公室工位", prompt: "电脑、键盘、加班灯、工位杂物，普通办公室格子间，桌上有显示器、键盘、鼠标、水杯、文件，真实打工人工位" },
      { id: "night_market", name: "夜市街头", prompt: "霓虹灯、小吃摊、人群、烟火气，夜晚的夜市街道，各种小吃摊位，五颜六色的霓虹灯牌，充满烟火气" },
      { id: "park_bench", name: "公园长椅", prompt: "树影、草地、夕阳、放空，公园环境，木质长椅，周围有树木和草坪，阳光透过树叶洒下光斑" },
      { id: "subway", name: "地铁车厢", prompt: "扶手、车窗、通勤人群，地铁车厢内，有金属扶手和拉环，车窗映着人影，典型的城市地铁通勤场景" },
      { id: "workout_checkin", name: "健身打卡", prompt: "运动后、出汗、瑜伽垫/哑铃，刚运动完的状态，头发微湿，脸上有汗珠，穿着运动服" },
      { id: "takeout", name: "外卖干饭", prompt: "塑料餐盒、筷子、一人食，打开的外卖餐盒，旁边有一次性筷子和汤勺，一个人吃外卖的场景" },
      { id: "snack_binge", name: "追剧零食", prompt: "平板/电视、薯片奶茶、窝着看，窝在沙发或床上，面前放着零食和饮料，屏幕亮着在播放剧集" },
      { id: "dog_walk", name: "遛狗遛弯", prompt: "牵狗绳、小区/公园、傍晚，手里牵着狗绳，狗狗在旁边，在小区或公园散步，傍晚时分的遛狗日常" },
      { id: "reading_slack", name: "看书摸鱼", prompt: "书/Kindle、咖啡、假装学习，面前摊开一本书或放着Kindle，旁边有咖啡，但人在走神或玩手机" },
      { id: "gaming", name: "打游戏", prompt: "手柄/键盘、屏幕光、专注脸，手里握着游戏手柄或放在键盘上，脸被屏幕光照亮，表情专注投入" },
      { id: "cooking_fail", name: "做饭翻车", prompt: "厨房、有点乱、成品一般，厨房台面上有点乱，锅碗瓢盆没收拾，做出来的卖相一般甚至有点黑暗料理" },
      { id: "fitting_room", name: "逛街试衣", prompt: "试衣间镜子、新衣服、纠结，服装店试衣间里，站在镜子前试穿新衣服，表情纠结在犹豫买不买" },
      { id: "dawn_light", name: "清晨微光", prompt: "天刚亮、窗帘透进来的光，清晨时分，光线柔和偏冷，从窗帘缝隙透进来，朦朦胧胧的清晨氛围" },
      { id: "afternoon_sun", name: "午后阳光", prompt: "阳光洒进来、暖金色、影子长，下午的阳光透过窗户洒进来，形成温暖的金色光斑，暖洋洋的午后氛围" },
      { id: "sunset", name: "黄昏日落", prompt: "橙红色天空、逆光、剪影，黄昏时分，天空是橙红色渐变，逆光拍摄形成剪影效果，温暖又伤感的日落氛围" },
      { id: "desk_lamp", name: "深夜台灯", prompt: "只有一盏灯亮、周围暗、孤独感，深夜环境，只有桌上的一盏台灯亮着，周围都是暗的，孤独的深夜氛围" },
      { id: "rainy_day", name: "阴雨天", prompt: "窗外下雨、室内暗、湿漉漉，阴天或者下雨，窗外灰蒙蒙的，能看到雨丝，室内光线偏暗偏冷" },
      { id: "no_person", name: "真实没有人", prompt: "手机原相机随手拍，无人物，自然光真实光影，普通路人第一视角，构图随意不刻意，轻微手机原生噪点，无美颜无滤镜，自然原生色调" },
    ],
  },
  {
    id: "quality",
    name: "画质标签",
    description: "控制图片的画质和渲染风格",
    tags: [
      { id: "8k", name: "8K超清", prompt: "8K ultra HD, extremely detailed, high resolution" },
      { id: "4k_photo", name: "4K摄影", prompt: "4K photography, professional camera quality, sharp details" },
      { id: "hd_render", name: "高清渲染", prompt: "high definition render, clean edges, no artifacts" },
      { id: "cinema", name: "电影画质", prompt: "cinematic quality, film grain, color grading, depth of field" },
    ],
  },
];

export function getAllTags() {
  return TAG_CATEGORIES.flatMap((cat) =>
    cat.tags.map((tag) => ({ ...tag, category: cat.id, categoryName: cat.name }))
  );
}

export function getTagById(tagId) {
  for (const cat of TAG_CATEGORIES) {
    const found = cat.tags.find((t) => t.id === tagId);
    if (found) return { ...found, category: cat.id, categoryName: cat.name };
  }
  return null;
}

export function buildPromptFromTags(selectedTagIds, userPrompt) {
  const tags = selectedTagIds.map(getTagById).filter(Boolean);
  const tagPrompts = tags.map((t) => t.prompt);
  const qualityTags = tags.filter((t) => t.category === "quality").map((t) => t.prompt);
  const otherTags = tags.filter((t) => t.category !== "quality").map((t) => t.prompt);

  const parts = [];
  if (userPrompt?.trim()) parts.push(userPrompt.trim());
  if (otherTags.length) parts.push(otherTags.join(", "));
  if (qualityTags.length) parts.push(qualityTags.join(", "));
  return parts.join(", ");
}
