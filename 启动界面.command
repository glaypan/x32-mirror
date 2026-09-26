#!/bin/bash
# x32-mirror GUI launcher for macOS (double-click in Finder, or:
#   chmod +x 启动界面.command && ./启动界面.command)
# Supports macOS 10.14.6 (Mojave) and later.
# Requires Python 3.9+ with tkinter (python.org installer recommended;
# on 10.14.6 use Python 3.12 or 3.13 - both officially support it).

cd "$(dirname "$0")" || exit 1

# pick the best available python3
PY=""
for cand in python3.13 python3.12 python3 /usr/local/bin/python3 \
            /opt/homebrew/bin/python3 /usr/bin/python3; do
    if command -v "$cand" >/dev/null 2>&1; then
        if "$cand" -c "import tkinter" >/dev/null 2>&1; then
            PY="$cand"
            break
        fi
    fi
done

if [ -z "$PY" ]; then
    echo "============================================================"
    echo " 未找到带 tkinter 的 Python。"
    echo " 请到 python.org 安装 Python 3.12 或 3.13（安装包自带 tkinter，"
    echo " 且官方支持 macOS 10.14.6 / High Sierra 10.13 以上）。"
    echo " 安装后重新双击本文件即可。"
    echo "============================================================"
    read -r -p "按回车键关闭..." _
    exit 1
fi

echo "Using Python: $($PY -V 2>&1)"
exec "$PY" -m x32mirror gui
