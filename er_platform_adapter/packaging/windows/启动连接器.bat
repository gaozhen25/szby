@echo off
chcp 65001 >nul
title 轻回桌面连接器
cd /d "%~dp0"
echo 正在启动 轻回桌面连接器 ...
echo 浏览器将自动打开 http://127.0.0.1:8765/ ，请保持本窗口开启。
echo 关闭本窗口将停止连接器。
adapter.exe serve --dotenv .env
pause
