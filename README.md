# ECNUCourseTableTool-2.0

从华东师范大学教务系统保存课表网页，生成可导入手机电脑日历的 ICS 文件，并为 iPhone 生成扫码导入二维码（保证手机和电脑在同一局域网内）。

## 准备课表 HTML

1. 使用任意浏览器登录 ECNU 教育教学管理平台。
2. 打开“我的课表”。
3. 选择“网页另存为”，保存类型选择“网页，全部”或“完整网页”。
4. 建议保存为项目目录中的 `ecnuclasstable.html`，并保留浏览器生成的 `ecnuclasstable_files` 文件夹。

目录示例：

```text
ECNUCourseTableTool/
├── ecnu_calendar.py
├── ecnuclasstable.html
├── ecnuclasstable_files/
│   └── course-table.html
└── requirements.txt
```

## 使用 uv（推荐）

项目已包含 `pyproject.toml` 和 `uv.lock`，推荐使用 Python 3.12。`uv sync` 会按照锁文件自动创建并同步项目环境。

### Linux / macOS

```bash
cd ECNUCourseTableTool
python3 --version
uv --version
uv sync
uv run python ecnu_calendar.py "华东师范大学教育教学管理平台.html" --output-dir "result"
```

### Windows PowerShell

```powershell
cd ECNUCourseTableTool
python --version
uv --version
uv sync
uv run python .\ecnu_calendar.py "ecnuclasstable.html" --output-dir "result"
```

完成首次配置后，日常运行只需要：

```bash
cd ECNUCourseTableTool
uv run python ecnu_calendar.py "ecnuclasstable.html" --output-dir "result"
```


## 不使用 uv

### Linux / macOS

```bash
cd ECNUCourseTableTool
python3 --version
python3 -m pip install -r requirements.txt
python3 ecnu_calendar.py "ecnuclasstable.html" --output-dir "result"
```

### Windows PowerShell

```powershell
cd ECNUCourseTableTool
python --version
python -m pip install -r requirements.txt
python .\ecnu_calendar.py "ecnuclasstable.html" --output-dir "result"
```

依赖版本已经固定在 `requirements.txt`：

```text
beautifulsoup4==4.15.0
pytz==2026.3.post1
icalendar==7.3.0
qrcode==8.2
pillow==12.3.0
```


## 导入日历

程序默认生成：

- `result/ECNU_学年_学期_Course_Schedule.ics`：Linux、macOS、Windows 均可导入。
- `result/ECNU_学年_学期_Course_Schedule_Summary.md`：解析结果摘要。
- `result/ECNU_学年_学期_Course_Schedule_iOS_QR.png`：iPhone 扫码入口。

使用 iPhone 扫码时，让手机和电脑连接同一局域网。程序显示二维码和下载地址后会保持运行；导入完成后按 `Ctrl+C` 退出。
自动检测会从电脑的物理网卡选取地址，避免 Clash TUN 等虚拟网卡的 IP 进入二维码；如果电脑连接了多个局域网，可用 `--host` 指定手机能访问的 IPv4 地址。

只生成 ICS 和摘要，不启动扫码服务：

```bash
uv run python ecnu_calendar.py "ecnuclasstable.html" --output-dir "result" --no-serve
```

Windows PowerShell：

```powershell
uv run python .\ecnu_calendar.py "ecnuclasstable.html" --output-dir "result" --no-serve
```

手动指定电脑的局域网地址或端口：

```bash
uv run python ecnu_calendar.py "ecnuclasstable.html" --output-dir "result" --host 192.168.1.23 --port 8877
```

## 许可证

MIT License

修改自：https://github.com/SJF-ECNU/ECNUCourseTableToolForIOS
