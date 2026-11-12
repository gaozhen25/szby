# -*- coding: utf-8 -*-
# Copyright (c) 2025 relakkes@gmail.com
#
# This file is part of MediaCrawler project.
# Repository: https://github.com/NanmiCoder/MediaCrawler/blob/main/tools/words.py
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


import asyncio
import json
import logging
import os
from collections import Counter

import aiofiles
import jieba
import matplotlib.pyplot as plt
from wordcloud import WordCloud

import config
from tools import utils

plot_lock = asyncio.Lock()

_FALLBACK_FONTS = [
    "./docs/STZHONGS.TTF",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
]


def resolve_wordcloud_font() -> str:
    candidates = [getattr(config, "FONT_PATH", "")] + _FALLBACK_FONTS
    for path in candidates:
        if path and os.path.isfile(path):
            return path
    return getattr(config, "FONT_PATH", "") or ""


class AsyncWordCloudGenerator:
    def __init__(self):
        logging.getLogger('jieba').setLevel(logging.WARNING)
        self.stop_words_file = config.STOP_WORDS_FILE
        self.lock = asyncio.Lock()
        self.stop_words = self.load_stop_words()
        self.custom_words = config.CUSTOM_WORDS
        self.font_path = resolve_wordcloud_font()
        for word, group in self.custom_words.items():
            jieba.add_word(word)

    def load_stop_words(self):
        if not os.path.isfile(self.stop_words_file):
            return set()
        with open(self.stop_words_file, 'r', encoding='utf-8') as f:
            return set(f.read().strip().split('\n'))

    async def generate_word_frequency_and_cloud(self, data, save_words_prefix):
        """
        生成词频 JSON + 词云 PNG。
        Returns:
            词云 png 路径；无有效词时返回 None
        """
        all_text = ' '.join(item['content'] for item in data if item.get('content'))
        words = [word for word in jieba.lcut(all_text) if word not in self.stop_words and len(word.strip()) > 0]
        word_freq = Counter(words)

        # Save word frequency to file
        freq_file = f"{save_words_prefix}_word_freq.json"
        async with aiofiles.open(freq_file, 'w', encoding='utf-8') as file:
            await file.write(json.dumps(word_freq, ensure_ascii=False, indent=4))

        if not word_freq:
            utils.logger.info(f"[AsyncWordCloudGenerator] empty word freq for {save_words_prefix}")
            return None

        # Try to acquire the plot lock without waiting
        if plot_lock.locked():
            utils.logger.info("Skipping word cloud generation as the lock is held.")
            return None

        return await self.generate_word_cloud(word_freq, save_words_prefix)

    async def generate_word_cloud(self, word_freq, save_words_prefix):
        await plot_lock.acquire()
        try:
            top_20_word_freq = {word: freq for word, freq in
                                sorted(word_freq.items(), key=lambda item: item[1], reverse=True)[:20]}
            if not self.font_path:
                raise FileNotFoundError(
                    "未找到中文字体，请将 FONT_PATH 指向有效的 .ttf/.ttc 文件"
                )
            wordcloud = WordCloud(
                font_path=self.font_path,
                width=800,
                height=400,
                background_color='white',
                max_words=200,
                stopwords=self.stop_words,
                colormap='viridis',
                contour_color='steelblue',
                contour_width=1
            ).generate_from_frequencies(top_20_word_freq)

            # Save word cloud image
            out_path = f"{save_words_prefix}_word_cloud.png"
            plt.figure(figsize=(10, 5), facecolor='white')
            plt.imshow(wordcloud, interpolation='bilinear')

            plt.axis('off')
            plt.tight_layout(pad=0)
            plt.savefig(out_path, format='png', dpi=300)
            plt.close()
            return out_path
        finally:
            if plot_lock.locked():
                plot_lock.release()
