# 卧室温湿度看板

在手机或平板上实时查看卧室的温度和湿度，保存历史曲线，并能和另一台温度计对比，判断读数准不准。

![看板截图](docs/screenshot.png)

## 家里这两台温度计能不能读到数据？

| 设备 | 能否自动读取 | 原因 |
|---|---|---|
| **Govee H5075**（[B07Y36FWTT](https://www.amazon.com/dp/B07Y36FWTT)） | ✅ 可以 | 它大约每 2 秒用蓝牙广播一次温度、湿度和电量，任何带蓝牙的电脑都能直接收到，**不需要配对，不需要 Govee 账号或云端**。 |
| **AcuRite 01083M**（[B01HDW58GS](https://www.amazon.com/dp/B01HDW58GS)） | ❌ 不行 | 它只有一块液晶屏，没有蓝牙、Wi‑Fi 或任何数据接口。看板里可以**手动填写**它的读数，用来和 Govee 对比准确度。 |

所以看板的数据来自 Govee；AcuRite 留在旁边当“参照物”。

## 需要什么

- 一台**带蓝牙、放在卧室附近**的电脑，一直开着：树莓派（3B+/4/5/Zero 2 W 都行）、Mac 或 Windows/Linux 电脑。蓝牙穿墙后距离会缩短，最好在 10 米以内。
- Python 3.10 或更新版本。
- 看板在局域网里提供网页，家里任何手机、平板、电脑的浏览器都能打开。

## 快速开始

```bash
git clone <本仓库> && cd <仓库目录>
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 1. 不接传感器，先用模拟数据看看效果
python -m bedroom_climate --demo
#    打开 http://localhost:8000

# 2. 找到你的 Govee（列出附近所有 H5075，以及它们当前的读数）
python -m bedroom_climate --scan

# 3. 正式运行
python -m bedroom_climate
#    手机上打开 http://<这台电脑的局域网 IP>:8000
```

不加 `--device` 时，程序会锁定**第一台**收到广播的 H5075。如果邻居或家里其他房间也有 Govee，用 `--scan` 看到的名字或地址指定：

```bash
python -m bedroom_climate --device GVH5075_1A2B   # 名字的一部分也行，例如 --device 1A2B
```

> **macOS**：从终端直接运行可能会因为蓝牙权限被系统杀掉（`Abort trap: 6`），请看下面的[在 Mac 上常驻](#在-mac-上常驻)。macOS 不显示蓝牙 MAC 地址，`--scan` 里看到的是一串 UUID，用名字指定更方便。

## 看板上有什么

- **当前温度和湿度**，以及是否在建议范围内（温度默认 15.6–19.4 °C / 60–67 °F，湿度默认 30–50%，依据见下方“参考资料”）。
- **6 小时 / 24 小时 / 7 天 / 30 天曲线**，灰色区域是建议范围；鼠标悬停或手指按住可查看任意时刻的读数，下方“数据表”里有全部数值。
- **与 AcuRite 对比**：把 AcuRite 屏幕上的数字填进去，自动和同一时刻的 Govee 读数配对，算出两台平均差多少、是否在两台的标称误差之内。
- °C / °F 切换、深色模式、手机布局。

传感器的电量、蓝牙信号强度、最后更新时间显示在标题下方；超过 5 分钟没收到信号会提示。

## 准不准？怎么校准

简短结论：两台都是比较准的型号。Govee H5075 标称 ±0.3 °C、±3% RH，AcuRite 01083M 标称 ±0.2 °C（±0.5 °F）、±2% RH。但这是新机在典型条件下的指标，单台会有偏差，湿度传感器用久了也会漂移；放的位置不对（晒太阳、靠近空调出风口或电器）带来的误差往往比传感器本身更大。

完整的检验步骤见 **[docs/accuracy.md](docs/accuracy.md)**：并排对比 → 盐水测试（75% 湿度基准）→ 把偏差写进看板。

校准偏移在启动时设置，会同时修正历史数据（数据库里存的是原始读数）：

```bash
python -m bedroom_climate --temp-offset -0.3 --humidity-offset 2.5
```

> Govee App 里也能设置校准，但据用户反馈那只改 App 里的显示，不会改变蓝牙广播出来的数值，所以要在这里另外设置。

## 所有参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--demo` | | 用模拟数据运行，不需要蓝牙 |
| `--scan` | | 列出附近的 Govee H5075 后退出 |
| `--device` | 第一台收到的 | 传感器地址，或名字的一部分 |
| `--db` | `climate.db` | SQLite 数据库文件 |
| `--host` | `0.0.0.0` | 监听地址；默认整个局域网可访问，只想本机访问用 `127.0.0.1` |
| `--port` | `8000` | 网页端口 |
| `--interval` | `60` | 每隔多少秒存一条数据 |
| `--temp-offset` | `0` | 温度校准偏移（°C） |
| `--humidity-offset` | `0` | 湿度校准偏移（%RH） |
| `--temp-range` | `15.56,19.44` | 建议温度范围（°C），例如 `--temp-range 18,22` |
| `--humidity-range` | `30,50` | 建议湿度范围（%RH） |

看板没有登录功能，局域网里的人都能看到并添加对比记录。不要把端口映射到公网。

## 在树莓派上开机自启

`/etc/systemd/system/bedroom-climate.service`（把路径和用户名换成你的）：

```ini
[Unit]
Description=Bedroom climate dashboard
After=bluetooth.target network-online.target
Wants=bluetooth.target

[Service]
User=pi
WorkingDirectory=/home/pi/bedroom-climate
ExecStart=/home/pi/bedroom-climate/.venv/bin/python -m bedroom_climate --db /home/pi/bedroom-climate/climate.db
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now bedroom-climate
journalctl -u bedroom-climate -f   # 查看日志
```

## 在 Mac 上常驻

已在 Mac mini（Apple 芯片，macOS 26.5，bleak 3.0.2）上实测。macOS 上有几处坑，`mac/step.sh` 都处理好了。每一步的输出也会存到 `mac/logs/<步骤>.log`：

```bash
mac/step.sh env                      # 找 Python ≥ 3.10，建 .venv，安装依赖，跑测试
mac/step.sh app                      # 编译 mac/build/BedroomClimate.app（需要 Xcode 或命令行工具）
mac/step.sh scan                     # 通过这个 App 扫描附近的 H5075，显示原始广播数据
mac/step.sh agent-install 2186 app   # 装成 LaunchAgent：登录后自动运行，退出后自动重启
mac/step.sh agent-status             # 是否在运行、最新读数、日志末尾
mac/step.sh agent-restart            # launchctl kickstart -k 重启，并检查能否恢复
mac/step.sh info                     # 局域网链接、防火墙和睡眠设置（只读）
mac/step.sh agent-uninstall          # 停止并删除 LaunchAgent
```

`2186` 换成你的传感器名字的一部分（见 `scan` 的输出）。数据库在 `~/Library/Application Support/bedroom-climate/climate.db`，日志在 `~/Library/Logs/bedroom-climate.log`。每存一条读数，日志里就记一行 `Saved ...`，一天大约 150 KB，不会自动轮转，太大了可以直接清空：`: > ~/Library/Logs/bedroom-climate.log`。

### 踩过的坑

1. **在 Warp 里直接运行 `python -m bedroom_climate`，进程会被系统杀掉（`Abort trap: 6`）。** 一个进程想用蓝牙，macOS 要求对它“负责”的那个 App 在 Info.plist 里写有 `NSBluetoothAlwaysUsageDescription`，并且用户允许过；否则直接 SIGABRT。从终端启动时，负责的 App 是终端本身，而 Warp 没有这一项（iTerm2 有）。在 Warp 里直接执行 `.app` 里面的可执行文件也不行，负责的 App 仍然是 Warp。解决办法是用 `mac/launcher.c` 和 `mac/Info.plist` 编一个带蓝牙用途说明的小 App（ad-hoc 签名），再由它启动 python。前台运行时用 `open -W -n -g -a BedroomClimate.app --args ...`（`step.sh scan` 就是这样做的），后台由 launchd 直接启动这个 App。系统如果弹出蓝牙权限请求，点“允许”。
2. **`--scan` 明明有信号，却显示 “No Govee H5075 found”。** H5075 在 Govee 自己的数据（公司 ID `0xEC88`）之外，另一个广播包里还带一段 Apple iBeacon（UUID 是 ASCII 的 `INTELLI_ROCKS_HW`）。CoreBluetooth 会把这两段厂商数据拼成一个值交给 bleak，程序收到的就是 31 字节，而不是 6 字节，旧的解析器会把它当成无效数据。现在 `govee.py` 会先去掉末尾的 iBeacon 部分；`tests/test_govee.py` 里收了一条真机数据。
3. **后台服务只在启动时收到一条读数，之后就不更新了。** CoreBluetooth 默认会过滤重复广播：同一次扫描里，每台设备只报告一次，之后只有广播内容变了（温度或湿度变化 0.1）才会再报告。bleak 3.0.2 没有打开 `CBCentralManagerScanOptionAllowDuplicatesKey`，所以卧室温度稳定时 Mac 什么也收不到，“最后更新”越来越旧，5 分钟后看板就提示没信号了；旧版本还会把同一条读数每分钟重复存一遍。现在分两层处理：
   - 每次开始扫描后，再用 `AllowDuplicates` 选项调用一次 `scanForPeripheralsWithServices:options:`，让 CoreBluetooth 上报每一条广播。bleak 没有提供这个参数，所以要通过它的内部对象 `scanner._backend._manager.central_manager` 去调；以后 bleak 改了内部结构，就自动退回到下面那一层。
   - 连续 20 秒没有新广播，就停止扫描再重新开始，新的一次扫描只要收得到，就会再报告一次传感器。实测只靠这一层时，重新扫描后常常要等一两轮才再次收到广播，存下的读数有 40–56 秒旧，离漏掉一分钟只差一点，所以两层都留着。整个运行期间只用一个 `BleakScanner` 反复 start/stop，因为在 macOS 上每新建一个 scanner 就会新建一个 CBCentralManager。

   同一条广播不会重复存储。Linux 上广播会源源不断地进来，不会触发重新扫描。
4. **隔着墙时，Mac 只能收到传感器很少一部分广播。** 传感器放在卧室（-67 到 -83 dBm），用一个允许重复上报的扫描诊断了 90 秒：这段时间 CoreBluetooth 每 10 秒能上报附近设备 160–430 次，这台 H5075 却只被听到 1 次，同一时间后台服务也没收到。可见问题出在接收这一层（距离、墙，或者传感器本身发得不够勤），既不是软件在过滤，也不是解析出了错。实测 12 分钟里有 10 分钟存到了新数据，偶尔会有一两分钟没有。没收到新广播的那一分钟不会写入数据库，日志里会记一条 `WARNING No new broadcast ...`，曲线上就是少一个点。想要更密的数据，就缩短传感器和 Mac 之间的距离，或者减少中间的墙。
5. **LaunchAgent 要在你登录以后才会运行。** Mac 重启后，要先登录一次才会开始采集。

## 已经在用 Home Assistant？

Home Assistant 自带 [Govee Bluetooth 集成](https://www.home-assistant.io/integrations/govee_ble/)，能直接识别 H5075，这种情况下不必再运行本程序。本程序适合不想装 Home Assistant、只要一个卧室看板的情况。

## 开发

```bash
python -m unittest        # 测试不需要蓝牙
```

代码结构：

- `bedroom_climate/govee.py`：解析 H5075 蓝牙广播
- `bedroom_climate/collector.py`：蓝牙扫描，每分钟存一条
- `bedroom_climate/store.py`：SQLite 存储
- `bedroom_climate/server.py`：网页和 JSON 接口（`/api/latest`、`/api/history?hours=24`、`/api/checks`、`/api/config`）
- `bedroom_climate/static/index.html`：看板页面（无外部依赖，离线可用）

## 参考资料

- H5075 广播格式：[Bluetooth-Devices/govee-ble](https://github.com/Bluetooth-Devices/govee-ble)（Home Assistant 使用的解析库）。本项目的解析结果与它在 20 万组随机数据上逐一核对一致。
- Govee H5075 精度：[Govee 产品页](https://eu.govee.com/products/govee-bluetooth-hygrometer-thermometer-h5075)
- AcuRite 01083M 精度：[AcuRite: What are the Accuracy Standards?](https://support.acurite.com/hc/en-us/articles/360007659854-What-are-the-Accuracy-Standards)
- 睡眠温度和湿度建议：[Sleep Foundation: Humidity and Sleep](https://www.sleepfoundation.org/bedroom-environment/humidity-and-sleep)
