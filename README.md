# 卧室温湿度看板

> 本仓库还有一个 **[体重看板](weight_tracker/README.md)**：给家里那台 Greater Goods 体重秤用，手动记录，自动算每周 / 每月平均和体重趋势。

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

> **macOS**：第一次运行时系统会询问“终端”能否使用蓝牙，需要允许。macOS 不显示蓝牙 MAC 地址，`--scan` 里看到的是一串 UUID，用名字指定更方便。

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
