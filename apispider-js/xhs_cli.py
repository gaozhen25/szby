# -*- coding: utf-8 -*-
"""小红书 CLI 入口（兼容旧命令：python xhs_cli.py ...）"""
from platforms.xhs.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
