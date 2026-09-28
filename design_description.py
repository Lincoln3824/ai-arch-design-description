#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 图生建筑设计说明
==================

读取一张建筑图纸（总平面图 / 建筑效果图），调用支持图片输入的多模态大模型，
按图纸类型自动套用对应的提示词，生成四个维度（总图）或三个维度（单体）的设计说明，
并保存为 Markdown 文件。

只描述图面上真实可见的信息：图面未表达的内容一律写“图面未表达”，不臆造。

用法：
    python design_description.py 图纸.png --type plan
    python design_description.py 效果图.jpg --type render
    python design_description.py 图纸.png                  # 不指定则自动识别图纸类型

详细说明见 README.md
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------- 依赖检查
try:
    import requests
except ImportError:  # pragma: no cover
    sys.stderr.write("缺少依赖 requests，请先执行：pip install -r requirements.txt\n")
    raise SystemExit(2)

# 编码处理：输出被重定向/管道时用 UTF-8；直接打到 Windows 控制台时保留系统码页（GBK 能正常显示中文）
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            if _stream.isatty():
                _stream.reconfigure(errors="replace")
            else:
                _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


# ---------------------------------------------------------------- 常量配置

PROVIDERS = {
    "dashscope": {
        "label": "通义千问 VL（阿里云百炼 DashScope，OpenAI 兼容模式）",
        "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen-vl-max",
        "key_env": "DASHSCOPE_API_KEY",
        "key_url": "https://bailian.console.aliyun.com/  →  右上角「API-KEY」",
        "models_hint": "qwen-vl-max（默认，最准）、qwen-vl-plus（更便宜）、qwen3-vl-plus（新版）",
    },
    "openai": {
        "label": "OpenAI 视觉模型（GPT-4o / GPT-4.1）",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o",
        "key_env": "OPENAI_API_KEY",
        "key_url": "https://platform.openai.com/api-keys",
        "models_hint": "gpt-4o、gpt-4.1、gpt-4o-mini（更便宜）",
    },
}

# 图纸类型 → 中文名 / 默认输出文件名后缀
IMAGE_TYPES = {
    "plan": {"label": "总平面图设计说明", "slug": "总平面图"},
    "render": {"label": "建筑单体效果图设计说明", "slug": "效果图"},
}

SUPPORTED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
    ".gif": "image/gif",
}

# 单张图片原始大小建议上限（base64 后会放大约 1/3）
IMAGE_SIZE_WARN_BYTES = 7 * 1024 * 1024

# ---------------------------------------------------------------- 提示词

SYSTEM_PROMPT = """你是一名注册建筑师，负责根据图纸、效果图撰写正式的建筑设计说明文本。

必须遵守的铁律：
1. 只描述图面上真实可见的内容。凡是图上看不到的，一律不写。
2. 绝对禁止臆造：不得编造图上没有的尺寸、数量、面积、层数、地名、道路名、材料牌号、规范条文号、经济技术指标。
3. 数值只在图上明确标注时才引用，并且必须注明“图示”；图上没有数字时，用定性描述（如“较大的开敞空间”），不得换算成假数值。
4. 无法判断或图面未表达的内容，必须明确写出“图面未表达，需结合其他图纸确认”，不得用推测或套话填充。宁可写得少，也不许写不存在的东西。
5. 不写空话套话（“以人为本”“打造城市新地标”“营造高品质空间”之类）。每一句判断都要能对应到图面上的具体位置、构件或图面要素。
6. 使用规范、平实的中文建筑专业书面语，第三人称陈述，不使用“我认为”“建议”等主观口吻。
7. 直接输出 Markdown 正文，不要写开场白、不要写“以下是……”，不要用代码块包裹全文。"""

