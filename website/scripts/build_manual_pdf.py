from __future__ import annotations

import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[2]
PUBLIC_DOCS = ROOT / "frontend" / "public" / "docs"
OUTPUT_DIR = ROOT / "output" / "pdf"
PINK = colors.HexColor("#cf43c8")
CYAN = colors.HexColor("#56d7ef")
INK = colors.HexColor("#151423")
MUTED = colors.HexColor("#5f6170")
PALE = colors.HexColor("#f7f3fb")
LINE = colors.HexColor("#e2d7e8")
SUCCESS = colors.HexColor("#167d68")
WARNING = colors.HexColor("#8b5f16")


CONTENT = {
    "en": {
        "file": "DroneDream-Manual-en.pdf",
        "font": "Segoe",
        "font_bold": "SegoeBold",
        "eyebrow": "DRONEDREAM MANUAL",
        "title": "Build explainable tuning experiments.",
        "intro": (
            "A complete guide to installing DroneDream, creating a PX4 tuning study, "
            "reviewing simulation evidence, and preserving the boundaries that keep every "
            "engineering decision auditable."
        ),
        "contents": "Contents",
        "chapters": [
            ("1", "Start here"),
            ("2", "Install and prepare"),
            ("3", "Create with Tuning Chat"),
            ("4", "Complete the five-step experiment"),
            ("5", "Edit a custom flight track"),
            ("6", "Review history and evidence"),
            ("7", "Accounts, data, and safety"),
        ],
        "sections": [
            {
                "number": "1",
                "title": "Start here",
                "body": (
                    "DroneDream is a local-first workspace for configuring, simulating, and "
                    "comparing PX4 controller parameters. Language models clarify intent and "
                    "prepare reviewable drafts; deterministic validation, constraints, "
                    "acceptance rules, and human review keep every experiment reproducible."
                ),
                "bullets": [
                    "Use Windows 10 or Windows 11 on an x64 computer.",
                    "Reserve at least 52 GiB on a writable NTFS drive for the isolated runtime.",
                    "Create an account before saving user-scoped settings or cloud records.",
                    "Configure a model only for Tuning Chat or an LLM-guided strategy.",
                    "Treat every result as simulation evidence, never automatic hardware approval.",
                ],
                "callout": (
                    "Engineering boundary: independently reproduce selected parameters in SITL "
                    "and inspect the complete logs before considering real hardware."
                ),
            },
            {
                "number": "2",
                "title": "Install and prepare",
                "body": (
                    "Download version 1.0.0 from the official website and install the desktop "
                    "application on an eligible local drive. On first launch, DroneDream prepares "
                    "a dedicated WSL2 distribution for PX4, Gazebo, workers, and experiment "
                    "artifacts without reusing a personal Ubuntu distribution."
                ),
                "steps": [
                    ("Download", "Get the current Windows installer from getdronedream.com."),
                    ("Install", "Choose an eligible NTFS drive and keep the recommended directory."),
                    ("Prepare", "Wait while the isolated runtime is imported and verified."),
                    ("Enter", "Open the workspace only after the green status reads Checked."),
                ],
                "callout": (
                    "Opening the workspace does not start another check. Run a new check only from "
                    "Settings > Local runtime > Check environment."
                ),
            },
            {
                "number": "3",
                "title": "Create with Tuning Chat",
                "body": (
                    "Describe the aircraft, route, target behavior, disturbances, and priorities "
                    "in plain language or by voice. DroneDream extracts explicit values, lists "
                    "missing decisions, and prepares a draft that must still be reviewed before "
                    "any job can begin."
                ),
                "image": PUBLIC_DOCS / "en" / "tuning-chat.png",
                "example": (
                    "Example: Tune an x500 quadrotor on a 5 m circular track at 3 m altitude. "
                    "Prioritize tracking accuracy, include moderate sensor noise, and keep the "
                    "experiment within 180 trials."
                ),
                "bullets": [
                    "The assistant summarizes the intended study in engineering terms.",
                    "Known fields are placed into the draft with visible provenance.",
                    "Missing parameter ranges and acceptance thresholds remain open for confirmation.",
                    "The assistant cannot create a running job or bypass the five-step review.",
                ],
            },
            {
                "number": "4",
                "title": "Complete the five-step experiment",
                "body": (
                    "The manual workflow exposes every field and records the current stage. "
                    "Reopening a draft returns to the same experiment and the last completed step, "
                    "so detailed configuration can be reviewed without rebuilding the study."
                ),
                "image": PUBLIC_DOCS / "en" / "flight-setup.png",
                "steps": [
                    ("Flight Setup", "Choose the vehicle, world, objective weights, and track."),
                    ("Parameters", "Confirm each selected PX4 parameter and its search range."),
                    ("Scenarios", "Define search, holdout, wind, noise, seeds, and vehicle effects."),
                    ("Constraints & Budget", "Select a strategy and set trial and acceptance limits."),
                    ("Review", "Audit the complete contract before creating the experiment."),
                ],
            },
            {
                "number": "5",
                "title": "Edit a custom flight track",
                "body": (
                    "The track editor pairs a plot with an equal-height coordinate table. Switch "
                    "among XY, XZ, YZ, and 3D views, edit full X/Y/Z values, and use JSON import or "
                    "export when a path is easier to generate with another tool."
                ),
                "bullets": [
                    "Select a row to highlight the corresponding waypoint.",
                    "Add, undo, or delete points with the controls above the coordinate table.",
                    "Keep imported coordinates inside the intended simulation volume.",
                    "In 3D, both ground axes use the same real-world unit and square grid cells.",
                ],
                "callout": (
                    "Extending a route adds more square cells; it must never stretch the existing "
                    "ground grid into rectangular units."
                ),
            },
            {
                "number": "6",
                "title": "Review history and evidence",
                "body": (
                    "Dashboard and Run History expose completed, failed, cancelled, and active "
                    "experiments. Filter by status, track, objective, strategy, or date, then open "
                    "a result to inspect the metrics, scenarios, logs, artifacts, and configuration "
                    "that produced the decision."
                ),
                "image": PUBLIC_DOCS / "en" / "dashboard.png",
                "steps": [
                    ("Configuration", "Vehicle, firmware, route, ranges, constraints, and budget."),
                    ("Execution", "Scenario identity, seeds, manifests, logs, and artifacts."),
                    ("Decision", "Feasibility, error, overshoot, settling, robustness, and trade-offs."),
                ],
                "callout": (
                    "Compare only experiments whose scenario and metric contracts are compatible. "
                    "A lower score is not meaningful when validation conditions differ."
                ),
            },
            {
                "number": "7",
                "title": "Accounts, data, and safety",
                "body": (
                    "Supabase identity and row-level policies isolate cloud account records. Public "
                    "community topics are deliberately shared, while account settings and user-owned "
                    "cloud data remain scoped to their owner. Local drafts stay available during the "
                    "application session and are discarded after a confirmed exit."
                ),
                "bullets": [
                    "Provider and model settings may be saved on the device, while the model API key remains only in session memory.",
                    "API keys are never written into experiment drafts, run records, exports, or community posts.",
                    "DroneDream assists engineering judgment; independent SITL validation and operator approval remain mandatory before hardware flight.",
                ],
            },
        ],
        "footer": "DroneDream 1.0.0 · getdronedream.com",
    },
    "zh-CN": {
        "file": "DroneDream-Manual-zh-CN.pdf",
        "font": "MicrosoftYaHei",
        "font_bold": "MicrosoftYaHeiBold",
        "eyebrow": "DRONEDREAM 使用说明",
        "title": "创建可解释、可复查的调优实验。",
        "intro": (
            "这份说明书覆盖 DroneDream 的完整使用流程，从安装 Windows 客户端，到创建 PX4 "
            "调优实验、审查仿真证据，以及保留每一个工程决策所需要的数据边界。"
        ),
        "contents": "目录",
        "chapters": [
            ("1", "开始之前"),
            ("2", "安装与环境准备"),
            ("3", "通过调优对话创建实验"),
            ("4", "完成五个实验配置环节"),
            ("5", "编辑自定义飞行轨迹"),
            ("6", "查看历史记录和实验依据"),
            ("7", "账户、数据与安全边界"),
        ],
        "sections": [
            {
                "number": "1",
                "title": "开始之前",
                "body": (
                    "DroneDream 是一个本地优先的 PX4 控制参数调优工作台。大语言模型可以帮助理解"
                    "意图并准备可审查草稿，但字段校验、耦合规则、仿真执行和验收判断始终由确定性的"
                    "工程流程控制。"
                ),
                "bullets": [
                    "使用 Windows 10 或 Windows 11 的 x64 计算机。",
                    "在可写入的 NTFS 磁盘上预留至少 52 GiB 空间。",
                    "先创建账户，再保存属于用户的设置和云端记录。",
                    "只有需要调优对话或大模型策略时才配置模型。",
                    "所有结果都只是仿真证据，不能自动成为真实飞行许可。",
                ],
                "callout": (
                    "工程边界：任何被选中的参数组合都必须先在独立 SITL 中复现，并检查完整日志，"
                    "之后才可以考虑真实硬件。"
                ),
            },
            {
                "number": "2",
                "title": "安装与环境准备",
                "body": (
                    "从官方网站下载 1.0.0 版本并安装桌面客户端。首次启动时，DroneDream 会准备一个"
                    "专用 WSL2 系统，用来容纳 PX4、Gazebo、工作进程和实验产物，不会复用或修改"
                    "用户个人的 Ubuntu。"
                ),
                "steps": [
                    ("下载安装包", "从 getdronedream.com 获取当前 Windows 安装程序。"),
                    ("安装客户端", "选择符合条件的 NTFS 磁盘并保留推荐目录。"),
                    ("准备环境", "等待隔离系统完成导入、启动和完整校验。"),
                    ("进入工作台", "确认绿色状态显示 Checked 后再打开工作台。"),
                ],
                "callout": (
                    "进入工作台不会自动再次检查环境。需要重新检查时，依次打开“设置”“本地运行环境”"
                    "和“检查环境”。"
                ),
            },
            {
                "number": "3",
                "title": "通过调优对话创建实验",
                "body": (
                    "用文字或语音描述飞行器、赛道、目标、扰动和优先级。DroneDream 会提取明确"
                    "信息、列出尚未说明的决策，并生成仍需用户复查的实验草稿，不会绕过审查直接启动任务。"
                ),
                "image": PUBLIC_DOCS / "zh-CN" / "tuning-chat.png",
                "example": (
                    "示例：在 3 米高度让 x500 四旋翼沿半径 5 米的圆形赛道飞行，优先提高轨迹跟踪"
                    "精度，加入中等强度的传感器噪声，并把总试验次数控制在 180 次以内。"
                ),
                "bullets": [
                    "助手会用工程术语总结用户希望完成的研究。",
                    "明确的信息会写入草稿，并保留可见的信息来源。",
                    "缺失的参数范围和验收阈值会继续等待用户确认。",
                    "助手不能创建运行任务，也不能绕过五环节审查。",
                ],
            },
            {
                "number": "4",
                "title": "完成五个实验配置环节",
                "body": (
                    "手动创建流程开放全部字段并记录当前环节。重新打开草稿时会回到同一个实验和上次"
                    "停留的位置，因此可以继续配置，而不必重新建立整套研究。"
                ),
                "image": PUBLIC_DOCS / "zh-CN" / "flight-setup.png",
                "steps": [
                    ("飞行设置", "选择飞行器、世界、目标权重和飞行轨迹。"),
                    ("控制参数", "确认每个 PX4 参数及其基线值和搜索范围。"),
                    ("仿真场景", "设置搜索、留出、风场、噪声、随机种子和飞行器影响。"),
                    ("约束与预算", "选择优化策略并设置试验和验收边界。"),
                    ("最终审查", "复查完整实验契约，确认无误后再创建实验。"),
                ],
            },
            {
                "number": "5",
                "title": "编辑自定义飞行轨迹",
                "body": (
                    "轨迹编辑器把坐标图与等高的坐标表组合在一起。用户可以切换 XY、XZ、YZ 和 3D "
                    "视图，修改完整的 X/Y/Z 数值，也可以通过 JSON 与外部路径生成工具交换坐标。"
                ),
                "bullets": [
                    "选择表格行时，对应航点会同步高亮。",
                    "使用表格上方的按钮添加、撤销或删除航点。",
                    "导入后检查所有坐标是否位于预期仿真空间。",
                    "3D 地面两个方向使用相同的真实单位和正方形网格。",
                ],
                "callout": (
                    "轨迹延长时应增加更多正方形网格，不能把已有的地面网格拉成长方形。"
                ),
            },
            {
                "number": "6",
                "title": "查看历史记录和实验依据",
                "body": (
                    "任务总览和历史报告会展示完成、失败、取消和正在运行的实验。用户可以按状态、轨迹、"
                    "目标、策略和日期筛选，并进入详情查看指标、场景、日志、产物和产生该结果的完整配置。"
                ),
                "image": PUBLIC_DOCS / "zh-CN" / "dashboard.png",
                "steps": [
                    ("配置依据", "飞行器、固件、轨迹、参数范围、约束和预算。"),
                    ("执行依据", "场景标识、随机种子、运行清单、日志和仿真产物。"),
                    ("决策依据", "可行性、误差、超调量、稳定时间、鲁棒性和权衡。"),
                ],
                "callout": (
                    "只有场景和指标契约兼容的实验才适合直接比较。验证条件不同，即使分数更低也不代表"
                    "工程结果更好。"
                ),
            },
            {
                "number": "7",
                "title": "账户、数据与安全边界",
                "body": (
                    "Supabase 身份与行级安全策略用来隔离云端账户记录。社区话题按设计公开共享，而"
                    "账户设置和属于用户的云端数据仍然只对创建者开放。本地草稿在应用会话中保留，"
                    "确认退出后会被丢弃。"
                ),
                "bullets": [
                    "供应商和模型设置可以保存在设备上，但模型 API Key 只停留在当前应用会话的内存中。",
                    "API Key 不会被写入实验草稿、运行记录、导出文件或社区帖子。",
                    "DroneDream 只辅助工程判断；真实飞行前仍然必须完成独立 SITL 验证并取得操作者确认。",
                ],
            },
        ],
        "footer": "DroneDream 1.0.0 · getdronedream.com",
    },
}


