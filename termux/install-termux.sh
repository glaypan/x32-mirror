#!/data/data/com.termux/files/usr/bin/bash
# ============================================================================
#  x32-mirror · Termux 一键安装脚本（安卓手机当同步服务器）
#
#  用法（在 Termux 里执行）：
#      bash install-termux.sh              # 交互式安装
#      bash install-termux.sh --yes        # 全部用默认值，不提问
#
#  脚本会依次完成：
#      1. 检查环境（必须是 Termux），装 python
#      2. 定位源码目录（脚本所在仓库，或从 GitHub 克隆到 ~/x32-mirror）
#      3. 生成/修改 config.json（两台调音台 IP、端口）
#      4. 安装 x32mirror / x32mirrorctl 两个命令到 $PREFIX/bin
#      5. 配置 termux-wake-lock（防休眠）+ Termux:Boot 开机自启
#      6. 打印手机访问地址（同一 WiFi 下的电脑、平板浏览器直接打开）
#
#  参数：
#      --yes            无人值守，全部取默认值
#      --src DIR        指定源码目录（默认自动判断）
#      --port N         调音台远控端口（默认 10023；WING 用 2223）
#      --http-port N    网页控制台端口（默认 8080）
#      --no-boot        不配置开机自启
#      --no-start       安装完不立即启动
# ============================================================================
set -euo pipefail

SRC=""
CON_PORT=10023
HTTP_PORT=8080
ASSUME_YES=0
DO_BOOT=1
DO_START=1

REPO_URL="https://github.com/glaypan/x32-mirror.git"
HOME_DIR="${HOME:-/data/data/com.termux/files/home}"
STATE_DIR="$HOME_DIR/.x32mirror"
BOOT_DIR="$HOME_DIR/.termux/boot"
BOOT_FILE="$BOOT_DIR/10-x32mirror.sh"
PID_FILE="$STATE_DIR/x32mirror.pid"

if [ -t 1 ]; then
  C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_DIM=$'\033[2m'; C_0=$'\033[0m'
else
  C_OK=""; C_WARN=""; C_ERR=""; C_DIM=""; C_0=""
fi
say()  { printf '%s\n' "$*"; }
step() { printf '\n%s==> %s%s\n' "$C_OK" "$*" "$C_0"; }
ok()   { printf '  %s✓%s %s\n' "$C_OK" "$C_0" "$*"; }
warn() { printf '  %s!%s %s\n' "$C_WARN" "$C_0" "$*"; }
die()  { printf '\n%s安装失败：%s%s\n' "$C_ERR" "$*" "$C_0" >&2; exit 1; }

ask() {  # ask "提示" "默认值" -> 结果放 REPLY
  local prompt="$1" def="$2"
  if [ "$ASSUME_YES" = "1" ] || [ ! -t 0 ]; then REPLY="$def"; return 0; fi
  printf '  %s [%s]: ' "$prompt" "$def"
  read -r REPLY || REPLY=""
  [ -z "$REPLY" ] && REPLY="$def"
  return 0
}

local_ip() {
  python - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except Exception:
    print("127.0.0.1")
finally:
    s.close()
PY
}

# ----------------------------------------------------------------- 参数解析
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y)     ASSUME_YES=1 ;;
    --src)        SRC="$2"; shift ;;
    --port)       CON_PORT="$2"; shift ;;
    --http-port)  HTTP_PORT="$2"; shift ;;
    --no-boot)    DO_BOOT=0 ;;
    --no-start)   DO_START=0 ;;
    -h|--help)    sed -n '2,26p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *)            die "未知参数：$1（用 --help 查看用法）" ;;
  esac
  shift
done

# ----------------------------------------------------------------- 1. 环境
step "检查运行环境"
if [ -z "${PREFIX:-}" ] || [ "${PREFIX#*com.termux}" = "$PREFIX" ]; then
  die "这个脚本只能在安卓 Termux 里运行。
     电脑请用 install.bat（Windows）/ install.command（macOS），或直接下载免安装包。"
