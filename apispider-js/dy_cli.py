# -*- coding: utf-8 -*-
"""抖音 CLI 入口（兼容旧命令：python dy_cli.py ...）"""
from platforms.douyin.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
