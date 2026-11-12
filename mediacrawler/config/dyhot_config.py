# -*- coding: utf-8 -*-
"""抖音热点宝（独立平台 dyhot）配置。"""

# 落盘目录：data/dyhot/
DY_HOTSPOT_DATA_DIR = "dyhot"

# Cookie 登录：--platform dyhot --lt cookie --cookies "从 douhot.douyin.com 复制的整段"
# 与浏览器抓包一致: {page_num, page_size: 10, date_window: 24, sub_type: 3001}
DY_HOTSPOT_SUB_TYPE = 3001
DY_HOTSPOT_DATE_WINDOW = 24
DY_HOTSPOT_PAGE_SIZE = 10
DY_HOTSPOT_MAX_COUNT = 20  # 只爬搜索热点总榜前 N 条

# 榜单完成后：按热词抖音搜索 + 评论 → 词云（已临时关闭）
DY_HOTSPOT_FOLLOW_SEARCH = False
# 跟搜关键词数：0=榜单全部
DY_HOTSPOT_SEARCH_TOP_N = 10
DY_HOTSPOT_SEARCH_NOTES_COUNT = 10
# 跟搜专用筛选（与普通 dy 搜索解耦）：最多点赞 + 一周内
DY_HOTSPOT_SEARCH_SORT_TYPE = 1  # 0综合 / 1最多点赞 / 2最新发布
DY_HOTSPOT_SEARCH_PUBLISH_TIME = 7  # 0不限 / 1一天内 / 7一周内