fi
ok "Termux 环境：$PREFIX"
ok "架构：$(uname -m) · Android $(getprop ro.build.version.release 2>/dev/null || echo '?')"

step "安装 Python"
if command -v python >/dev/null 2>&1; then
  ok "已安装：$(python -V 2>&1)"
else
  say "  ${C_DIM}正在安装 python（约 50 MB，首次较慢）...${C_0}"
  pkg install -y python || die "python 安装失败，请检查网络后重试"
  ok "已安装：$(python -V 2>&1)"
fi
python -c "import asyncio, sqlite3, http.server" 2>/dev/null \
  || die "当前 python 缺少标准库组件，请执行 pkg install python 后重试"

# ----------------------------------------------------------------- 2. 源码
step "准备源码"
HERE="$(cd "$(dirname "$0")" && pwd)"
if [ -z "$SRC" ]; then
  if [ -f "$HERE/../x32mirror/__init__.py" ]; then
    SRC="$(cd "$HERE/.." && pwd)"
  elif [ -f "$HERE/x32mirror/__init__.py" ]; then
    SRC="$HERE"
  else
    SRC="$HOME_DIR/x32-mirror"
  fi
fi

if [ -f "$SRC/x32mirror/__init__.py" ]; then
  ok "使用已有源码：$SRC"
else
  command -v git >/dev/null 2>&1 || { say "  ${C_DIM}安装 git ...${C_0}"; pkg install -y git || die "git 安装失败"; }
  say "  ${C_DIM}从 GitHub 克隆到 $SRC ...${C_0}"
  rm -rf "$SRC"
  git clone --depth 1 "$REPO_URL" "$SRC" \
    || die "源码下载失败，请检查网络（也可先在浏览器下载源码 zip，解压后进入 termux 目录运行本脚本）"
  ok "已下载源码"
fi

VER="$(sed -n 's/^__version__ = "\(.*\)".*/\1/p' "$SRC/x32mirror/__init__.py" | head -1)"
ok "版本：x32-mirror ${VER:-unknown}"

# ----------------------------------------------------------------- 3. 配置
step "配置调音台地址"
CFG="$SRC/config.json"
RECONF="y"
if [ -f "$CFG" ]; then
  ok "已有配置：$CFG"
  ask "是否重新填写两台调音台 IP？(y/N)" "N"
  RECONF="$REPLY"
fi

if [ "$RECONF" = "y" ] || [ "$RECONF" = "Y" ]; then
  ask "调音台 A（主机）IP" "192.168.1.100"; A_HOST="$REPLY"
  ask "调音台 B（备机）IP" "192.168.1.101"; B_HOST="$REPLY"
  ask "远控端口（X32/M32=10023，WING=2223）" "$CON_PORT"; CON_PORT="$REPLY"
  python - "$CFG" "$A_HOST" "$B_HOST" "$CON_PORT" <<'PY'
