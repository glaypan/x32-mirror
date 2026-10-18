# x32-mirror（macOS 版）

支持 **macOS 10.14.6 Mojave 及以上**（Intel x86_64）。解压后把
`x32-mirror.app` 拖进「应用程序」文件夹即可，不需要安装 Python。

## 第一次打开（重要）

本程序未做 Apple 开发者签名，首次打开会被 Gatekeeper 拦截：

- 在 Finder 里 **右键点 `x32-mirror.app` → 打开 → 再点「打开」**；或
- 终端执行一次：`xattr -dr com.apple.quarantine /Applications/x32-mirror.app`

之后就能正常双击启动。

## 使用

1. 打开后在工作台「01 调音台」填两台调音台的 IP（端口默认 10023，WING 为 2223）。
2. 选择同步模式（单控台 / 双控台全镜像 / 双控台显示独立），点「启动镜像」。
   启动会先做安全检测（预检 → 对齐 → 读回核对），完成后提示「可以操作调音台」。
3. 没有真机时，终端运行
   `/Applications/x32-mirror.app/Contents/MacOS/x32-mirror --demo`
   可启动两台模拟调音台体验全部功能。

## 配置与数据放在哪

macOS 不允许往 .app 内部写文件，配置与数据都在：

```
~/Library/Application Support/x32-mirror/
├── config.json      # 调音台 IP、同步模式、热备、云备份
├── snapshots/       # 快照
└── oplog.sqlite     # 操作日志（断线补发用）
```

升级时替换 .app 即可，这个目录会保留。

## 网络

- 调音台用 DHCP 或静态 IP 都可以，程序只认界面里填的地址；地址会变的话建议
  在路由器做 DHCP 保留。
- 双机热备：在 `config.json` 的 `ha` 里填 `peer_host`（对方电脑 IP），
  `node_id` 两台不能相同。
- 首次运行如弹出防火墙提示，请允许传入连接（手机页与热备心跳需要）。

## 命令行

```
/Applications/x32-mirror.app/Contents/MacOS/x32-mirror --version
/Applications/x32-mirror.app/Contents/MacOS/x32-mirror run --config ~/Library/Application\ Support/x32-mirror/config.json
```
