"""Desktop GUI for the mirror tool (tkinter, stdlib only).

Launch:
    python -m x32mirror gui          # explicit
    python -m x32mirror              # no args -> GUI
    启动界面.bat                      # double-click on Windows

Tabs: 运行状态 / 连接配置 / 快照与恢复 / 操作日志 / 使用说明 / 注意事项
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import cloud
from .drivers import DRIVERS, detect_console_sync, get_driver
from .engine import MirrorEngine, restore_snapshot

log = logging.getLogger("x32mirror.gui")

DEFAULT_CONFIG = "config.json"


# ---------------------------------------------------------------- engine runner
class EngineRunner:
    """Runs MirrorEngine in a background thread with its own event loop."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.engine: MirrorEngine | None = None
        self._loop = None
        self._thread = None
        self._stop_evt = None
        self._transport = None
        self.error = None

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self):
        if self.running:
            return
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True, name="mirror-engine")
        self._thread.start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_evt = asyncio.Event()
        try:
            self._loop.run_until_complete(self._main())
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            log.error("engine stopped with error: %s", exc)

    async def _main(self):
        loop = asyncio.get_running_loop()
        self.engine = MirrorEngine(self.cfg)
        self._transport, _ = await loop.create_datagram_endpoint(
            lambda: self.engine,
            local_addr=(self.cfg.get("listen_host", "0.0.0.0"),
                        int(self.cfg.get("listen_port", 10099))))
        await self.engine.start()
        log.info("mirror engine running - consoles %s <-> %s (listen :%s)",
                 self.engine.a.name, self.engine.b.name, self.cfg.get("listen_port", 10099))
        await self._stop_evt.wait()
        await self.engine.stop()
        self._transport.close()

    def stop(self):
        if self._loop and self._stop_evt:
            self._loop.call_soon_threadsafe(self._stop_evt.set)
        if self._thread:
            self._thread.join(timeout=6)
        self._thread = None
        self.engine = None


# ---------------------------------------------------------------- help texts
HELP_USAGE = """\
【使用说明】调音台实时镜像同步工具

一、准备工作
  1. 两台调音台和本电脑接在同一个局域网（网线或同一 WiFi 均可）。
  2. 记下两台调音台的 IP 地址：
     X32/M32：Setup → Network 查看本机 IP；
     WING：Setup → Network → Control Audio IP。
  3. 调音台远程控制协议默认开启（X32/M32 端口 10023，WING 端口 2223）。

二、填写连接配置（“连接配置”页）
  1. 调音台 A / 调音台 B：分别填入两台调音台的 IP 地址。
  2. 型号驱动：默认 auto（推荐）——点【自动检测型号】或启动镜像时
     自动识别 X32 / M32 / WING 并套用对应协议；也可手动指定：
     X32 和 M32 都选 x32（同协议）；WING 选 wing。
     跨型号配对（如 X32 ↔ WING）会自动做推子 dB 换算。
  3. 点“保存配置”写入 config.json。

三、选择同步模式并启动镜像（“同步模式”页）
  1. 三种模式（右侧可切主机 A/B）：
     ● 单控台（A → B）：主台操作，备台跟随；备台被人误动后约 0.5 秒
       自动回弹到主机状态；两台同时操作以主机为准。
     ● 双控台全镜像（A ≠ B）：双侧双向同步，支持的屏幕状态一起跟随。
     ● 双控台显示独立（A · B）：音频双侧双向同步，两边屏幕各自操作，
       屏幕状态（选中通道/独奏开关等）不互相跟随。
  2. 点【连接】启动镜像，状态变为“连接成功”。启动后（勾选“启动时安全
     检测”）会先跑一遍安全检测：兼容预检 → 读取主机 → 写入备台 →
     读回核对，进度框实时显示 Node 写入数与当前路径，可随时取消。
  3. 运行中切换模式同样先做安全检测：先把主机状态对齐到另一台并逐项
     读回核对，对齐期间请勿操作调音台；完成后提示“可以操作调音台”。
     检测期间已写入的参数在取消时不会自动撤销。
  4. “运行状态”卡常驻显示 转发 / 读回确认 / 待核对 / 自动恢复 计数，
     并可【暂停同步】临时断开转发（链路与日志照常）、【结束同步】停止。

四、用手机/iPad/电脑遥控软件（Mixing Station、X32-Edit 等）
  遥控软件里服务器地址不要填调音台 IP，改填：
     本电脑的 IP : 10099
  工具对外就像一台虚拟调音台，遥控软件的操作会同步到两台调音台，
  台上的物理操作也会实时回显到遥控软件。可同时连接多个遥控端。

五、快照与恢复（“快照与恢复”页）
  ● 手动快照：读取当前调音台全部状态，保存为 JSON 文件。
  ● 上传云端：把快照上传到对象存储 / WebDAV / 本地目录（需在配置里启用 cloud）。
  ● 一键恢复：把选中的快照写回两台调音台。默认先预览，
    确认无误后再点“确认写台”。恢复前建议先拍一张当前快照留还原点。

六、手机访问（安卓 / iPhone，无需装 App）
  在电脑上运行：python -m x32mirror web --http-port 8080 --autostart
  然后手机浏览器（连同一 WiFi）打开：
     http://<电脑IP>:8080
  手机上即可查看状态、启动/停止镜像、改调音台 IP、拍快照、
  一键恢复、看日志，使用说明和注意事项也已内置在页面里。
  首次使用请在防火墙放行 8080 端口（TCP）。

七、双机热备（可选，进阶）
  两台电脑跑同一个工具互为备份：先启动的自动当主机负责同步，
  另一台自动待命并实时记录操作日志；主机宕机约 3 秒后备机自动接管。
  在 config.json 的 ha 节配置（node_id 两台不能重复，peer_host 填对方 IP）。
"""