def register_fonts() -> None:
    pdfmetrics.registerFont(TTFont("Segoe", r"C:\Windows\Fonts\segoeui.ttf"))
    pdfmetrics.registerFont(TTFont("SegoeBold", r"C:\Windows\Fonts\seguisb.ttf"))
    pdfmetrics.registerFont(TTFont("MicrosoftYaHei", r"C:\Windows\Fonts\msyh.ttc"))
    pdfmetrics.registerFont(TTFont("MicrosoftYaHeiBold", r"C:\Windows\Fonts\msyhbd.ttc"))


def make_styles(font: str, bold: str) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_eyebrow": ParagraphStyle(
            "cover_eyebrow",
            parent=base["Normal"],
            fontName=bold,
            fontSize=9,
            leading=12,
            textColor=PINK,
            spaceAfter=8,
            tracking=1.5,
        ),
        "cover_title": ParagraphStyle(
            "cover_title",
            parent=base["Title"],
            fontName=bold,
            fontSize=25,
            leading=31,
            textColor=INK,
            alignment=TA_LEFT,
            spaceAfter=14,
        ),
        "intro": ParagraphStyle(
            "intro",
            parent=base["Normal"],
            fontName=font,
            fontSize=11,
            leading=18,
            textColor=MUTED,
            spaceAfter=14,
        ),
        "h1": ParagraphStyle(
            "h1",
            parent=base["Heading1"],
            fontName=bold,
            fontSize=22,
            leading=28,
            textColor=INK,
            spaceBefore=4,
            spaceAfter=12,
        ),
        "h2": ParagraphStyle(
            "h2",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=13,
            leading=18,
            textColor=INK,
            spaceBefore=8,
            spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "body",
            parent=base["BodyText"],
            fontName=font,
            fontSize=10,
            leading=16,
            textColor=MUTED,
            spaceAfter=10,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            parent=base["BodyText"],
            fontName=font,
            fontSize=9.7,
            leading=15,
            textColor=MUTED,
            leftIndent=2,
        ),
        "step_title": ParagraphStyle(
            "step_title",
            parent=base["BodyText"],
            fontName=bold,
            fontSize=10,
            leading=14,
            textColor=INK,
            spaceAfter=2,
        ),
        "step_body": ParagraphStyle(
            "step_body",
            parent=base["BodyText"],
            fontName=font,
            fontSize=9,
            leading=13,
            textColor=MUTED,
        ),
        "callout": ParagraphStyle(
            "callout",
            parent=base["BodyText"],
            fontName=font,
            fontSize=9.5,
            leading=15,
            textColor=WARNING,
        ),
        "toc_title": ParagraphStyle(
            "toc_title",
            parent=base["Heading2"],
            fontName=bold,
            fontSize=14,
            leading=18,
            textColor=INK,
            spaceAfter=8,
        ),
        "toc": ParagraphStyle(
            "toc",
            parent=base["BodyText"],
            fontName=font,
            fontSize=10,
            leading=17,
            textColor=MUTED,
        ),
        "example": ParagraphStyle(
            "example",
            parent=base["BodyText"],
            fontName=font,
            fontSize=9.5,
            leading=15,
            textColor=INK,
        ),
    }