import json, os, sys
path, a, b, port = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
cfg = {}
if os.path.exists(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except Exception:
        cfg = {}
cfg.setdefault("listen_host", "0.0.0.0")
cfg.setdefault("listen_port", 10099)
cfg.setdefault("direction", "both")
cfg.setdefault("echo_window_s", 1.0)
cfg.setdefault("renew_interval_s", 5.0)
cfg.setdefault("full_sync", True)
cfg.setdefault("full_sync_from", "a")
cfg.setdefault("oplog_db", "oplog.sqlite")
cons = cfg.setdefault("consoles", {})
cons["a"] = {"name": "console-A", "host": a, "port": port, "driver": "auto"}
cons["b"] = {"name": "console-B", "host": b, "port": port, "driver": "auto"}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(cfg, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
print("  \033[32m✓\033[0m 已写入 %s" % path)
print("    A = %s:%d   B = %s:%d" % (a, port, b, port))
PY
else
  ok "保留原有配置"
fi

# ----------------------------------------------------------------- 4. 命令
step "安装命令 x32mirror / x32mirrorctl"
mkdir -p "$PREFIX/bin" "$STATE_DIR"

cat > "$PREFIX/bin/x32mirror" <<'SHIM'
#!/data/data/com.termux/files/usr/bin/bash
# x32-mirror 命令包装（由 termux/install-termux.sh 生成）
export PYTHONPATH="@SRC@${PYTHONPATH:+:$PYTHONPATH}"
cd "@SRC@" || { echo "源码目录不存在：@SRC@" >&2; exit 1; }
exec python -m x32mirror "$@"
SHIM
sed -i "s|@SRC@|$SRC|g" "$PREFIX/bin/x32mirror"
chmod 755 "$PREFIX/bin/x32mirror"
ok "x32mirror -> python -m x32mirror"

cat > "$PREFIX/bin/x32mirrorctl" <<'CTL'
#!/data/data/com.termux/files/usr/bin/bash
# x32-mirror 后台服务管理（由 termux/install-termux.sh 生成）
SRC="@SRC@"
STATE="@STATE@"
PORT="@PORT@"
LOG="$STATE/x32mirror.log"
PIDF="$STATE/x32mirror.pid"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"

ip() {
  python - <<'PY'
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(("8.8.8.8", 80))
    print(s.getsockname()[0])
except Exception:
    print("127.0.0.1")
finally:
    s.close()
PY
}

pid() {
  [ -f "$PIDF" ] || return 1
  local p
  p="$(cat "$PIDF" 2>/dev/null)"
  [ -n "$p" ] || return 1
  kill -0 "$p" 2>/dev/null || return 1
  echo "$p"
}

port_open() {
  python - "$PORT" <<'PY'
import socket, sys
s = socket.socket()
s.settimeout(0.6)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

do_start() {
  local p
  if p="$(pid)"; then echo "已在运行（PID $p，端口 $PORT）"; return 0; fi
  if port_open; then
    echo "端口 $PORT 已被占用：可能已在运行（PID 记录丢失），先 x32mirrorctl stop 再重启"
    return 0
  fi
  mkdir -p "$STATE"
  cd "$SRC" || return 1
  command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
  echo "----- $(date '+%F %T') start -----" >> "$LOG"
  nohup python -m x32mirror web --http-port "$PORT" --autostart >> "$LOG" 2>&1 &
  p=$!
  disown "$p" 2>/dev/null || true
  echo "$p" > "$PIDF"
  sleep 3
  if kill -0 "$p" 2>/dev/null; then
    echo "已启动：http://$(ip):$PORT"
  else
    rm -f "$PIDF"
    echo "启动失败，最后 20 行日志："
    tail -n 20 "$LOG"
    return 1
  fi
}

do_stop() {
  local p
  if ! p="$(pid)"; then
    rm -f "$PIDF"
    if port_open && command -v pkill >/dev/null 2>&1; then
      pkill -f "x32mirror web --http-port $PORT" 2>/dev/null || true
      sleep 1
      command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
      echo "已停止（按端口回收，PID 记录已丢失）"
      return 0
    fi
    echo "未在运行"
    return 0
  fi
  kill "$p" 2>/dev/null || true
  local i=0
  while kill -0 "$p" 2>/dev/null && [ "$i" -lt 20 ]; do sleep 0.2; i=$((i + 1)); done
  kill -9 "$p" 2>/dev/null || true
  rm -f "$PIDF"
  command -v termux-wake-unlock >/dev/null 2>&1 && termux-wake-unlock
  echo "已停止"
}

case "${1:-status}" in
  start)   do_start ;;
  stop)    do_stop ;;
  restart) do_stop; sleep 1; do_start ;;
  status)
    if p="$(pid)"; then echo "运行中（PID $p）"
    elif port_open; then echo "端口 $PORT 有服务在响应（PID 记录丢失，可 x32mirrorctl stop 清理）"
    else echo "未运行"; fi ;;
  log)     tail -n "${2:-40}" "$LOG" 2>/dev/null || echo "暂无日志" ;;
  logf)    tail -f "$LOG" ;;
  clean)   : > "$LOG"; echo "日志已清空" ;;
  ip)      ip ;;
  url)     echo "http://$(ip):$PORT" ;;
  *) echo "用法：x32mirrorctl {start|stop|restart|status|log|logf|clean|ip|url}"; exit 1 ;;