HELP_CAUTION = """\
【注意事项】请务必阅读

⚠ 1. 先空场测试再上演出
     首次连接真机时，请先用一两路通道试推子和静音，确认两台动作
     方向一致、无异常后再投入正式使用。

⚠ 2. 恢复操作会覆盖调音台当前状态
     “一键恢复”会把快照里的推子/静音值写回两台调音台，当前正在
     进行的调音会被覆盖。演出进行中不要随意恢复；恢复前先拍快照。

⚠ 3. 不要在两台调音台上同时操作同一路径
     全镜像模式下同时操作按“后写为准”(last-write-wins)裁决，虽然
     不会报错，但结果可能和你预期的不同。养成“谁主调谁操作”的习惯；
     或改用单控台模式——同时操作一律以主机为准，备台误动会自动回弹。

⚠ 4. 跨品牌配对只同步已映射的参数
     X32↔WING 已覆盖推子/静音/通道名等核心参数；EQ、效果器、
     路由等参数不在同步范围（两边型号差异太大，强行同步会出错）。

⚠ 5. 镜像 ≠ 备份，重要场合两者都要
     实时镜像保证两台状态一致；但误操作也会被同步过去。演出前
     务必拍一张快照（或开启云端定时备份），出问题可一键拉回。

⚠ 6. 网络要求
     全程使用局域网，不要经过公网/VPN 做实时镜像（延迟和丢包会
     破坏实时性）。推子高频动作约几十毫秒内同步到对端属正常。

⚠ 7. 防火墙放行
     Windows 首次运行会弹防火墙询问，请允许“专用网络”。
     若状态页一直显示“未收到数据”，多半是防火墙拦了 UDP 端口。

⚠ 8. 双机热备时遥控软件要连主机
     连在备机上的遥控端是只读的。主机切换后需要把遥控软件重新
     指向新的主机电脑。

⚠ 9. 端口占用
     若启动报端口被占用(WinError 10013/10048)，在连接配置里换一个
     监听端口（如 10098）再启动。

⚠ 10. 长时间运行
     工具设计为可 7×24 运行。建议演出期间不要关电脑的休眠
     （电源选项设为“从不睡眠”）。
"""

HELP_FAQ = """\
【常见问题】

Q：启动后状态灯变绿但两台调音台没反应？
A：按顺序检查——① 两台 IP 填对了吗（ping 一下试试）；② 端口对吗
   （X32/M32 10023，WING 2223）；③ 防火墙放行了吗；④ 调音台的
   远程控制是否被禁用（X32: Setup→Remote）。

Q：推子数值两边差一点点？
A：正常。跨机型（X32↔WING）换算使用官方分段线性曲线，误差在
   ±0.05 dB 内；同型号直传理论无误差。

Q：换场景会同步吗？
A：会。场景切换作为高优先级事件立即转发（同族配对）。

Q：三种同步模式有什么区别？
A：单控台=主机单向驱动备台（备台误动约 0.5 秒回弹，同时操作以主机
   为准）；全镜像=双侧双向，屏幕状态也一起跟随；显示独立=音频双向
   同步，但两边屏幕各自操作不互跟。运行中可随时切换，切换前会先把
   主机状态对齐到另一台。

Q：操作日志在哪里？
A：config 里 oplog_db 指定的 SQLite 文件（默认 oplog.sqlite），
   记录每一次变更：时间、来源、路径、数值，可审计追溯。
"""