def page_chrome(canvas, doc, footer: str, font: str) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFillColor(colors.HexColor("#080a14"))
    canvas.rect(0, height - 7 * mm, width, 7 * mm, fill=1, stroke=0)
    canvas.setFillColor(CYAN)
    canvas.rect(0, height - 7 * mm, width * 0.34, 0.9 * mm, fill=1, stroke=0)
    canvas.setFillColor(PINK)
    canvas.rect(width * 0.34, height - 7 * mm, width * 0.66, 0.9 * mm, fill=1, stroke=0)
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, 15 * mm, width - 18 * mm, 15 * mm)
    canvas.setFont(font, 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, 9.5 * mm, footer)
    canvas.drawRightString(width - 18 * mm, 9.5 * mm, str(doc.page))
    canvas.restoreState()


def callout(text: str, styles: dict[str, ParagraphStyle]) -> Table:
    table = Table(
        [[Paragraph("!", styles["step_title"]), Paragraph(text, styles["callout"])]],
        colWidths=[10 * mm, 155 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fff8e8")),
                ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#e8c47c")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("TEXTCOLOR", (0, 0), (0, 0), WARNING),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    return table


def step_table(items: list[tuple[str, str]], styles: dict[str, ParagraphStyle]) -> Table:
    rows = []
    for index, (title, body) in enumerate(items, start=1):
        rows.append(
            [
                Paragraph(f"{index:02d}", styles["step_title"]),
                Paragraph(title, styles["step_title"]),
                Paragraph(body, styles["step_body"]),
            ]
        )
    table = Table(rows, colWidths=[13 * mm, 35 * mm, 117 * mm], repeatRows=0)
    commands = [
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.45, LINE),
        ("BACKGROUND", (0, 0), (0, -1), PALE),
        ("TEXTCOLOR", (0, 0), (0, -1), PINK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]
    table.setStyle(TableStyle(commands))
    return table


def screenshot(path: Path) -> Image:
    image = Image(str(path))
    image._restrictSize(165 * mm, 86 * mm)
    image.hAlign = "CENTER"
    return image


def build(locale: str) -> Path:
    copy = CONTENT[locale]
    font = copy["font"]
    bold = copy["font_bold"]
    styles = make_styles(font, bold)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / copy["file"]
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=17 * mm,
        bottomMargin=20 * mm,
        title=copy["title"],
        author="Chi Zhang",
        subject="DroneDream 1.0.0 product manual",
    )
    story = [
        Spacer(1, 18 * mm),
        Paragraph(copy["eyebrow"], styles["cover_eyebrow"]),
        Paragraph(copy["title"], styles["cover_title"]),
        Paragraph(copy["intro"], styles["intro"]),
        Spacer(1, 5 * mm),
        callout(copy["sections"][0]["callout"], styles),
        Spacer(1, 12 * mm),
        Paragraph(copy["contents"], styles["toc_title"]),
    ]
    toc_rows = []
    for number, title in copy["chapters"]:
        toc_rows.append(
            [
                Paragraph(number, styles["step_title"]),
                Paragraph(title, styles["toc"]),
            ]
        )
    toc = Table(toc_rows, colWidths=[12 * mm, 145 * mm])
    toc.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.35, LINE),
                ("TEXTCOLOR", (0, 0), (0, -1), PINK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([toc, PageBreak()])

    for index, section in enumerate(copy["sections"]):
        if index > 0:
            story.append(Spacer(1, 8 * mm))
        story.append(
            KeepTogether(
                [
                    Paragraph(
                        f'<font color="#cf43c8">{section["number"].zfill(2)}</font>  {section["title"]}',
                        styles["h1"],
                    ),
                    Paragraph(section["body"], styles["body"]),
                ]
            )
        )
        if section.get("image"):
            story.extend([Spacer(1, 2 * mm), screenshot(section["image"]), Spacer(1, 5 * mm)])
        if section.get("example"):
            example_box = Table(
                [[Paragraph(section["example"], styles["example"])]],
                colWidths=[165 * mm],
            )
            example_box.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f8ff")),
                        ("LINEBEFORE", (0, 0), (0, -1), 2.2, CYAN),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 9),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
                    ]
                )
            )
            story.extend([example_box, Spacer(1, 5 * mm)])
        if section.get("steps"):
            story.extend([step_table(section["steps"], styles), Spacer(1, 5 * mm)])
        if section.get("bullets"):
            bullets = ListFlowable(
                [
                    ListItem(Paragraph(item, styles["bullet"]), leftIndent=7)
                    for item in section["bullets"]
                ],
                bulletType="bullet",
                start="circle",
                bulletFontName=bold,
                bulletColor=PINK,
                leftIndent=16,
                bulletFontSize=7,
                spaceAfter=8,
            )
            story.append(bullets)
            if index < len(copy["sections"]) - 1 or section.get("callout"):
                story.append(Spacer(1, 3 * mm))
        if section.get("callout") and not (index == 0):
            story.append(KeepTogether([callout(section["callout"], styles)]))

    doc.build(
        story,
        onFirstPage=lambda canvas, built: page_chrome(canvas, built, copy["footer"], font),
        onLaterPages=lambda canvas, built: page_chrome(canvas, built, copy["footer"], font),
    )
    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", choices=["en", "zh-CN", "all"], default="all")
    args = parser.parse_args()
    register_fonts()
    locales = ["en", "zh-CN"] if args.locale == "all" else [args.locale]
    for locale in locales:
        path = build(locale)
        print(path)


if __name__ == "__main__":
    main()
