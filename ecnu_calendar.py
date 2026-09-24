#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import hashlib
import http.server
import ipaddress
import json
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytz
import qrcode
from bs4 import BeautifulSoup
from icalendar import Calendar, Event


OFFICIAL_URL = "https://byyt.ecnu.edu.cn/student/for-std/course-table"
WEEKDAYS_ZH = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


@dataclass(frozen=True)
class Course:
    lesson_id: str
    name: str
    code: str
    weekday: int
    start_period: int
    end_period: int
    weeks: tuple[int, ...]
    week_text: str
    campus: str
    room: str
    teacher: str


def parse_clock(value: str) -> time:
    hour, minute = (int(part) for part in value.split(":"))
    return time(hour, minute)


def parse_weeks(spec: str) -> tuple[int, ...]:
    result: set[int] = set()
    for raw_part in spec.split(","):
        part = raw_part.strip()
        parity = None
        parity_match = re.search(r"\((单|双)\)$", part)
        if parity_match:
            parity = parity_match.group(1)
            part = part[: parity_match.start()]

        if "~" in part:
            start, end = (int(value) for value in part.split("~", 1))
            values = range(start, end + 1)
        else:
            values = [int(part)]

        for value in values:
            if parity == "单" and value % 2 == 0:
                continue
            if parity == "双" and value % 2 == 1:
                continue
            result.add(value)
    return tuple(sorted(result))


def load_saved_course_table(input_path: Path) -> tuple[Path, str]:
    path = input_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"HTML 文件不存在：{path}")

    html = path.read_text(encoding="utf-8")
    if BeautifulSoup(html, "html.parser").select_one("table.courseTable") is not None:
        return path, html

    # Chrome/Edge/Firefox 保存“完整网页”时，外层页面旁边通常会生成
    # <文件名>_files/course-table.html。允许用户直接传外层 HTML。
    asset_directories = [
        path.with_name(f"{path.stem}_files"),
        path.with_name(f"{path.stem}.files"),
    ]
    candidates: list[Path] = []
    for directory in asset_directories:
        if directory.is_dir():
            candidates.extend(
                [
                    directory / "course-table.html",
                    *sorted(directory.glob("*course-table*.html")),
                ]
            )

    checked: set[Path] = set()
    for candidate in candidates:
        if candidate in checked or not candidate.is_file():
            continue
        checked.add(candidate)
        candidate_html = candidate.read_text(encoding="utf-8")
        if BeautifulSoup(candidate_html, "html.parser").select_one("table.courseTable") is not None:
            return candidate, candidate_html

    raise ValueError(
        "传入的 HTML 中没有课表。请在“我的课表”页面选择“网页，全部/完整网页”保存，"
        "并保留 HTML 旁边的 _files 文件夹。"
    )