# ---------------------------------------------------------------- GUI
class MirrorGUI(tk.Tk):
    def __init__(self, config_path=DEFAULT_CONFIG):
        super().__init__()
        self.title("调音台实时镜像同步工具 x32-mirror")
        self.geometry("880x640")
        self.minsize(760, 560)
        try:
            self.call("tk", "scaling", 1.25)
        except tk.TclError:
            pass

        self.config_path = os.path.abspath(config_path)
        self.cfg = {}
        self.runner = None
        self._log_queue = queue.Queue()

        self._setup_logging()
        self._load_config(silent=True)
        self._build_toolbar()
        self._build_tabs()
        self._fill_config_form()
        self._poll_status()
        self._poll_log()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- logging ----------
    def _setup_logging(self):
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        if not any(isinstance(h, logging.handlers.QueueHandler) for h in root.handlers):
            qh = logging.handlers.QueueHandler(self._log_queue)
            qh.setLevel(logging.INFO)
            root.addHandler(qh)

    def _poll_log(self):
        try:
            while True:
                record = self._log_queue.get_nowait()
                ts = time.strftime("%H:%M:%S", time.localtime(record.created))
                self.log_text.configure(state="normal")
                self.log_text.insert("end", f"[{ts}] {record.levelname[:4]} {record.getMessage()}\n")
                if self.log_text.index("end-1c").split(".")[0] != "1" or True:
                    self.log_text.see("end")
                # keep it bounded
                if int(self.log_text.index("end-1c").split(".")[0]) > 3000:
                    self.log_text.delete("1.0", "1000.0")
                self.log_text.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(300, self._poll_log)

    # ---------- config ----------
    def _load_config(self, silent=False):
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                self.cfg = json.load(fh)
            if not silent:
                self._log(f"配置已加载: {self.config_path}")
        except Exception as exc:  # noqa: BLE001
            self.cfg = {
                "listen_host": "0.0.0.0", "listen_port": 10099, "direction": "both",
                "sync_mode": "mirror", "master": "a",
                "full_sync": True, "full_sync_from": "a", "oplog_db": "oplog.sqlite",
                "consoles": {
                    "a": {"name": "console-A", "host": "192.168.1.100", "port": 10023, "driver": "x32"},
                    "b": {"name": "console-B", "host": "192.168.1.101", "port": 10023, "driver": "x32"},
                },
            }
            if not silent:
                messagebox.showwarning("配置", f"读取 {self.config_path} 失败（{exc}），\n已载入默认配置，请修改后保存。")

    def _fill_config_form(self):
        c = self.cfg
        self.var_a_name.set(c["consoles"]["a"].get("name", "console-A"))
        self.var_a_host.set(c["consoles"]["a"].get("host", ""))
        self.var_a_port.set(str(c["consoles"]["a"].get("port", 10023)))
        self.var_a_drv.set(c["consoles"]["a"].get("driver", "x32"))
        self.var_b_name.set(c["consoles"]["b"].get("name", "console-B"))
        self.var_b_host.set(c["consoles"]["b"].get("host", ""))
        self.var_b_port.set(str(c["consoles"]["b"].get("port", 10023)))
        self.var_b_drv.set(c["consoles"]["b"].get("driver", "x32"))
        self.var_listen.set(str(c.get("listen_port", 10099)))
        self.var_direction.set(c.get("direction", "both"))
        self.var_delay.set(str(c.get("sync_delay_s", 0) or 0))
        self.var_fullsync.set(bool(c.get("full_sync", True)))
        self.var_oplog.set(c.get("oplog_db") or "")
        self.var_mode.set(c.get("sync_mode", "mirror"))
        self.var_master.set(c.get("master", "a"))

    def _collect_config(self):
        def port(v, dflt):
            try:
                return int(v)
            except (TypeError, ValueError):
                return dflt

        def delay(v):
            try:
                return max(0.0, float(v))
            except (TypeError, ValueError):
                return 0.0

        mode = self.var_mode.get() or "mirror"
        master = self.var_master.get() or "a"
        if mode == "single":
            direction = "a_to_b" if master == "a" else "b_to_a"
        else:
            direction = "both"
        return {
            "listen_host": "0.0.0.0",
            "listen_port": port(self.var_listen.get(), 10099),
            "direction": direction,
            "sync_mode": mode,
            "master": master,
            "revert_delay_s": 0.5,
            "sync_delay_s": delay(self.var_delay.get()),
            "echo_window_s": 1.0,
            "renew_interval_s": 5.0,
            "coalesce_window_s": 0.12,
            "reconcile_interval_s": 3600.0,
            "link_timeout_s": 15.0,
            "full_sync": bool(self.var_fullsync.get()),
            "full_sync_from": "a",
            "oplog_db": self.var_oplog.get().strip() or None,
            "consoles": {
                "a": {"name": self.var_a_name.get() or "console-A",
                      "host": self.var_a_host.get().strip(),
                      "port": port(self.var_a_port.get(), 10023),
                      "driver": self.var_a_drv.get()},
                "b": {"name": self.var_b_name.get() or "console-B",
                      "host": self.var_b_host.get().strip(),
                      "port": port(self.var_b_port.get(), 10023),
                      "driver": self.var_b_drv.get()},
            },
        }

    def _save_config(self):
        if self.runner and self.runner.running:
            messagebox.showwarning("保存配置", "镜像运行中，请先停止再修改配置。")
            return
        self.cfg = self._collect_config()
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, ensure_ascii=False)
        self._log(f"配置已保存: {self.config_path}")

    # ---------- toolbar ----------
    def _build_toolbar(self):
        bar = ttk.Frame(self, padding=(8, 6))
        bar.pack(fill="x")
        ttk.Label(bar, text="配置文件:").pack(side="left")
        self.var_cfgpath = tk.StringVar(value=self.config_path)
        ttk.Entry(bar, textvariable=self.var_cfgpath, width=34).pack(side="left", padx=(4, 4))
        ttk.Button(bar, text="…", width=3, command=self._pick_config).pack(side="left")
        ttk.Button(bar, text="加载", width=6, command=self._reload_config).pack(side="left", padx=(4, 8))

        self.btn_start = ttk.Button(bar, text="▶ 启动镜像", command=self._start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_stop = ttk.Button(bar, text="■ 停止", command=self._stop, state="disabled")
        self.btn_stop.pack(side="left", padx=2)

        self.var_status = tk.StringVar(value="● 未运行")
        self.lbl_status = tk.Label(bar, textvariable=self.var_status, fg="#888888",
                                   font=("Microsoft YaHei", 10, "bold"))
        self.lbl_status.pack(side="right", padx=4)

    def _pick_config(self):
        path = filedialog.askopenfilename(title="选择配置文件",
                                          filetypes=[("JSON 配置", "*.json"), ("所有文件", "*.*")],
                                          initialdir=os.path.dirname(self.config_path) or ".")
        if path:
            self.config_path = path
            self.var_cfgpath.set(path)
            self._load_config()
            self._fill_config_form()

    def _reload_config(self):
        if self.runner and self.runner.running:
            messagebox.showwarning("加载配置", "镜像运行中，请先停止再加载配置。")
            return
        self.config_path = self.var_cfgpath.get().strip() or DEFAULT_CONFIG
        self._load_config()
        self._fill_config_form()

    def _log(self, msg):
        logging.getLogger("x32mirror").info(msg)

    # ---------- tabs ----------
    def _build_tabs(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.tab_status = ttk.Frame(nb)
        self.tab_config = ttk.Frame(nb)
        self.tab_snap = ttk.Frame(nb)
        self.tab_log = ttk.Frame(nb)
        self.tab_help = ttk.Frame(nb)
        self.tab_caution = ttk.Frame(nb)
        self.tab_faq = ttk.Frame(nb)
        for f, label in ((self.tab_status, "运行状态"), (self.tab_config, "连接配置"),
                         (self.tab_snap, "快照与恢复"), (self.tab_log, "操作日志"),
                         (self.tab_help, "使用说明"), (self.tab_caution, "注意事项"),
                         (self.tab_faq, "常见问题")):
            nb.add(f, text=label)

        self._build_status_tab(self.tab_status)
        self._build_config_tab(self.tab_config)
        self._build_snapshot_tab(self.tab_snap)
        self._build_log_tab(self.tab_log)
        self._build_text_tab(self.tab_help, HELP_USAGE)
        self._build_text_tab(self.tab_caution, HELP_CAUTION)
        self._build_text_tab(self.tab_faq, HELP_FAQ)

    def _build_status_tab(self, frame):
        frame.configure(padding=10)
        top = ttk.LabelFrame(frame, text="镜像概况", padding=10)
        top.pack(fill="x", pady=(0, 8))
        self.var_summary = tk.StringVar(value="未运行。填写连接配置后点上方【启动镜像】。")
        ttk.Label(top, textvariable=self.var_summary, justify="left",
                  font=("Microsoft YaHei", 10)).pack(anchor="w")

        mid = ttk.Frame(frame)
        mid.pack(fill="both", expand=True)
        for col, title in ((0, "调音台 A"), (1, "调音台 B")):
            lf = ttk.LabelFrame(mid, text=title, padding=10)
            lf.grid(row=0, column=col, sticky="nsew", padx=(0, 8))
            mid.columnconfigure(col, weight=1)
            setattr(self, f"var_info_{'a' if col == 0 else 'b'}",
                    tk.StringVar(value="—"))
            lbl = tk.Label(lf, textvariable=getattr(self, f"var_info_{'a' if col == 0 else 'b'}"),
                           justify="left", anchor="nw", font=("Consolas", 10), fg="#333333")
            lbl.pack(fill="both", expand=True)

        btns = ttk.Frame(frame)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="立即全量对齐 (A→B)", command=self._resync).pack(side="left")
        ttk.Button(btns, text="清空日志显示", command=self._clear_log_view).pack(side="left", padx=8)

    def _build_config_tab(self, frame):
        frame.configure(padding=10)
        drv_keys = ["auto"] + sorted(DRIVERS.keys())

        def console_frame(parent, side):
            lf = ttk.LabelFrame(parent, text=f"调音台 {side}", padding=10)
            v_name = tk.StringVar()
            v_host = tk.StringVar()
            v_port = tk.StringVar()
            v_drv = tk.StringVar(value="auto")
            rows = [("名称", v_name), ("IP 地址", v_host), ("端口", v_port)]
            for i, (label, var) in enumerate(rows):
                ttk.Label(lf, text=label + ":").grid(row=i, column=0, sticky="e", pady=3, padx=(0, 6))
                ttk.Entry(lf, textvariable=var, width=22).grid(row=i, column=1, sticky="w", pady=3)
            ttk.Label(lf, text="型号驱动:").grid(row=3, column=0, sticky="e", pady=3, padx=(0, 6))
            cb = ttk.Combobox(lf, textvariable=v_drv, values=drv_keys, width=20, state="readonly")
            cb.grid(row=3, column=1, sticky="w", pady=3)
            hint = tk.Label(lf, text="", justify="left", fg="#666666", font=("Microsoft YaHei", 9))
            hint.grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))

            def on_drv(*_):
                key = v_drv.get()
                if key == "auto":
                    hint.configure(text="启动时自动探测型号（X32 / M32 / WING）\n并自动套用对应协议端口与参数映射")
                    return
                try:
                    spec = get_driver(key)
                    hint.configure(text=f"{spec.brand} · {spec.models}\n{spec.transport} 端口 {spec.port} · 推子单位 {spec.fader_unit}")
                except Exception:  # noqa: BLE001
                    hint.configure(text="")
            v_drv.trace_add("write", on_drv)

            def do_detect():
                host = v_host.get().strip()
                if not host:
                    hint.configure(text="请先填写 IP 地址再检测")
                    return
                hint.configure(text=f"正在探测 {host} …")
                try:
                    port_hint = [int(v_port.get())] if v_port.get().strip().isdigit() else []
                except ValueError:  # noqa: PERF203
                    port_hint = []

                def worker():
                    key, model, port = detect_console_sync(host, 2.5, port_hint)
                    def apply():
                        if key:
                            v_port.set(str(port))
                            v_drv.set(key)
                            hint.configure(text=f"✔ 检测到：{model}（驱动 {key}，端口 {port}）")
                        else:
                            hint.configure(text=f"✗ 未识别出型号（{host} 不响应 OSC 探测，请核对 IP/端口/防火墙）")
                    frame.after(0, apply)
                threading.Thread(target=worker, daemon=True).start()

            ttk.Button(lf, text="🔍 自动检测型号", command=do_detect).grid(
                row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))
            on_drv()
            return lf, v_name, v_host, v_port, v_drv

        grid = ttk.Frame(frame)
        grid.pack(fill="x")
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        lf_a, self.var_a_name, self.var_a_host, self.var_a_port, self.var_a_drv = console_frame(grid, "A")
        lf_b, self.var_b_name, self.var_b_host, self.var_b_port, self.var_b_drv = console_frame(grid, "B")
        lf_a.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        lf_b.grid(row=0, column=1, sticky="nsew")

        opts = ttk.LabelFrame(frame, text="运行选项", padding=10)
        opts.pack(fill="x", pady=8)
        self.var_listen = tk.StringVar(value="10099")
        self.var_direction = tk.StringVar(value="both")
        self.var_delay = tk.StringVar(value="0")
        self.var_fullsync = tk.BooleanVar(value=True)
        self.var_oplog = tk.StringVar(value="oplog.sqlite")
        self.var_mode = tk.StringVar(value="mirror")
        self.var_master = tk.StringVar(value="a")
        ttk.Label(opts, text="监听端口:").grid(row=0, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(opts, textvariable=self.var_listen, width=10).grid(row=0, column=1, sticky="w", pady=3)
        ttk.Label(opts, text="同步方向:").grid(row=0, column=2, sticky="e", padx=(24, 6), pady=3)
        ttk.Combobox(opts, textvariable=self.var_direction, width=10, state="readonly",
                     values=["both", "a_to_b", "b_to_a"]).grid(row=0, column=3, sticky="w", pady=3)
        ttk.Label(opts, text="同步延迟(秒):").grid(row=1, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Entry(opts, textvariable=self.var_delay, width=10).grid(row=1, column=1, sticky="w", pady=3)
        ttk.Label(opts, text="0 = 实时；A 操作后延迟多少秒再同步到 B",
                  foreground="#666666", font=("Microsoft YaHei", 8)).grid(
            row=1, column=2, columnspan=2, sticky="w", padx=(24, 6), pady=3)
        ttk.Label(opts, text="同步模式:").grid(row=2, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Combobox(opts, textvariable=self.var_mode, width=12, state="readonly",
                     values=["mirror", "single", "independent"]).grid(row=2, column=1, sticky="w", pady=3)
        ttk.Label(opts, text="single 单控台(备台误操作自动回弹) / mirror 全镜像 / independent 显示独立(屏幕状态不跟随)",
                  foreground="#666666", font=("Microsoft YaHei", 8)).grid(
            row=2, column=2, columnspan=2, sticky="w", padx=(24, 6), pady=3)
        ttk.Label(opts, text="主机:").grid(row=3, column=0, sticky="e", padx=(0, 6), pady=3)
        ttk.Combobox(opts, textvariable=self.var_master, width=6, state="readonly",
                     values=["a", "b"]).grid(row=3, column=1, sticky="w", pady=3)
        ttk.Label(opts, text="单控台模式由主机驱动备台；两台同时操作以主机为准",
                  foreground="#666666", font=("Microsoft YaHei", 8)).grid(
            row=3, column=2, columnspan=2, sticky="w", padx=(24, 6), pady=3)
        ttk.Checkbutton(opts, text="启动时全量基线对齐 (主机→备机)",
                        variable=self.var_fullsync).grid(row=4, column=0, columnspan=2, sticky="w", pady=3)
        ttk.Label(opts, text="操作日志:").grid(row=4, column=2, sticky="e", padx=(24, 6), pady=3)
        ttk.Entry(opts, textvariable=self.var_oplog, width=18).grid(row=4, column=3, sticky="w", pady=3)

        ttk.Button(frame, text="💾 保存配置到 config.json", command=self._save_config).pack(anchor="w")

    def _build_snapshot_tab(self, frame):
        frame.configure(padding=10)
        lf1 = ttk.LabelFrame(frame, text="快照备份", padding=10)
        lf1.pack(fill="x", pady=(0, 8))
        ttk.Button(lf1, text="📸 拍摄快照（读取两台当前状态）",
                   command=self._do_snapshot).pack(side="left")
        ttk.Button(lf1, text="☁ 上传云端", command=self._do_upload).pack(side="left", padx=8)
        self.var_snap_last = tk.StringVar(value="尚未拍摄")
        tk.Label(lf1, textvariable=self.var_snap_last, fg="#666666",
                 font=("Microsoft YaHei", 9)).pack(side="left", padx=12)

        lf2 = ttk.LabelFrame(frame, text="恢复（把快照写回两台调音台）", padding=10)
        lf2.pack(fill="x")
        self.var_snapfile = tk.StringVar()
        ttk.Entry(lf2, textvariable=self.var_snapfile, width=40).pack(side="left", padx=(0, 4))
        ttk.Button(lf2, text="浏览…", command=self._pick_snapshot).pack(side="left")
        ttk.Button(lf2, text="☁ 拉取云端最新", command=self._do_cloud_download).pack(side="left", padx=(8, 0))
        ttk.Button(lf2, text="① 预览（干跑）", command=lambda: self._do_restore(dry=True)).pack(side="left", padx=(16, 4))
        ttk.Button(lf2, text="② 确认写台", command=lambda: self._do_restore(dry=False)).pack(side="left")

        lf3 = ttk.LabelFrame(frame, text="云端存储配置（写入 config.json 的 cloud 节）", padding=10)
        lf3.pack(fill="x", pady=8)
        self.var_cloud_provider = tk.StringVar(value=(self.cfg.get("cloud") or {}).get("provider", "local"))
        self.var_cloud_dir = tk.StringVar(value=(self.cfg.get("cloud") or {}).get("dir", "./cloud-backups"))
        self.var_cloud_hours = tk.StringVar(value=str((self.cfg.get("cloud") or {}).get("interval_hours", 6)))
        ttk.Label(lf3, text="类型:").grid(row=0, column=0, sticky="e", padx=(0, 6))
        ttk.Combobox(lf3, textvariable=self.var_cloud_provider, width=10, state="readonly",
                     values=["local", "s3", "webdav"]).grid(row=0, column=1, sticky="w")
        ttk.Label(lf3, text="目录/URL:").grid(row=0, column=2, sticky="e", padx=(16, 6))
        ttk.Entry(lf3, textvariable=self.var_cloud_dir, width=30).grid(row=0, column=3, sticky="w")
        ttk.Label(lf3, text="自动上传间隔(小时,0=手动):").grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Entry(lf3, textvariable=self.var_cloud_hours, width=8).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Button(lf3, text="保存云端配置", command=self._save_cloud_cfg).grid(row=1, column=3, sticky="w", pady=(6, 0))
        tk.Label(lf3, text="s3=AWS S3/阿里云OSS/腾讯云COS/MinIO（凭据在 config.json 的 cloud 节填写 access_key 等）",
                 fg="#666666", font=("Microsoft YaHei", 9)).grid(row=2, column=0, columnspan=4, sticky="w", pady=(6, 0))

        self.snap_info = tk.Text(frame, height=10, font=("Consolas", 10), state="disabled")
        self.snap_info.pack(fill="both", expand=True, pady=(4, 0))

    def _build_log_tab(self, frame):
        frame.configure(padding=6)
        self.log_text = tk.Text(frame, font=("Consolas", 10), state="disabled",
                                bg="#1e1e1e", fg="#d4d4d4", insertbackground="#d4d4d4")
        scroll = ttk.Scrollbar(frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log_text.pack(fill="both", expand=True)

    def _build_text_tab(self, frame, text):
        frame.configure(padding=6)
        txt = tk.Text(frame, font=("Microsoft YaHei", 10), wrap="word", padx=14, pady=12,
                      relief="flat", bg="#fafafa")
        txt.insert("1.0", text)
        txt.configure(state="disabled")
        scroll = ttk.Scrollbar(frame, command=txt.yview)
        txt.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        txt.pack(fill="both", expand=True)

    # ---------- engine control ----------
    def _start(self):
        if self.runner and self.runner.running:
            return
        if not self.var_a_host.get().strip() or not self.var_b_host.get().strip():
            messagebox.showwarning("启动", "请先在“连接配置”页填写两台调音台的 IP 地址。")
            return
        self.cfg = self._collect_config()
        self.runner = EngineRunner(self.cfg)
        self.runner.start()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self._log("镜像引擎启动中…")

    def _stop(self):
        if not (self.runner and self.runner.running):
            return
        if not messagebox.askyesno("停止", "确定停止镜像同步？两台调音台将各自独立运行。"):
            return
        self.runner.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self._log("镜像引擎已停止")

    def _on_close(self):
        if self.runner and self.runner.running:
            if not messagebox.askyesno("退出", "镜像正在运行，退出后将停止同步。确定退出？"):
                return
            self.runner.stop()
        self.destroy()

    def _resync(self):
        if not (self.runner and self.runner.running and self.runner.engine):
            messagebox.showinfo("全量对齐", "镜像未运行。")
            return
        eng = self.runner.engine
        loop = eng._loop  # noqa: SLF001 - deliberate re-entrant use

        async def job():
            if eng.pairmap_ab is None and eng.drv_a.key != eng.drv_b.key:
                log.warning("cross-brand pair without mapping: full sync skipped")
                return
            log.info("manual full sync from %s: %d paths", eng.a.name, len(eng.sync_paths))
            for path in eng.sync_paths:
                eng._send(eng.a, path, [])
                await asyncio.sleep(0.004)

        loop.call_soon_threadsafe(lambda: loop.create_task(job()))
        self._log("已请求全量对齐（A→B）")

    def _clear_log_view(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    # ---------- status polling ----------
    def _poll_status(self):
        running = bool(self.runner and self.runner.running)
        if running:
            eng = self.runner.engine
            if eng:
                role = "主机(ACTIVE)" if eng.active else "备机(STANDBY)"
                if not eng.ha:
                    role = "单机"
                alert = eng.link_alerted["a"] or eng.link_alerted["b"]
                color = "#c62828" if alert else ("#1a7f37" if eng.active else "#9a6700")
                self.lbl_status.configure(fg=color)
                self.var_status.set("● 链路告警 · 有调音台失联" if alert else f"● 运行中 · {role}")
                n = eng.stats.get("echo_n", 0)
                lat = (eng.stats.get("echo_ms_sum", 0.0) / n) if n else 0.0
                info = (f"模型: {eng.drv_a.key} ↔ {eng.drv_b.key}\n"
                        f"模式: {eng.sync_mode} (主机 {eng.master}) · 方向 {eng.direction}\n"
                        f"监听: :{self.cfg.get('listen_port', 10099)} (遥控端 {len(eng.clients)}/{eng.max_clients})\n"
                        f"同步延迟: {lat:.0f} ms (回声实测均值, {n} 样本)\n"
                        f"统计: 收 {eng.stats.get('received', 0)} / 转 {eng.stats.get('forwarded', 0)}"
                        f" / 抑制回声 {eng.stats.get('echo_suppressed', 0)}"
                        f" / 合并写入 {eng.stats.get('coalesced', 0)}"
                        f"{(' / 对账修复 ' + str(eng.stats.get('reconcile_fixes', 0))) if eng.stats.get('reconcile_fixes') else ''}"
                        f"{(' / 误操作回弹 ' + str(eng.stats.get('reverts', 0))) if eng.stats.get('reverts') else ''}"
                        f"{(' / 链路告警 ' + str(eng.stats.get('link_alerts', 0))) if eng.stats.get('link_alerts') else ''}\n"
                        f"参数覆盖: {len(eng.sync_paths)} 路 (含增益/发送/声像/静音组)")
                self.var_summary.set(info)
                for side, con in (("a", eng.a), ("b", eng.b)):
                    ok = con.last_seen is not None and (time.time() - con.last_seen) < eng.link_timeout
                    age = "无数据" if con.last_seen is None else f"{time.time() - con.last_seen:.1f}s 前"
                    mark = "● 在线" if ok else "● 失联"
                    line = f"{mark}\nIP: {con.host}:{con.port}\n最近消息: {age}"
                    self.var_info_a.set(line) if side == "a" else \
                        self.var_info_b.set(line)
            else:
                self.var_status.set("● 启动中…")
                self.lbl_status.configure(fg="#9a6700")
        else:
            if self.runner and self.runner.error:
                self.var_status.set("● 出错")
                self.lbl_status.configure(fg="#c62828")
                err = self.runner.error
                self.runner.error = None
                messagebox.showerror("引擎错误", err)
            else:
                self.lbl_status.configure(fg="#888888")
                self.var_status.set("● 未运行")
        self.after(1000, self._poll_status)

    # ---------- snapshot / cloud ----------
    def _pick_snapshot(self):
        path = filedialog.askopenfilename(title="选择快照文件",
                                          filetypes=[("JSON 快照", "*.json"), ("所有文件", "*.*")],
                                          initialdir=".")
        if path:
            self.var_snapfile.set(path)

    def _snap_summary(self, snap):
        paths = snap.get("paths") or {}
        ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(snap.get("ts", 0)))
        lines = [f"快照: {ts} · 模型 {snap.get('model')} · {len(paths)} 个参数", "-" * 60]
        for p in sorted(paths)[:12]:
            lines.append(f"  {p} = {paths[p]}")
        if len(paths) > 12:
            lines.append(f"  … 共 {len(paths)} 个参数")
        return "\n".join(lines)

    def _show_snap_info(self, text):
        self.snap_info.configure(state="normal")
        self.snap_info.delete("1.0", "end")
        self.snap_info.insert("1.0", text)
        self.snap_info.configure(state="disabled")

    def _do_snapshot(self):
        if self.runner and self.runner.running and self.runner.engine and self.runner.engine.state:
            snap = self.runner.engine.snapshot_dict()
            self._write_snapshot_file(snap)
            return
        # offline: spin a temp engine on a separate port and read state
        cfg = self._collect_config()
        cfg["listen_port"] = int(self.var_listen.get() or 10099) + 50
        cfg["full_sync"] = True

        def job():
            async def run():
                loop = asyncio.get_running_loop()
                eng = MirrorEngine(cfg)
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: eng, local_addr=(cfg["listen_host"], cfg["listen_port"]))
                await eng.start()
                await asyncio.sleep(3.0)
                snap = eng.snapshot_dict()
                await eng.stop()
                transport.close()
                return snap
            try:
                snap = asyncio.run(run())
                self.after(0, lambda: self._write_snapshot_file(snap))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("快照失败", str(exc)))

        threading.Thread(target=job, daemon=True).start()

    def _write_snapshot_file(self, snap):
        out = filedialog.asksaveasfilename(
            title="保存快照", defaultextension=".json",
            initialfile=f"snapshot-{time.strftime('%Y%m%d-%H%M%S')}.json",
            filetypes=[("JSON 快照", "*.json")])
        if not out:
            return
        with open(out, "wb") as fh:
            fh.write(cloud.snapshot_bytes(snap))
        self.var_snapfile.set(out)
        self.var_snap_last.set(f"上次快照: {time.strftime('%H:%M:%S')} · {len(snap.get('paths') or {})} 参数")
        self._show_snap_info(self._snap_summary(snap))
        self._log(f"快照已保存: {out}")

    def _save_cloud_cfg(self):
        if self.runner and self.runner.running:
            messagebox.showwarning("保存云端配置", "镜像运行中，请先停止再修改配置。")
            return
        self.cfg = self._collect_config()
        try:
            hours = float(self.var_cloud_hours.get())
        except ValueError:
            hours = 6.0
        cloud_cfg = dict(self.cfg.get("cloud") or {})
        cloud_cfg.update({
            "enabled": self.var_cloud_provider.get() != "local" or True,
            "provider": self.var_cloud_provider.get(),
            "dir": self.var_cloud_dir.get().strip(),
            "prefix": cloud_cfg.get("prefix", "x32mirror"),
            "interval_hours": hours,
        })
        self.cfg["cloud"] = cloud_cfg
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(self.cfg, fh, indent=2, ensure_ascii=False)
        self._log(f"云端配置已保存: {cloud_cfg.get('provider')}")

    def _do_upload(self):
        path = self.var_snapfile.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("上传云端", "请先拍摄快照或选择快照文件。")
            return
        cloud_cfg = self.cfg.get("cloud") or {}
        if not cloud_cfg:
            messagebox.showwarning("上传云端", "尚未配置云端存储。")
            return
        with open(path, "rb") as fh:
            body = fh.read()
        snap = cloud.load_snapshot(body)
        name = cloud.snapshot_name(snap.get("node", "node"))

        def job():
            try:
                cloud.upload(cloud_cfg, body, name)
                cloud.upload(cloud_cfg, body, "latest.json")
                self.after(0, lambda: self._log(f"已上传云端: {name} + latest.json"))
                self.after(0, lambda: messagebox.showinfo("上传云端", f"上传成功：\n{name}\nlatest.json"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("上传失败", str(exc)))

        threading.Thread(target=job, daemon=True).start()

    def _do_cloud_download(self):
        cloud_cfg = self.cfg.get("cloud") or {}
        if not cloud_cfg:
            messagebox.showwarning("云端", "尚未配置云端存储。")
            return

        def job():
            try:
                raw = cloud.download_latest(cloud_cfg)
                if raw is None:
                    self.after(0, lambda: messagebox.showwarning("云端", "云端没有快照或下载失败。"))
                    return
                snap = cloud.load_snapshot(raw)
                out = f"latest-snapshot-{time.strftime('%Y%m%d-%H%M%S')}.json"
                with open(out, "wb") as fh:
                    fh.write(raw)
                self.after(0, lambda: (self.var_snapfile.set(os.path.abspath(out)),
                                       self._show_snap_info(self._snap_summary(snap)),
                                       self._log(f"已从云端下载: {out}")))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("下载失败", str(exc)))

        threading.Thread(target=job, daemon=True).start()

    def _do_restore(self, dry):
        path = self.var_snapfile.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showwarning("恢复", "请先选择快照文件（或先从云端拉取最新）。")
            return
        try:
            with open(path, "rb") as fh:
                snap = cloud.load_snapshot(fh.read())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("恢复", f"读取快照失败: {exc}")
            return
        self._show_snap_info(self._snap_summary(snap))
        if dry:
            messagebox.showinfo("预览（干跑）",
                                f"快照包含 {len(snap.get('paths') or {})} 个参数。\n"
                                "以上为预览。确认无误后点【② 确认写台】。\n"
                                "注意：写台会覆盖两台调音台当前状态！")
            return
        if not messagebox.askyesno("确认写台",
                                   "⚠ 将把快照写回两台调音台，覆盖当前状态！\n\n"
                                   "建议先拍一张当前快照留还原点。\n\n确定继续？"):
            return
        cfg = self._collect_config()

        def job():
            try:
                n = restore_snapshot(cfg, snap)
                self.after(0, lambda: (self._log(f"恢复完成: {n} 个参数已写回两台调音台"),
                                       messagebox.showinfo("恢复完成", f"已写回 {n} 个参数到两台调音台。")))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("恢复失败", str(exc)))

        threading.Thread(target=job, daemon=True).start()


def run_gui(config_path=DEFAULT_CONFIG):
    app = MirrorGUI(config_path)
    app.mainloop()
