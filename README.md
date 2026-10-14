# Web Project Mockup & Poster Generator

网页项目宣传海报与样机生成工具（CLI）。

自动通过无头 Chrome/Chromium 截取高分辨率视口，合成为包含 **macOS 风格浏览器视窗** 与 **抗锯齿手机样机** 的宣发海报，并注入 **标准 sRGB / ICC 色彩元数据** 防止广色域屏幕偏色。

---

## 核心特性

- **桌面端浏览器样机**：macOS 视窗风格，包含标准三色控制按钮、居中地址栏、HTTPS 锁图标与自定义域名。
- **移动端手机样机**：
  - **4x SSAA 超采样抗锯齿**：外边框与内屏圆角经 Lanczos 滤波光栅化，边缘平滑无阶梯。
  - **规范状态栏**：54pt 顶部安全区；灵动岛包含镜头光学反光与传感器开孔；时间采用 MiSans VF 亚像素级垂直居中；信号柱、Wi-Fi 与电池图标线宽协调且保持等距排布。
  - **智能明暗自适应**：自动采样页面顶部背景无缝延伸，依据感知亮度自动切换黑白图标。
  - **底部手势条**：34pt 底部安全区，居中绘制半透明自适应 Home Indicator。
- **色彩管理保护**：内嵌 `sRGB`、`gAMA`、`cHRM` 与 `iCCP` 元数据块，杜绝 HDR / DCI-P3 广色域屏幕下的偏色泛灰。
- **零额外重型框架**：基于 Python 3 + `Pillow`，调度本地 Chromium / Google Chrome 执行 2x Retina 截屏。

---

## 环境依赖

安装图像处理库 `Pillow`：

```bash
pip install Pillow
```

系统需安装 Chromium 或 Google Chrome（支持 Linux、macOS、Windows 自动探测）。

---

## 使用示例

### 1. 抓取网页并生成海报与样机

```bash
python3 tools/mockup-generator/generate.py \
  --url "http://localhost:4173/" \
  --site-url "font.yukonga.top"
```

输出文件：
- `screenshot_poster.png`：桌面视窗 + 悬浮手机组合海报
- `screenshot_widescreen.png`：纯净 2x Retina 宽屏截图
- `screenshot_mobile.png`：独立手机样机展示图

### 2. 使用本地已有截图直接合成

```bash
python3 tools/mockup-generator/generate.py \
  --widescreen-input "desktop.png" \
  --mobile-input "mobile.png" \
  --site-url "myapp.com" \
  --bg "#ffffff"
```

---

## 参数列表

| 参数 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `--url` | `http://localhost:4173/` | 截取目标网页地址 |
| `--site-url` | `font.yukonga.top` | 浏览器地址栏中显示的自定义域名 |
| `--widescreen-input` | `None` | 指定宽屏截图路径（跳过浏览器截屏） |
| `--mobile-input` | `None` | 指定移动端截图路径（跳过浏览器截屏） |
| `--output-dir` | `.` | 图片输出目录 |
| `--bg` | `#ffffff` | 海报画布背景色（十六进制色彩，如 `#ffffff`、`#f5f6f7`） |
| `--chrome-path` | 自动探测 | 手动指定 Chrome/Chromium 执行路径 |
| `--status-bar-time` | `9:41` | 手机状态栏时间文字 |
| `--status-bar-weight` | `480` | MiSans VF 时间字重（150-700） |
| `--status-bar-theme` | `auto` | 状态栏主题：`auto`（自动探测）、`dark`（深色图标）、`light`（浅色图标） |
| `--status-bar-mode` | `safe-area` | 布局模式：`safe-area`（预留 54pt 顶部安全区）、`overlay`（直接覆盖于页面顶部） |

---

## 项目移植

该工具为独立脚本，在新项目中宣发时：
1. 复制 `tools/mockup-generator/` 目录至目标仓库。
2. 执行 `python3 tools/mockup-generator/generate.py --url <URL> --site-url <域名>` 即可生成全套宣发资产。
