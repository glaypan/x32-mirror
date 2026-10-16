# x32mirror — 数字调音台实时镜像同步工具

在一台调音**台上操作（推子、静音、通道名等），另一台实时执行同样操作；两台可互为镜像（双向）。纯 Pytho**n 标准库实现，零第三方依赖。

当前适配 **Behringer X32 / Midas M32** 的 OSC 远控协议（UDP 10023），其他型号在 `engine.py` 中替换路径表即可。

## 支持的调音台（驱动注册表 `x32mirror/drivers.py`）

| 品牌 / 型号                           | 协议                                                                | 端口                  | 状态                                |
| --------------------------------- | ----------------------------------------------------------------- | ------------------- | --------------------------------- |
| Behringer **X32** 全系              | OSC over UDP，`/renew` 订阅推送                                        | 10023               | ✅ ready（当前默认）                     |
| Midas **M32** 全系                  | 与 X32 同协议同端口，路径基本一致                                               | 10023               | ✅ ready                           |
| Behringer **WING** 全系             | OSC over UDP，官方授权文档完整；推子 `/fdr` 为 dB（-144=-∞），静音 int              | 2223（TCP 2222 为控制面） | ✅ ready（经映射层与 X32/M32 互通）         |
| Allen & Heath **SQ**              | MIDI over TCP（NRPN/CC，官方 External Control/Crestron 驱动同源）          | 51325               | 📋 planned                        |
| Allen & Heath **Qu**              | CMNet（UDP，社区逆向）+ MIDI over TCP                                    | 51325/UDP           | 📋 planned                        |
| Allen & Heath **dLive / Avantis** | MIDI over TCP                                                     | 51325               | 📋 planned                        |
| Yamaha **TF / CL / QL / DM3**     | RCP 文本协议 over TCP：`get/set/ssrecall_ex`，**NOTIFY 主动推送**；dB×100 整数 | 逐机型实测               | 📋 planned                        |
| Yamaha **RIVAGE PM / DM3**        | 官方 OSC Specifications（PM V1.0.2 / DM3 V1.0.0）                     | 按规格                 | 📋 planned                        |
| DiGiCo **SD / Quantum / S**       | 无整机状态远程协议；Generic OSC 仅每通道 8 旋钮 + 8 开关外控且不支持轮询                    | —                   | ⛔ 实时整机镜像不可行，退化为 **session 文件级备份** |
| Soundcraft / PreSonus             | Vi/Si 走 MIDI/专有；StudioLive UCNet 闭源                               | —                   | 📋 待调研                            |

**使用方法**：推荐在 `config.json` 的每台调音台下写 `"driver": "auto"`——启动镜像时自动向该台发 OSC `/xinfo` 探测，从应答的型号字符串识别 X32 / M32 / WING 并自动套用对应驱动、协议端口与跨品牌参数映射；识别不出时回落 x32 并在日志中说明。GUI 里也可以点"🔍 自动检测型号"按钮手动探测（成功后自动回填驱动与端口），或手动指定 `"driver": "m32"`（等）；未声明默认 `x32`。手机网页控制台同样支持：`GET /api/detect?host=<调音台IP>`。

**规范映射层（`x32mirror/mapping.py`）**：跨家族配对时，参数先归一为"规范参数"（`通道/总线/DCA/主输出 × 推子/静音/名称`），推子统一为 **dB** 再换算到目标机型：

- X32/M32 位置值 0–1 ↔ dB 走官方分段线性曲线（0.0=-∞ / 0.0625=-60 / 0.25=-30 / 0.5=-10 / 0.75=0 / 1.0=+10）
- WING 原生 dB（-144 代表 -∞）
- 同步覆盖差异自动处理：WING 有 40 通道/16 DCA/aux，X32 只有 32 通道/8 DCA——多出的通道不映射不报错
- 长期跨品牌扩展：新品牌只需实现"路径解析/构建 + 取值换算"挂进注册表，引擎不用改

**已验证**（离线自检，全部 PASS）：