USER_PROMPT_PLAN = """这是一张建设项目**总平面图**。请仔细看图，按以下四个维度撰写总图设计说明。

输出格式（严格使用这四个二级标题，标题文字不要改）：

## 一、功能分区

- 逐一说明场地内各功能区块的名称、所在方位（东/南/西/北侧、中部、沿街一侧等）、相互位置关系。
- 说明主要出入口的方位与所朝向的道路或外部环境。
- 说明各区块与周边道路、相邻用地、保留要素（保留树木、既有建筑、水系等）的衔接关系。
- 若图上标注了用地面积、建筑面积、容积率、绿地率、建筑密度、机动车位数量等指标，如实引用并在括号内注明“图示”；未标注则写“图面未表达”。

## 二、交通组织

- 出入口的数量、位置、服务对象（人行 / 车行 / 消防 / 地库）。
- 人车分流方式；机动车流线、非机动车流线与主要人行流线的走向及相互关系。
- 停车布置方式（地面 / 地下 / 立体车库）及停车区域位置；有无停车数量标注。
- 道路宽度、转弯半径、回车场、尽端式道路等信息，仅在图上明确标注时引用并注明“图示”。
- 无障碍通行、装卸货场地、非机动车停放区等，如可见则描述，不可见则不写。

## 三、竖向设计

- 场地的标高标注、坡向、分台处理、台阶与坡道位置。
- 地下车库出入口坡道的位置与形式（直线 / 曲线、单进单出 / 双向）。
- 场地排水方向、雨水口或明沟的分布（如可见）。
- 场地标高与相邻城市道路标高的关系（图上有标高数字时才描述，否则写“图面未表达”）。

## 四、消防组织

- 消防车道是否成环、环通情况；有无尽头式消防车道及回车场。
- 消防车道的宽度、转弯半径、距建筑外墙的距离，仅在标注明确时引用并注明“图示”。
- 高层建筑或大型公共建筑的消防登高操作场地位置、尺寸（如有标注）。
- 建筑之间的防火间距（如标注）、消防控制室 / 消防水池 / 水泵房位置（如可见）。

各维度篇幅控制在 150～350 字。如果某个维度在图上确实信息很少，就只写 1～2 句并明确说明信息不足，不要为了凑字数编内容。

最后另起一段，用三级标题输出：

### 附：图面无法确认的信息

- 用简短条目列出图上看不清、缺失、或对设计说明有影响但无法判断的关键信息（例如缺少尺寸标注、图例不可辨、指北针缺失等）。若确实没有，写“无”。"""

USER_PROMPT_RENDER = """这是一张**建筑单体效果图**（三维表现图）。请注意：效果图是设计意图的表达，不等于建成实景。

请仔细看图，按以下三个维度撰写单体设计说明。

输出格式（严格使用这三个二级标题，标题文字不要改）：

## 一、风格意象

- 整体气质与形式取向（如简洁现代、几何体量、地域性表达、古典比例等），用准确的建筑语汇描述，不要用营销辞藻。
- 建筑的体量关系、形体组合方式、整体比例与尺度感。
- 主要体块的层数感、高宽比、屋顶形态（平屋顶 / 坡屋顶 / 退台 / 构架等）。
- 色彩基调与主要色彩关系。
- 建筑与画面中自然环境、道路、相邻建筑的关系。

## 二、设计手法

- 体量的穿插、咬合、悬挑、架空、退台等处理。
- 立面划分：横向与竖向的构图关系、分段方式、基座与主体的处理。
- 虚实关系：实墙与玻璃的面积关系、开窗的节奏与韵律、幕墙分格的大致尺度感（不臆造具体尺寸）。
- 屋顶处理、女儿墙、构架、遮阳构件、雨篷、入口的强调方式。
- 细部构件：栏杆、百叶、遮阳板、雨棚、入口台阶、柱子等的可见形式。
- 夜景效果图请补充描述照明方式与光色倾向。

## 三、材料质感

- 逐一列出可从图面辨认出的材料类别（玻璃幕墙 / 石材幕墙 / 金属板 / 清水混凝土 / 砖 / 木材 / 涂料 / 陶板等），并说明其在建筑上的位置。
- 每种材料的表观特征：色彩、明度、反光或哑光、透明度、纹理方向（如石材横向分缝、金属板竖向密拼等）。
- 材料之间的组合与对比关系（如玻璃的通透与石材的厚重对比、暖色木与冷色金属的对比）。
- 图中呈现的光影效果对材料质感的强化作用（如玻璃反射天空、金属板高光带）。
- 无法确认具体材料品种时，只能写材料的外观类别，并注明“具体品种图面未表达”。

各维度篇幅控制在 200～400 字。看图说话，看不清的部位直接不写，不要通用化地描述“大面积玻璃幕墙”之类图中并不存在的做法。

最后另起一段，用三级标题输出：

### 附：图面无法确认的信息

- 用简短条目列出效果图无法表达、但对设计说明有影响的信息（例如图中看不到背立面、无尺寸与层数标注、材料品种不可辨、非建成实景等）。若确实没有，写“无”。"""