def parse_course_table(html: str) -> tuple[str, date, dict[int, tuple[time, time]], list[Course]]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.courseTable")
    if table is None:
        raise ValueError("页面中没有找到官方课表 table.courseTable")

    semester_node = soup.select_one("#allSemesters option[selected]")
    if semester_node is None:
        semester_node = soup.select_one("#allSemesters option")
    semester = semester_node.get_text(strip=True) if semester_node else "ECNU课表"

    start_node = soup.select_one("#startDate")
    if start_node is None:
        raise ValueError("页面中没有找到学期起始日期 #startDate")
    semester_start = date.fromisoformat(start_node.get_text(strip=True))

    period_times: dict[int, tuple[time, time]] = {}
    for row in table.select("tbody > tr"):
        row_classes = row.get("class", [])
        if not row_classes or not row_classes[0].isdigit():
            continue
        period = int(row_classes[0])
        time_node = row.select_one("td.dayPartUnit")
        match = re.search(
            r"(\d{1,2}:\d{2})\s*~\s*(\d{1,2}:\d{2})",
            time_node.get_text(" ", strip=True),
        )
        if match is None:
            raise ValueError(f"第 {period} 节没有找到起止时间")
        period_times[period] = (parse_clock(match.group(1)), parse_clock(match.group(2)))

    courses: list[Course] = []
    seen: set[tuple[object, ...]] = set()
    for card in table.select("td.td-content .tdHtml[lessonid]"):
        cell = card.find_parent("td")
        day_classes = [value for value in cell.get("class", []) if value.isdigit()]
        if not day_classes:
            continue
        weekday = int(day_classes[0])
        start_period = int(cell.find_parent("tr").get("class", ["0"])[0])
        divs = card.find_all("div", recursive=False)
        if len(divs) < 3:
            raise ValueError("发现无法识别的课程卡片")

        # 官网会把多门接续课程放进同一张卡片，例如前 12 周与后 6 周
        # 共享同一时间地点。每门课都是“课程名、教学班代码、详情”三项一组。
        for index in range(0, len(divs), 3):
            group = divs[index : index + 3]
            if len(group) < 3 or "course-name" not in group[0].get("class", []):
                raise ValueError("发现无法识别的多课程卡片")

            name = group[0].get_text(" ", strip=True)
            code_match = re.search(r"教学班代码：\s*(\S+)", group[1].get_text(" ", strip=True))
            if code_match is None:
                raise ValueError(f"课程 {name} 没有教学班代码")
            code = code_match.group(1)
            detail = group[2].get_text(" ", strip=True)
            detail_match = re.fullmatch(
                r"\((.+)周\)\s*\((\d+)-(\d+)节\)\s*([^\s]+)\s*([^\s]+)\s+(.+)",
                detail,
            )
            if detail_match is None:
                raise ValueError(f"无法解析课程详情：{detail}")
            week_text, start_text, end_text, campus, room, teacher = detail_match.groups()
            if int(start_text) != start_period:
                raise ValueError(f"课程 {name} 的卡片行与节次不一致")
            weeks = parse_weeks(week_text)
            identity = (
                code,
                weekday,
                start_period,
                int(end_text),
                weeks,
                campus,
                room,
                teacher,
            )
            if identity in seen:
                continue
            seen.add(identity)
            courses.append(
                Course(
                    lesson_id=f"{card['lessonid']}:{code}",
                    name=name,
                    code=code,
                    weekday=weekday,
                    start_period=start_period,
                    end_period=int(end_text),
                    weeks=weeks,
                    week_text=week_text,
                    campus=campus,
                    room=room,
                    teacher=teacher,
                )
            )

    if not courses:
        raise ValueError("官方课表中没有解析到课程")
    courses.sort(key=lambda item: (item.weekday, item.start_period, item.name))
    return semester, semester_start, period_times, courses


def semester_file_stem(semester: str) -> str:
    year_match = re.search(r"(20\d{2})", semester)
    year = year_match.group(1) if year_match else "Current"
    if "秋" in semester or "Fall" in semester:
        season = "Fall"
    elif "春" in semester or "Spring" in semester:
        season = "Spring"
    elif "夏" in semester or "Summer" in semester:
        season = "Summer"
    else:
        season = "Semester"
    return f"ECNU_{year}_{season}_Course_Schedule"


def build_calendar(
    semester: str,
    semester_start: date,
    period_times: dict[int, tuple[time, time]],
    courses: list[Course],
) -> tuple[bytes, int]:
    calendar = Calendar()
    calendar.add("prodid", "-//ECNU Course Schedule//CN")
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", "PUBLISH")
    calendar.add("X-WR-CALNAME", f"华东师大 {semester} 课表")
    calendar.add("X-WR-TIMEZONE", "Asia/Shanghai")

    timezone = pytz.timezone("Asia/Shanghai")
    generated_at = datetime.now(timezone)
    event_count = 0
    for course in courses:
        for week in course.weeks:
            event_date = semester_start + timedelta(weeks=week - 1, days=course.weekday - 1)
            start_at = datetime.combine(event_date, period_times[course.start_period][0])
            end_at = datetime.combine(event_date, period_times[course.end_period][1])
            digest = hashlib.sha256(
                f"{course.code}|{event_date.isoformat()}|{course.start_period}-{course.end_period}".encode()
            ).hexdigest()[:24]
            description = "\n".join(
                [
                    f"教师：{course.teacher}",
                    f"教学班代码：{course.code}",
                    f"周次：第{week}周（官网HTML：{course.week_text}周）",
                    f"节次：第{course.start_period}-{course.end_period}节",
                    f"来源：{OFFICIAL_URL}",
                ]
            )
            event = Event()
            event.add("uid", f"{digest}@ecnu.edu.cn")
            event.add("dtstamp", generated_at)
            event.add("dtstart", timezone.localize(start_at))
            event.add("dtend", timezone.localize(end_at))
            event.add("summary", course.name)
            event.add("location", f"{course.campus} {course.room}")
            event.add("description", description)
            event.add("status", "CONFIRMED")
            event.add("transp", "OPAQUE")
            calendar.add_component(event)
            event_count += 1
    return calendar.to_ical(), event_count


