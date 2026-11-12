# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/config/weibo_config.py
# GitHub: https://github.com/NanmiCoder
# Licensed under NON-COMMERCIAL LEARNING LICENSE 1.1
#

# 声明：本代码仅供学习和研究目的使用。使用者应遵守以下原则：
# 1. 不得用于任何商业用途。
# 2. 使用时应遵守目标平台的使用条款和robots.txt规则。
# 3. 不得进行大规模爬取或对平台造成运营干扰。
# 4. 应合理控制请求频率，避免给目标平台带来不必要的负担。
# 5. 不得用于任何非法或不当的用途。
#
# 详细许可条款请参阅项目根目录下的LICENSE文件。
# 使用本代码即表示您同意遵守上述原则和LICENSE中的所有条款。


# Weibo platform configuration

# Search type, the specific enumeration value is in media_platform/weibo/field.py
# default=综合 | real_time=实时 | popular=热门 | video=视频
# 综合翻页大约到 170+ 页会空；换 real_time/popular 可再采一批不同结果
WEIBO_SEARCH_TYPE = "real_time"

# 搜索时间范围（高级搜索 timescope）。空字符串=不限时间。
# 格式: custom:开始年-月-日-时:结束年-月-日-时
# 例: 2024-01-01 0点 ~ 2026-12-31 23点
WEIBO_TIMESCOPE = ""  # H5不支持timescope；年份用 process_x_dao_ku.py --year-from 2024 --year-to 2026

# Specify Weibo ID list
WEIBO_SPECIFIED_ID_LIST = [
    "4982041758140155",
    # ........................
]

# Specify Weibo user ID list
WEIBO_CREATOR_ID_LIST = [
    "5756404150",
    # ........................
]

# Whether to enable the function of crawling the full text of Weibo. It is enabled by default.
# If turned on, it will increase the probability of being risk controlled, which is equivalent to a keyword search request that will traverse all posts and request the post details again.
ENABLE_WEIBO_FULL_TEXT = True