- `python -m x32mirror simulate` —— X32↔X32 同族双向镜像
- `python -m x32mirror simulate-cross` —— X32↔WING 跨族映射，146 个语义参数（dB 归一后）完全收敛
- `python -m x32mirror simulate-ha` —— 四阶段：自动选举 + 崩溃自动接管 + 手动切主（promote）+ 手动切回（demote）
- `python -m x32mirror simulate-proxy` —— 遥控 App 代理：xinfo 发现、App 写入双台同步、台上操作回显 App、双 App 互同步
- `python test_autodetect.py` —— 驱动自动探测：型号识别（X32/M32/WING/未知）、探测（含死端口）、双 auto 引擎自动套用驱动与映射并完成全量对齐

**协议查证来源**：WING 官方 OSC 文档（wing-docs.com，Behringer 授权 P-G. Maillot 维护）；A\&H 官方 External Control 文档与 SQ MIDI Protocol（MIDI over TCP 51325）；Yamaha RCP 见 BrenekH/yamaha-rcp-docs（TF/CL/QL/DM3）及官方 RIVAGE PM/DM3 OSC 规格；DiGiCo 官方 "Generic OSC control" 公告。

## 快速开始

### 方式〇：命令行一键安装（推荐）

装一次，之后处处可用：

- **Windows**：双击 **`install.bat`**
- **macOS（10.14.6+）**：双击 **`install.command`**（首次如无权限，先执行一次 `chmod +x install.command`）

它会自动完成：① 在项目目录创建 `x32mirror` 命令行入口并**加入用户 PATH**（无需管理员）；② 桌面创建 **`X32-Mirror GUI`**（双击弹图形界面）与 **`X32-Mirror Web`**（双击启动镜像+手机控制台）快捷方式；③ Windows 上可加 `--autostart` 注册**登录自启**（开机后台运行镜像+手机网页控制台，无窗口）。

安装后在任意**新开的**终端里：

```bash
x32mirror                    # 弹出图形界面
x32mirror web --autostart    # 镜像 + 手机网页控制台
x32mirror --help             # 全部命令
```

卸载：`python -m x32mirror uninstall`（只移除入口/快捷方式/PATH 项，项目文件保留）。预览模式：`install --dry-run` 只打印将要做的事，不改系统。

### 方式一：图形界面（零安装直接用）

**默认弹出全新 macOS 风格界面**（毛玻璃材质 / 亮暗色自动适配 / 8 种强调色 / SF 字体 / 实时同步通道可视化 / 圆角窗口与红绿灯按钮）：

**Windows**：双击 **`启动界面.bat`**（或运行 `python -m x32mirror`，不带参数即弹 GUI）。

