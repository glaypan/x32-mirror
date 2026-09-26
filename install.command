#!/bin/bash
# ============================================================
#  X32 Mirror - one-click installer (macOS, 10.14.6+)
#  Double-click in Finder, or:
#    chmod +x install.command && ./install.command
#  Installs: `x32mirror` command + desktop launcher.
# ============================================================
cd "$(dirname "$0")" || exit 1

# pick the best available python3 with tkinter
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
    echo " 官方支持 macOS 10.14.6 以上），安装后重新运行本文件。"
    echo "============================================================"
    read -r -p "按回车键关闭..." _
    exit 1
fi

echo "[*] Installing X32 Mirror (using $($PY -V 2>&1)) ..."
echo
"$PY" -m x32mirror install "$@"
echo
read -r -p "按回车键关闭..." _