esac
CTL
sed -i "s|@SRC@|$SRC|g; s|@STATE@|$STATE_DIR|g; s|@PORT@|$HTTP_PORT|g" "$PREFIX/bin/x32mirrorctl"
chmod 755 "$PREFIX/bin/x32mirrorctl"
ok "x32mirrorctl {start|stop|restart|status|log|ip|url}"

# ----------------------------------------------------------------- 5. 自启
if [ "$DO_BOOT" = "1" ]; then
  step "配置开机自启（Termux:Boot）"
  mkdir -p "$BOOT_DIR"
  cat > "$BOOT_FILE" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/bash
# 由 x32-mirror termux/install-termux.sh 生成
# Termux:Boot 会在开机后执行 ~/.termux/boot/ 下的脚本
sleep 8
command -v termux-wake-lock >/dev/null 2>&1 && termux-wake-lock
"@BIN@/x32mirrorctl" start >> "@STATE@/boot.log" 2>&1
BOOT
  sed -i "s|@BIN@|$PREFIX/bin|g; s|@STATE@|$STATE_DIR|g" "$BOOT_FILE"
  chmod 755 "$BOOT_FILE"
  ok "已写入 $BOOT_FILE"
  if command -v pm >/dev/null 2>&1 && pm list packages 2>/dev/null | grep -q "com.termux.boot"; then
    ok "检测到已安装 Termux:Boot"
  else
    warn "还没装 Termux:Boot（F-Droid 搜 Termux:Boot，装完先手动打开一次）"
  fi
else
  step "跳过开机自启（--no-boot）"
fi

# ----------------------------------------------------------------- 6. 总结
step "安装完成"
IP="$(local_ip)"

cat <<EOF

  源码目录   $SRC
  配置文件   $CFG
  运行日志   $STATE_DIR/x32mirror.log

  启动服务   x32mirrorctl start
  查看状态   x32mirrorctl status
  实时日志   x32mirrorctl logf
  查看地址   x32mirrorctl url
  停止服务   x32mirrorctl stop

  手机 / 平板浏览器打开：  ${C_OK}http://$IP:$HTTP_PORT${C_0}
  （同一 WiFi 下的电脑、平板都能打开这个地址）

  命令行也可以直接用：
      x32mirror show-config
      x32mirror web --http-port $HTTP_PORT --autostart
      x32mirror snapshot

EOF

if [ "$DO_START" = "1" ]; then
  ask "现在启动同步服务？(Y/n)" "Y"
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    step "启动服务"
    "$PREFIX/bin/x32mirrorctl" start || warn "启动失败，看日志：x32mirrorctl log"
  fi
fi

cat <<EOF

${C_WARN}安卓省电策略必看${C_0}（不做这两步，锁屏几分钟后会被系统杀掉）：
  1. 系统设置 → 应用 → Termux → 电池 → 选“不限制 / 允许后台活动”
  2. 保留通知栏的 Termux wakelock 常驻通知（脚本已自动 termux-wake-lock）
  3. 开机自启还需装 Termux:Boot，并先手动打开一次

${C_DIM}提示：热点或路由器重启后手机 IP 可能变化，用 x32mirrorctl url 重新查看。${C_0}
${C_DIM}注意：手机端只跑网页控制台（web），没有桌面 GUI；两台调音台与手机要在同一局域网。${C_0}

EOF