**macOS（最低 10.14.6 / Mojave）**：
1. 到 [python.org](https://www.python.org/downloads/) 安装 **Python 3.12 或 3.13**（安装包自带 tkinter；两者官方均支持 macOS 10.14.6——3.12 支持 10.9+，3.13 支持 10.13+）
2. 双击 **`启动界面.command`**。若提示"无法打开因为无法验证开发者"或没有执行权限，在终端执行一次：
   ```bash
   cd x32-mirror && chmod +x 启动界面.command && ./启动界面.command
   ```
   之后即可直接双击。工具本身是纯标准库 Python，无需安装任何第三方包。

新界面通过 pywebview 渲染本地页面（Windows 用 WebView2，macOS 用 WKWebView），需要额外装一个可选依赖：

```bash
pip install pywebview        # 只有新界面需要；不装也能用
```

- `python -m x32mirror gui` —— 新界面（默认）
- `python -m x32mirror gui --browser` —— 新界面改用系统浏览器打开（无 pywebview 时）
- `python -m x32mirror gui --classic` —— 经典 tkinter 界面（纯标准库，任何环境都能跑）

新界面六个页面：**运行状态**（实时同步通道可视化 + 两台调音台链路健康 + 统计磁贴）、**连接配置**、**双机热备**（角色 / Epoch / 对端状态 + 手动升主让位）、**备份恢复**（快照 / 预览 / 写台 / 云备份）、**实时日志**、**使用说明**。

经典 tkinter 界面共 7 个标签页：

| 标签页 | 用途 |
|---|---|
| **运行状态** | 启动/停止镜像、两台调音台在线状态、收/转/回声抑制统计、手动全量对齐 |
| **连接配置** | 填两台调音台的 IP/端口/型号驱动（默认 auto 自动探测，可下拉手选或点"自动检测型号"按钮，自动显示协议与端口）、同步方向、保存 config.json |
| **快照与恢复** | 拍快照 → 上传云端；从云端/本地选快照 → 预览（干跑）→ 确认写台；云端存储配置 |
| **操作日志** | 引擎实时日志（连接、转发、错误全在这里） |
| **使用说明** | 内置完整上手指南（准备工作 → 配置 → 启动 → 遥控软件 → 快照恢复 → 双机热备） |
| **注意事项** | 10 条关键提醒：先空场测试、恢复会覆盖当前状态、避免双台同时操作同一路径、防火墙放行等 |
| **常见问题** | 启动后没反应排查、推子误差说明、场景同步、多台扩展等 |

GUI 启动引擎在后台线程运行，关窗口前会确认；恢复写台强制"预览 → 确认"两步，防误操作。

> 注：经典 GUI（`--classic`）用 Python 自带的 tkinter，Windows 官方安装的 Python 均内置；若提示 `No module named tkinter`，重装 Python 时勾选 tcl/tk 组件即可。命令行模式无此要求。

### 方式二：命令行

```bash
python -m x32mirror run            # 命令行运行镜像
python -m x32mirror snapshot       # 手动快照
python -m x32mirror restore --file latest --yes
```

```bash
# 1. 离线自检（两台模拟调音台 + 镜像引擎，验证端到端同步）
python -m x32mirror simulate

# 2. 修改 config.json 中的两台调音台 IP（X32 默认远控端口 10023）
# 3. 接真机运行（前台常驻，Ctrl+C 退出）
python -m x32mirror run --config config.json
```

### 方式三：手机访问（安卓 / iPhone，无需装 App）

工具内置**手机网页控制台**，手机浏览器直接操作，无需安装任何 App：

```bash
python -m x32mirror web --http-port 8080 --autostart
```

启动后控制台会打印实际访问地址（形如 `http://192.168.1.50:8080`），手机连同一 WiFi 用浏览器打开即可：

| 手机端功能 | 说明 |
|---|---|
| 状态监控 | 主机/备机角色、两台调音台在线状态（在线/迟缓/失联）、转发统计，每 2 秒自动刷新 |
| 启动 / 停止镜像 | 手机上一键操作 |
| 修改配置 | 直接改两台调音台的 IP/端口/型号并保存（换场地最常用） |
| 快照与恢复 | 拍快照、浏览快照列表、下载快照、预览（干跑）→ 确认写台，两步防误操作 |
| 实时日志 | 手机上滚动查看引擎日志 |
| 内置说明 | 使用说明 / 注意事项 / 常见问题与桌面版一致 |

典型用法：电脑开机跑 `web` 常驻，演出期间用手机随时看两台调音台是否在线、有没有在正常转发；出状况时手机上直接拍快照或一键恢复。

> 提示：手机与电脑必须在同一局域网；首次运行请放行防火墙 8080/TCP。双机热备时手机连当前 ACTIVE 节点。

## 配置项（config.json）

| 字段                 | 说明                                          |
| ------------------ | ------------------------------------------- |
| `listen_port`      | 本机监听端口，任意空闲端口（默认 10099）                     |
| `consoles.a / b`   | 两台调音台的 name / host / port                   |
| `direction`        | `both` 双向互为镜像；`a_to_b` 仅 A→B；`b_to_a` 反向    |
| `full_sync`        | 启动时从 `full_sync_from` 台全量读取 146 个基础路径并同步到对端 |
| `extra_sync_paths` | 额外要同步的路径（如效果器、路由参数）                         |
| `echo_window_s`    | 回声抑制窗口，防止 A→B→A 死循环                         |
| `oplog_db`         | SQLite 操作日志文件（WAL 模式），审计与追溯用                |
| `ha`               | 双机热备（见下节），不启用则单机运行                          |

## 双机热备（两台电脑部署）

用两台电脑跑同一个工具、接同一对调音台，实现**镜像链路自身的实时备份**（工具所在电脑不再是单点故障）：

1. 两台电脑的 `config.json` 相同，仅 `ha` 节不同：

```json
"ha": {
  "enabled": true,
  "node_id": "pc-1",              // 另一台写 pc-2，两台不能重复
  "peer_host": "192.168.1.50",    // 对方电脑的 IP
  "port": 49900,                  // 心跳端口，两台一致
  "failover_s": 3.0,              // 判定对方死亡的秒数
  "auto_resume_s": 30.0           // demote 后对方也宕机，等待多久自动恢复主
}
```

2. 运行方式与单机完全一样：`python -m x32mirror run --config config.json`。

**工作机制**：

- 两机每秒互发 UDP 心跳，**先启动的/时间戳更早的成为主机**（active），负责转发；另一台为备机（standby）
- 备机同样订阅两台调音台并把每条变更**实时写入自己的 op-log**——即第二台电脑上始终有一份实时备份的操作记录
- 主机宕机（心跳中断 3 秒）后备机**自动接管**：重新订阅 + 全量基线对齐 + 开始转发，恢复镜像，全程无需人工干预
- 崩溃主机重启后自动以备机身份待命（不会抢回控制权），避免双主脑裂
- 备机也宕机则无镜像（两台调音台各自独立运行，不受影响）

**手动切换**（维护、迁移、有意换主机时用，对目标电脑的 IP 执行）：

```bash
# 查看某台电脑上节点的当前角色
python -m x32mirror ha-switch status --host 192.168.1.51

# 手动切主：把 192.168.1.51 上的节点升为主机（原主机自动让位为备机）
python -m x32mirror ha-switch promote --host 192.168.1.51

# 手动让位：把 192.168.1.51 上的节点降为备机（对端自动接管为主机）
python -m x32mirror ha-switch demote --host 192.168.1.51
```

- `promote` 通过内部 epoch 优先级压过自动选举，立即生效并触发全量基线对齐；**不持久化**——该节点重启后回到自动选举
- `demote` 后该节点在对端存活期间保持备机；安全兜底：若对端之后也宕机，等待 `auto_resume_s`（默认 30 秒）自动恢复主，避免镜像长时间中断
- 两台电脑都要放行该 HA 端口的 UDP 入站（与心跳同端口，默认 49900）

**注意**：两台必须同时启用或同时停用 `ha`；心跳端口若被 Windows 保留端口段占用（WinError 10013），换一个 `port` 即可。

## 工作原理

1. **订阅**：每 9 秒向两台调音台发送 `/renew`，保持它们把所有变更主动推送到本工具。
2. **捕获**：收到某台推送的参数变更（路径 + 值），先记入 op-log。
3. **转发**：立即把同一 OSC 消息写到另一台 → 对端执行相同操作。
4. **回声抑制**：本工具写入对端后，对端也会把这条变更广播回来；1 秒窗口内"同主机 + 同路径 + 同值"的消息被识别为回声，不再转发，杜绝死循环。
5. **全量同步**：启动时向主台逐条发送读请求（无参数 OSC 消息），回复值经转发通路自动写入对台，两台基线对齐。
6. **存活监控**：每 10 秒输出链路状态（最后消息时间）与转发/抑制计数；单台掉线不影响另一台。

## 已验证行为（simulate 自检）

- 双向操作 12 秒：两台状态完全收敛一致（PASS）
- 全量基线同步 146 路径
- 回声抑制有效：307 收 / 154 转 / 152 抑制，无转发循环

## 遥控 App 同步（Mixing Station / X32-Edit / iPad 遥控）

**内置客户端代理（虚拟调音台）模式，默认开启**。工具在本机监听一个 OSC 端口（`listen_port`，默认 10099，可改成 10023 更有"真台"的感觉），对外表现就像一台虚拟 X32：

- **Mixing Station / X32-Edit / X32-Mix (iPad)** 等任何 X32 OSC 遥控端，把连接地址从"调音台 IP"改成"**运行本工具的电脑 IP + listen_port**"即可
- App 上的操作会推到**两台调音台**（自动做跨机型换算）；台上物理操作、另一个 App 的操作也会**实时回显**到所有已连接的 App
- `xinfo` 发现、`/renew` 订阅、读参数、meters 订阅（blob 透传）都按 X32 协议应答，App 端识别为普通 X32
- 最多 `max_clients`（默认 8）个遥控端同时在线；闲置 `client_timeout_s` 秒自动剔除
- 双机热备时：**App 应连当前 ACTIVE 节点**；备机上的连接为只读镜像视图（写操作会被忽略并告警），主机切换后把 App 指向新主机即可

也可不经过代理、让 App 直连调音台 A：由于调音台会把所有变更广播给本工具，App 的操作同样会同步到 B 台（但 App 只能"看到"A 台视角，且 A 台掉线时 App 失联——推荐走代理）。

**限制**：代理面向 OSC 家族（X32/M32/WING）；X32↔WING 配对时 App（X32 协议）写参数会自动换算到 WING，读值以 A 台（X32）视角返回。

## 云端备份（云服务器 / 对象存储 / 网盘）

**定位**：实时镜像必须在局域网内（OSC 是 UDP，公网延迟与丢包不适合实时同步）；**备份与恢复走云端**——工具定期把全量状态快照上传到云，事故后可从云端一键恢复到两台调音台。

**快照内容**：引擎实时状态缓存的全部已同步路径（推子/静音/通道名等，默认 146 路），JSON 格式，云端保留滚动历史（`snapshots/<节点>/<时间>.json`）+ 始终最新的 `latest.json`。

**三种存储 provider（纯标准库实现）**：

| provider | 适用 | 配置要点 |
| --- | --- | --- |
| `s3` | AWS S3、阿里云 OSS（S3 兼容）、腾讯云 COS（S3 兼容）、MinIO、Backblaze B2 | `endpoint/region/bucket/access_key/secret_key`，SigV4 签名 |
| `webdav` | Nextcloud、群晖/威联通 NAS、各类网盘 | `endpoint/username/password` |
| `local` | 本机/NAS 挂载目录（也用于离线自检） | `dir` |

**两种用法**：

1. **自动定时上传**：`config.json` 的 `cloud.enabled: true` + `interval_hours: 6`，运行中的镜像引擎每 6 小时自动上传快照（双机热备时仅 ACTIVE 节点上传，不会重复）
2. **手动**：
   ```bash
   python -m x32mirror snapshot --config config.json          # 立即快照并上传
   python -m x32mirror snapshot --listen-port 10199           # 镜像正运行时换个端口抓快照
   python -m x32mirror restore --file latest --yes            # 从云端拉取最新快照一键恢复
   python -m x32mirror restore --file snapshot-xxx.json       # 从本地文件恢复（默认干跑，--yes 才写）
   python -m x32mirror cloud-download --out backup.json       # 只下载不恢复
   ```

**安全机制**：`restore` 默认干跑（只列出将写回的参数），加 `--yes` 才真正写台；恢复按限速逐条写两台（跨机型配对自动换算取值）；建议演出前 `snapshot` 一次作为还原点。

**已验证**（`simulate-cloud` 离线自检）：快照 146 路 → 上传 → 下载校验一致 → 打乱两台调音台状态 → 一键恢复 → 双台与快照 0 差异，PASS。

## 已知限制（对应设计文档的阶段 3→4）

- 冲突策略：双向同时操作同一路径为 last-write-wins，无仲裁 UI
- 推子高速拖动按原样逐条转发，未做同路径值合并（带宽富余时可忽略）
- 未含场景库（snapshot）整库复制、定时备份、恢复点；见《系统设计与技术方案》阶段 2/4
- X32 部分参数（效果器内部、路由矩阵）未纳入默认同步路径，用 `extra_sync_paths` 扩展

## 部署建议

- 本工具与两台调音台处于同一二层网络（直连交换机口即可），PC 固定 IP
- Windows 首次运行需允许 Python 的 UDP 入站（防火墙提示）
- 生产环境建议用 NSSM / systemd 注册为服务常驻