DETECT_PROMPT = """请判断这张图的类型，只输出一个单词，不要输出任何其他内容：

- 如果是**总平面图**（含用地红线、建筑屋顶平面轮廓、道路与场地、指北针、坐标或标高标注、经济技术指标表等），输出：plan
- 如果是**建筑效果图**（建筑的三维透视渲染图、人视图、鸟瞰图，表现形体立面与材质），输出：render

只输出 plan 或 render。"""


# ---------------------------------------------------------------- 工具函数


def load_env_file(explicit: str | None = None) -> Path | None:
    """加载 .env。优先用 python-dotenv，没装则用内置解析器。已存在的环境变量不被覆盖。"""
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    else:
        candidates.append(Path.cwd() / ".env")
        candidates.append(Path(__file__).resolve().parent / ".env")

    env_path = next((p for p in candidates if p.is_file()), None)
    if env_path is None:
        return None

    try:
        from dotenv import load_dotenv  # type: ignore

        load_dotenv(env_path, override=False)
        return env_path
    except ImportError:
        pass

    # 内置兜底解析器：KEY=VALUE，# 开头为注释
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.lower().startswith("export "):
            line = line[7:].strip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
    return env_path


def encode_image(path: Path) -> tuple[str, int]:
    """把本地图片编码成 data URL，返回 (data_url, 原始字节数)。"""
    suffix = path.suffix.lower()
    mime = MIME_TYPES.get(suffix, "image/png")
    data = path.read_bytes()
    if not data:
        raise RuntimeError(f"图片文件为空：{path}")
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}", len(data)


def build_messages(system: str, user_text: str, data_url: str) -> list[dict]:
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]


def parse_extra_params(pairs: list[str] | None) -> dict:
    """--extra-param key=value → dict，值会尝试按 JSON 解析成 bool/数字。"""
    out: dict = {}
    for item in pairs or []:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"--extra-param 格式应为 key=value，收到：{item}")
        value = value.strip()
        try:
            out[key.strip()] = json.loads(value)
        except json.JSONDecodeError:
            out[key.strip()] = value
    return out


def call_api(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    messages: list[dict],
    temperature: float,
    max_tokens: int,
    timeout: int,
    extra: dict,
    retries: int = 3,
    verbose: bool = False,
) -> tuple[str, dict, dict]:
    """调用 OpenAI 兼容的 chat/completions 接口，返回 (正文, usage, 原始响应)。"""
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    payload.update(extra)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    last_err = "未知错误"
    for attempt in range(1, retries + 1):
        if verbose:
            print(f"  → POST {endpoint} (model={model}, 第 {attempt} 次尝试)")
        try:
            resp = requests.post(
                endpoint, headers=headers, json=payload, timeout=(15, timeout)
            )
        except requests.RequestException as exc:
            last_err = f"网络请求失败：{exc}"
        else:
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                except (ValueError, KeyError, IndexError, TypeError):
                    raise RuntimeError(
                        f"接口返回结构异常：{resp.text[:500]}"
                    ) from None
                if isinstance(content, list):  # 少数兼容实现会返回分段内容
                    content = "".join(
                        part.get("text", "")
                        for part in content
                        if isinstance(part, dict)
                    )
                if not content or not content.strip():
                    raise RuntimeError(f"模型返回了空内容，原始响应：{resp.text[:300]}")
                return content, (data.get("usage") or {}), data

            body = resp.text[:600]
            if resp.status_code in (401, 403):
                raise RuntimeError(
                    f"API Key 无效或无权限（HTTP {resp.status_code}）。\n"
                    f"请检查 .env 中的 Key、是否已实名/开通对应模型。\n返回：{body}"
                )
            if resp.status_code == 400:
                raise RuntimeError(
                    "请求被拒绝（HTTP 400）。常见原因：\n"
                    "  · 模型名写错（--model）\n"
                    "  · 图片过大或格式不支持（建议压到 4MB 以内）\n"
                    "  · 该 Key 未开通这个模型\n"
                    f"返回：{body}"
                )
            if resp.status_code == 429:
                last_err = f"触发限流（HTTP 429）：{body}"
            else:
                last_err = f"HTTP {resp.status_code}：{body}"

        if attempt < retries:
            wait = 2 ** attempt
            print(f"  ! {last_err}")
            print(f"  ! {wait} 秒后重试（{attempt}/{retries - 1}）…")
            time.sleep(wait)

    raise RuntimeError(f"调用失败（已重试 {retries} 次）：{last_err}")


