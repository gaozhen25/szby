# -*- coding: utf-8 -*-
"""
统一入口（对齐 mediaspider platforms 结构）

用法:
  python web_im/server.py --port 8787 小红书私信服务
  python main.py xhs login                 # 有头浏览器扫码登录
  python main.py xhs login --name 账号A
  python main.py dy login                  # 有头浏览器扫码登录
  python main.py dy login --name 账号A
  python main.py xhs search 美食 旅游
  python main.py dy search 美食,篮球
  python main.py dyhot search-board
  python main.py xhs creator 'https://www.xiaohongshu.com/user/profile/...'
  python main.py dy creator 'https://www.douyin.com/user/...'
  python main.py dy creator 抖音号 --all --with-comments
  python main.py dy creator '主页URL' --all --excel --interval 3
  python main.py xhs detail 'https://www.xiaohongshu.com/explore/...?xsec_token=...'
  python main.py dy detail 'https://www.douyin.com/video/...'
  python main.py xhs profile
  python main.py dy profile
  python main.py xhs accounts
  python main.py dy accounts
  python main.py xhs profile 小红书号
  python main.py dy profile 抖音号
  python main.py xhs im dump
  python main.py xhs im poll --nick 心动 --poll-interval 2 --seconds 0
  python main.py xhs im listen --seconds 0                  # WS 长连接实时接收（秒级推送，免轮询）
  python main.py xhs im send --to 心动 --text '你好'     # 发送私信（纯WS直发优先，~1-2s；失败自动回退浏览器）
  python main.py xhs im send --to 6a4717b5000000000e03dc02 --text '你好'
  python main.py dy im dump --nick 顾清寒
  python main.py dy im poll --nick 顾清寒 --poll-interval 2
  python main.py ks im poll --nick 昵称 --poll-interval 2 --headed
  python main.py ks im dump --account ks_1
  python main.py dy im send --nick 9277 --text '你好'
  python main.py dy im send --nick 9277 --to 号1,号2 --text '你好' --workers 3
"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    platform = args.pop(0).lower()
    if platform in ("xhs", "xiaohongshu", "red"):
        from platforms.xhs.cli import main as xhs_main

        return xhs_main(args)
    if platform in ("dy", "douyin"):
        from platforms.douyin.cli import main as dy_main

        return dy_main(args)
    if platform in ("dyhot", "douhot", "热点宝"):
        from platforms.dyhot.cli import main as dyhot_main

        return dyhot_main(args)
    if platform in ("ks", "kuaishou", "快手"):
        from platforms.ks.cli import main as ks_main

        return ks_main(args)
    print(f"未知平台: {platform}（支持 xhs / dy / dyhot / ks）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