def write_summary(
    path: Path,
    semester: str,
    semester_start: date,
    period_times: dict[int, tuple[time, time]],
    courses: list[Course],
    event_count: int,
    import_url: str | None,
) -> None:
    lines = [
        f"# 华东师范大学 {semester} 官方 HTML 课表",
        "",
        f"- 学期起始日期：{semester_start.isoformat()}",
        f"- 课程：{len({course.code for course in courses})} 门",
        f"- 日历事件：{event_count} 个",
        f"- 数据来源：{OFFICIAL_URL}",
        "- 解析规则：只使用官网课表 HTML，不合并人工更正",
        "",
        "| 星期 | 节次/时间 | 课程 | 周次 | 地点 | 教师 | 教学班 |",
        "|---|---|---|---|---|---|---:|",
    ]
    for course in courses:
        start = period_times[course.start_period][0].strftime("%H:%M")
        end = period_times[course.end_period][1].strftime("%H:%M")
        lines.append(
            f"| {WEEKDAYS_ZH[course.weekday - 1]} | {course.start_period}–{course.end_period}节 "
            f"{start}–{end} | {course.name} | {course.week_text}周 | "
            f"{course.campus} {course.room} | {course.teacher} | {course.code} |"
        )
    if import_url:
        lines.extend(["", "iOS 扫码地址：", "", import_url])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def detect_lan_ip() -> str:
    """Find an address on a local network adapter, ignoring VPN/TUN routes."""
    system = platform.system()
    candidates: list[tuple[int, str]] = []

    try:
        if system == "Darwin":
            # networksetup lists hardware ports, so utun and other VPN devices are absent.
            output = subprocess.run(
                ["networksetup", "-listallhardwareports"],
                check=True, capture_output=True, text=True,
            ).stdout
            for block in output.split("\n\n"):
                port = re.search(r"^Hardware Port: (.+)$", block, re.MULTILINE)
                device = re.search(r"^Device: (.+)$", block, re.MULTILINE)
                if not port or not device:
                    continue
                name = port.group(1).lower()
                if "bridge" in name:
                    continue
                result = subprocess.run(
                    ["ipconfig", "getifaddr", device.group(1)],
                    check=False, capture_output=True, text=True,
                )
                if result.returncode == 0:
                    priority = 0 if "wi-fi" in name else 1 if "ethernet" in name else 2
                    candidates.append((priority, result.stdout.strip()))
        elif system == "Linux":
            output = subprocess.run(
                ["ip", "-j", "-4", "addr", "show", "up"],
                check=True, capture_output=True, text=True,
            ).stdout
            for adapter in json.loads(output):
                name = adapter.get("ifname", "")
                if name.startswith(("lo", "tun", "tap", "wg", "docker", "br-", "veth", "tailscale", "zt")):
                    continue
                if adapter.get("link_type") != "ether":
                    continue
                priority = 0 if (Path("/sys/class/net") / name / "device").exists() else 1
                for address in adapter.get("addr_info", []):
                    if address.get("family") == "inet" and address.get("scope") == "global":
                        candidates.append((priority, address["local"]))
        elif system == "Windows":
            script = (
                "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | "
                "ForEach-Object { Get-NetIPAddress -InterfaceIndex $_.ifIndex "
                "-AddressFamily IPv4 -ErrorAction SilentlyContinue } | "
                "Select-Object -ExpandProperty IPAddress"
            )
            output = subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", script],
                check=True, capture_output=True, text=True,
            ).stdout
            candidates.extend((0, line.strip()) for line in output.splitlines())
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        raise RuntimeError("无法自动检测局域网 IP，请使用 --host 手动指定") from exc

    for _, value in sorted(candidates):
        try:
            address = ipaddress.IPv4Address(value)
        except ipaddress.AddressValueError:
            continue
        if not (address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified):
            return value
    raise RuntimeError("无法自动检测局域网 IP，请使用 --host 手动指定")


class CalendarHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".ics": "text/calendar; charset=utf-8"}

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        super().end_headers()

    def log_message(self, format_string: str, *args) -> None:
        print("iOS下载：" + format_string % args)


def serve_for_ios(ics_path: Path, qr_path: Path, host: str, port: int) -> None:
    with tempfile.TemporaryDirectory(prefix="ecnu-calendar-share-") as temp_dir:
        share_dir = Path(temp_dir)
        shared_ics = share_dir / ics_path.name
        shutil.copy2(ics_path, shared_ics)
        url = f"http://{host}:{port}/{ics_path.name}"
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=12,
            border=4,
        )
        qr.add_data(url)
        qr.make(fit=True)
        qr.make_image(fill_color="black", back_color="white").save(qr_path)

        handler = functools.partial(CalendarHandler, directory=str(share_dir))
        # 与参考项目一致：服务监听所有 IPv4 网卡；host 只用于二维码中的访问地址。
        server = http.server.ThreadingHTTPServer(("", port), handler)
        server.daemon_threads = True
        print(f"iOS 二维码：{qr_path}")
        print(f"局域网地址：{url}")
        print("请让 iPhone 与电脑连接同一局域网后扫码；导入完成按 Ctrl+C 退出。")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止局域网下载服务。")
        finally:
            server.server_close()


def validate_ics(path: Path, expected_events: int) -> None:
    calendar = Calendar.from_ical(path.read_bytes())
    events = [component for component in calendar.walk() if component.name == "VEVENT"]
    uids = [str(event.get("uid", "")) for event in events]
    if len(events) != expected_events:
        raise ValueError(f"ICS 校验失败：期望 {expected_events} 个事件，实际 {len(events)} 个")
    if not all(uids):
        raise ValueError("ICS 校验失败：部分事件没有 UID")
    if len(set(uids)) != len(uids):
        raise ValueError("ICS 校验失败：存在重复 UID")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从用户保存的 ECNU 官方课表 HTML 生成 ICS 和 iOS 导入二维码"
    )
    parser.add_argument(
        "html_file",
        type=Path,
        help="从“我的课表”页面保存的 HTML；可传外层 HTML 或 _files/course-table.html",
    )
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "ecnu-calendar-output")
    parser.add_argument("--host", help="局域网 IP；默认自动检测")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-serve", action="store_true", help="只生成 ICS 和摘要，不生成二维码或启动服务")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    source_path, html = load_saved_course_table(args.html_file)
    print(f"课表来源：{source_path}")

    semester, semester_start, period_times, courses = parse_course_table(html)
    calendar_bytes, event_count = build_calendar(semester, semester_start, period_times, courses)
    stem = semester_file_stem(semester)
    ics_path = args.output_dir / f"{stem}.ics"
    summary_path = args.output_dir / f"{stem}_Summary.md"
    qr_path = args.output_dir / f"{stem}_iOS_QR.png"
    ics_path.write_bytes(calendar_bytes)
    validate_ics(ics_path, event_count)

    if args.no_serve:
        write_summary(
            summary_path,
            semester,
            semester_start,
            period_times,
            courses,
            event_count,
            None,
        )
        print(f"课程：{len({course.code for course in courses})} 门")
        print(f"事件：{event_count} 个")
        print(f"ICS：{ics_path}")
        print(f"摘要：{summary_path}")
        return

    host = args.host or detect_lan_ip()
    import_url = f"http://{host}:{args.port}/{ics_path.name}"
    write_summary(
        summary_path,
        semester,
        semester_start,
        period_times,
        courses,
        event_count,
        import_url,
    )
    print(f"课程：{len({course.code for course in courses})} 门")
    print(f"事件：{event_count} 个")
    print(f"ICS：{ics_path}")
    print(f"摘要：{summary_path}")
    serve_for_ios(ics_path, qr_path, host, args.port)


if __name__ == "__main__":
    main()