def detect_image_type(
    *,
    endpoint: str,
    api_key: str,
    model: str,
    data_url: str,
    timeout: int,
    verbose: bool,
) -> str:
    """让模型先判断图纸类型，返回 'plan' 或 'render'。"""
    messages = build_messages(
        "你是一名建筑专业图纸识别助手，只做图纸类型判断。",
        DETECT_PROMPT,
        data_url,
    )
    text, _, _ = call_api(
        endpoint=endpoint,
        api_key=api_key,
        model=model,
        messages=messages,
        temperature=0.0,
        max_tokens=16,
        timeout=timeout,
        extra={},
        retries=2,
        verbose=verbose,
    )
    lowered = text.lower()
    match = re.search(r"\b(plan|render)\b", lowered)
    if match:
        return match.group(1)
    if "总平" in text or "平面" in text:
        return "plan"
    if "效果" in text or "透视" in text or "渲染" in text:
        return "render"
    raise RuntimeError(
        f"无法自动识别图纸类型，模型返回：{text.strip()[:100]!r}\n"
        "请用 --type plan 或 --type render 手动指定。"
    )


def unique_output_path(path: Path, overwrite: bool) -> Path:
    """若目标文件已存在且未指定 --overwrite，自动追加 _2 / _3 序号。"""
    if overwrite or not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        candidate = path.with_name(f"{stem}_{i}{suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"输出目录中同名文件过多：{path}")


def write_markdown(
    out_path: Path,
    *,
    body: str,
    image_path: Path,
    type_key: str,
    model: str,
    provider: str,
    elapsed: float,
    usage: dict,
) -> None:
    meta = IMAGE_TYPES[type_key]
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    provider_label = PROVIDERS[provider]["label"] if provider in PROVIDERS else provider

    rows = [
        ("图纸文件", f"`{image_path.name}`"),
        ("图纸类型", f"{meta['slug']}（`{type_key}`）"),
        ("生成模型", f"`{model}`（{provider_label}）"),
        ("生成时间", f"{stamp}（耗时 {elapsed:.1f}s）"),
    ]
    if usage:
        rows.append(
            (
                "Token 用量",
                f"输入 {usage.get('prompt_tokens', '—')} / "
                f"输出 {usage.get('completion_tokens', '—')} / "
                f"合计 {usage.get('total_tokens', '—')}",
            )
        )

    lines = [
        f"# {meta['label']}",
        "",
        "> 本文件由程序自动生成（AI 图生建筑设计说明）。",
        "",
        "| 项 | 内容 |",
        "| --- | --- |",
        *[f"| {k} | {v} |" for k, v in rows],
        "",
        "---",
        "",
        body.strip(),
        "",
        "---",
        "",
        "**免责与复核提示**：以上内容由多模态大模型根据图面信息生成，仅描述图上可见内容。",
        "凡标注“图面未表达 / 需结合其他图纸确认”的部分，以及所有尺寸、指标、材料品种，",
        "均须由设计人对照原始图纸核实后方可用于正式成果。",
        "",
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- 主流程


def fail(message: str) -> int:
    """打印错误并返回退出码（先把 stdout 刷出去，避免日志顺序错乱）。"""
    sys.stdout.flush()
    sys.stderr.write(message if message.endswith("\n") else message + "\n")
    sys.stderr.flush()
    return 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="design_description.py",
        description="AI 图生建筑设计说明：读一张总平面图或效果图，生成对应的设计说明 Markdown。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""示例：
  python design_description.py 总平面图.png --type plan
  python design_description.py 效果图.jpg --type render -o 说明/单体.md
  python design_description.py 图纸.png                 # 自动识别图纸类型
  python design_description.py 图纸.png --provider openai --model gpt-4.1
""",
    )
    p.add_argument("image", help="图片路径（支持 png / jpg / jpeg / webp / bmp / gif）")
    p.add_argument(
        "-t",
        "--type",
        choices=["plan", "render"],
        help="图纸类型：plan=总平面图，render=建筑效果图。不填则自动识别。",
    )
    p.add_argument("-o", "--out", help="输出 .md 路径，默认 output/<图名>_<类型>.md")
    p.add_argument(
        "--provider",
        default=os.getenv("DESIGN_LLM_PROVIDER", "dashscope"),
        choices=sorted(PROVIDERS),
        help="模型服务商，默认 dashscope（通义千问 VL）",
    )
    p.add_argument("--model", help="模型名，默认取服务商的推荐模型")
    p.add_argument("--endpoint", help="自定义接口地址（覆盖服务商默认值）")
    p.add_argument("--api-key", help="直接传 Key（不推荐，建议用 .env）")
    p.add_argument("--env-file", help="指定 .env 文件路径，默认查找当前目录和脚本目录")
    p.add_argument("--temperature", type=float, default=0.2, help="采样温度，默认 0.2")
    p.add_argument("--max-tokens", type=int, default=2048, help="最大输出 token，默认 2048")
    p.add_argument("--timeout", type=int, default=180, help="读取超时秒数，默认 180")
    p.add_argument(
        "--extra-param",
        action="append",
        metavar="KEY=VALUE",
        help="附加到请求体的参数，可重复。如 --extra-param vl_high_resolution_images=true",
    )
    p.add_argument("--overwrite", action="store_true", help="允许覆盖同名输出文件")
    p.add_argument("--raw", help="把接口原始响应保存到该 JSON 文件，便于排查")
    p.add_argument("--print-prompt", action="store_true", help="只打印提示词，不调用接口（无需 Key）")
    p.add_argument("-v", "--verbose", action="store_true", help="打印详细过程")
    return p


def print_prompts(type_key: str | None) -> None:
    """打印将要发送的提示词（不需要图片，也不需要 Key）。"""
    line = "=" * 70
    print(line)
    print(f"[SYSTEM]\n{SYSTEM_PROMPT}\n")
    if type_key:
        print(line)
        print(f"[USER · {IMAGE_TYPES[type_key]['slug']}]\n"
              f"{USER_PROMPT_PLAN if type_key == 'plan' else USER_PROMPT_RENDER}")
    else:
        print(line)
        print(f"[识别用 USER]\n{DETECT_PROMPT}\n")
        print(line)
        print(f"[USER · 总平面图]\n{USER_PROMPT_PLAN}\n")
        print(line)
        print(f"[USER · 效果图]\n{USER_PROMPT_RENDER}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    # 0) --print-prompt：只打印提示词，不校验图片、不需要 Key
    if args.print_prompt:
        print_prompts(args.type)
        return 0

    # 1) 校验图片
    image_path = Path(args.image).expanduser()
    if not image_path.is_file():
        return fail(f"[错误] 找不到图片文件：{image_path}")
    if image_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return fail(
            f"[错误] 不支持的图片格式：{image_path.suffix}\n"
            f"       支持：{'、'.join(sorted(SUPPORTED_SUFFIXES))}"
        )

    # 2) 确定图纸类型与提示词
    provider = PROVIDERS[args.provider]
    type_key = args.type

    # 3) 读取 .env 与 API Key
    env_path = load_env_file(args.env_file)
    if env_path:
        print(f"[信息] 已加载环境变量文件：{env_path}")
    else:
        print("[信息] 未找到 .env 文件，将只从系统环境变量读取 Key")

    api_key = (
        args.api_key
        or os.getenv(provider["key_env"])
        or os.getenv("DESIGN_LLM_API_KEY")
    )
    if not api_key:
        return fail(
            f"[错误] 未找到 API Key（环境变量 {provider['key_env']}）。\n\n"
            f"解决办法：\n"
            f"  1) 复制 .env.example 为 .env\n"
            f"  2) 在 .env 中填写 {provider['key_env']}=你的Key\n"
            f"     获取地址：{provider['key_url']}"
        )
    api_key = api_key.strip()

    model = args.model or provider["model"]
    endpoint = args.endpoint or provider["endpoint"]
    extra = parse_extra_params(args.extra_param)

    # 4) 编码图片
    data_url, raw_size = encode_image(image_path)
    size_mb = raw_size / 1024 / 1024
    print(f"[信息] 图片：{image_path.name}（{size_mb:.2f} MB，base64 后约 {size_mb * 4 / 3:.2f} MB）")
    if raw_size > IMAGE_SIZE_WARN_BYTES:
        print(
            "  ! 图片较大，部分接口对 base64 图片有大小限制（常见约 10MB），"
            "失败时请先压缩图片尺寸。"
        )
    print(f"[信息] 服务商：{provider['label']}｜模型：{model}")

    started = time.time()
    usage: dict = {}

    try:
        # 5) 自动识别类型
        if type_key is None:
            print("[流程] 未指定 --type，先让模型识别图纸类型…")
            type_key = detect_image_type(
                endpoint=endpoint,
                api_key=api_key,
                model=model,
                data_url=data_url,
                timeout=args.timeout,
                verbose=args.verbose,
            )
            print(f"[流程] 识别结果：{type_key}（{IMAGE_TYPES[type_key]['slug']}）")

        user_prompt = USER_PROMPT_PLAN if type_key == "plan" else USER_PROMPT_RENDER

        # 6) 生成设计说明
        print(f"[流程] 正在生成「{IMAGE_TYPES[type_key]['label']}」…")
        messages = build_messages(SYSTEM_PROMPT, user_prompt, data_url)
        body, usage, raw = call_api(
            endpoint=endpoint,
            api_key=api_key,
            model=model,
            messages=messages,
            temperature=args.temperature,
            max_tokens=args.max_tokens,
            timeout=args.timeout,
            extra=extra,
            verbose=args.verbose,
        )
    except RuntimeError as exc:
        return fail(f"\n[失败] {exc}")
    except KeyboardInterrupt:
        sys.stdout.flush()
        sys.stderr.write("\n[中断] 用户取消\n")
        return 130

    elapsed = time.time() - started

    # 7) 写文件
    if args.out:
        out_path = Path(args.out).expanduser()
        # 以 .md / .markdown 结尾才当文件名，否则当目录并自动命名
        if out_path.suffix.lower() not in (".md", ".markdown") or out_path.is_dir():
            out_path = out_path / f"{image_path.stem}_{type_key}.md"
    else:
        out_path = Path("output") / f"{image_path.stem}_{type_key}.md"
    out_path = unique_output_path(out_path, args.overwrite)

    write_markdown(
        out_path,
        body=body,
        image_path=image_path,
        type_key=type_key,
        model=model,
        provider=args.provider,
        elapsed=elapsed,
        usage=usage,
    )

    if args.raw:
        Path(args.raw).write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"[信息] 原始响应已保存：{args.raw}")

    print(f"[完成] 已生成：{out_path.resolve()}")
    if usage:
        print(
            f"[用量] 输入 {usage.get('prompt_tokens', '—')} tokens / "
            f"输出 {usage.get('completion_tokens', '—')} tokens"
        )
    print(f"[耗时] {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
