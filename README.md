# AI 图生建筑设计说明

丢一张图进去，出来一份设计说明。

读取**总平面图**或**建筑单体效果图**，调用多模态大模型，按图纸类型自动套用对应的专业提示词，生成结构化的设计说明，保存为 Markdown 文件。

> **English summary**: A CLI tool that reads an architectural site plan or building rendering, sends it to a multimodal LLM (Qwen-VL / GPT-4o, via OpenAI-compatible APIs), and generates a structured Chinese architectural design description as Markdown. It works on a strict no-fabrication prompt: anything not visible in the drawing is explicitly reported as "not shown" instead of being invented.

---

## 它输出什么

| 图纸类型 | 输出维度 |
| --- | --- |
| **总平面图** `--type plan` | 功能分区、交通组织、竖向设计、消防组织 |
| **建筑单体效果图** `--type render` | 风格意象、设计手法、材料质感 |

每个维度都会附一节「图面无法确认的信息」，列出图纸缺失或看不清的关键内容（未标注指标、指北针缺失等），方便复核。

**核心原则：只写图上真实看得见的东西。** 看不清、没标注的，一律写"图面未表达"，不给模型编造的空间。

---

## 用了什么多模态 API

程序通过 **OpenAI 兼容格式**（`/chat/completions`）调用多模态大模型，图片以 base64 data URL 的形式随消息发送：

```json
{
  "role": "user",
  "content": [
    {"type": "text",      "text": "……提示词……"},
    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBORw0K..."}}
  ]
}
```

支持的服务商：

| 服务商 | 参数 | 默认模型 |
| --- | --- | --- |
| **通义千问 VL**（阿里云百炼 DashScope） | `--provider dashscope`（默认） | `qwen-vl-max` |
| **OpenAI** | `--provider openai` | `gpt-4o` |

因为用的是通用兼容格式，任何提供 OpenAI 兼容接口的视觉模型都能接（智谱 GLM-4V、本地 vLLM 等），用 `--endpoint` + `--model` 指定即可。

---

## 安装

需要 Python 3.9 或以上。

```bash
git clone https://github.com/<你的用户名>/<仓库名>.git
cd <仓库名>
pip install -r requirements.txt
```

依赖只有两个，而且 `python-dotenv` 是**可选**的——脚本内置了简易 .env 解析器，只装 `requests` 也能跑：

```bash
pip install requests        # 最小安装
```

---

## 配置 API Key

Key 从环境变量读取，**不写死在代码里**。

**1. 创建 `.env`**

```bash
cp .env.example .env          # Windows: copy .env.example .env
```

**2. 填入 Key**

```ini
DASHSCOPE_API_KEY=sk-你的真实Key
```

**3. 去哪儿拿 Key**

| 方案 | 获取地址 |
| --- | --- |
| 通义千问 VL（默认） | <https://bailian.console.aliyun.com/> → 右上角「API-KEY」 |
| OpenAI | <https://platform.openai.com/api-keys> |

> `.env` 已在 `.gitignore` 中，不会被提交。**不要把 Key 写进 `.env.example`** ——那个文件是要提交的。

---

## 运行

### 命令行

```bash
# 总平面图
python design_description.py 总平面图.png --type plan

# 效果图
python design_description.py 效果图.jpg --type render

# 不指定类型，让模型自己判断
python design_description.py 图纸.png
```

### Windows 用户：双击运行

仓库里带了一个 `run.bat`，**把图片文件拖到它图标上**即可，按提示选类型。也可以双击它，再按提示把图片拖进窗口。它自动处理 Python 路径、中文编码、跑完暂停。

### 结果在哪

默认输出到 `output/<图名>_<plan|render>.md`，终端最后一行会打印完整路径。同名文件不会覆盖，自动加序号 `_2`、`_3`。

### 参数

| 参数 | 作用 |
| --- | --- |
| `-t, --type plan\|render` | 指定图纸类型；不填则自动识别 |
| `-o, --out 路径` | 以 `.md` 结尾当文件名，否则当目录（自动命名为 `<图名>_<类型>.md`） |
| `--provider dashscope\|openai` | 换服务商，默认通义千问 |
| `--model 模型名` | 换模型 |
| `--endpoint 地址` | 自定义接口地址 |
| `--overwrite` | 允许覆盖同名输出 |
| `--print-prompt` | 只打印提示词、不调接口（**不需要 Key**，改提示词时先看这个） |
| `--raw 文件名.json` | 保存接口原始响应，排查问题用 |
| `--temperature 0.2` | 采样温度，默认 0.2（越低越保守） |
| `--max-tokens 2048` | 输出上限，说明写得更长就调大 |
| `--extra-param K=V` | 附加请求参数，可重复 |
| `-v, --verbose` | 打印详细过程 |
| `--env-file 路径` | 指定 .env 位置 |

完整帮助：`python design_description.py --help`

### 示例

```bash
# 输出到指定目录
python design_description.py 图纸/总平.png -t plan -o 说明/

# 改用 OpenAI
python design_description.py 效果图.jpg -t render --provider openai --model gpt-4.1

# 先看提示词，不花钱
python design_description.py 效果图.jpg -t render --print-prompt

# 批量处理
for f in 图纸/*.png; do python design_description.py "$f" -t plan; done
```

---

## 支持的模型

### 通义千问 VL（`--provider dashscope`）

| 模型名 | 说明 |
| --- | --- |
| `qwen-vl-max` | **默认**。旗舰，图纸细节认得最准 |
| `qwen-vl-plus` | 便宜、快，日常够用 |
| `qwen3-vl-plus` | 新版 |
| `qwen-vl-max-latest` | ⚠️ 这个别名在部分账号上未开通，会报 403，别用 |

### OpenAI（`--provider openai`）

需要额外填 `OPENAI_API_KEY`。

| 模型名 | 说明 |
| --- | --- |
| `gpt-4o` | **默认**，视觉能力成熟稳定 |
| `gpt-4.1` | 更新，指令跟随更好 |
| `gpt-4o-mini` | 便宜，简单图够用 |

### 接其他兼容服务

```bash
python design_description.py 图纸.png -t plan \
  --endpoint https://open.bigmodel.cn/api/paas/v4/chat/completions \
  --model glm-4v-plus
```

---

## 输出长什么样

```markdown
# 总平面图设计说明

| 项 | 内容 |
| --- | --- |
| 图纸文件 | `总平面图.png` |
| 图纸类型 | 总平面图（`plan`） |
| 生成模型 | `qwen-vl-max`（通义千问 VL…） |
| 生成时间 | 2026-09-28 10:30:00（耗时 21.4s） |
| Token 用量 | 输入 1523 / 输出 1102 / 合计 2625 |

---

## 一、功能分区

场地北侧为…（正文，只描述图面可见内容）

## 二、交通组织
## 三、竖向设计
## 四、消防组织

### 附：图面无法确认的信息

- 图中未标注用地面积、容积率等经济技术指标。
- 指北针缺失，方位描述依据图面默认朝向。
```

---

## 关于「不臆造」

系统提示词里写死了 7 条铁律，主要几条：

1. 只描述图上可见内容，看不到的不写。
2. 禁止编造图上没有的尺寸、面积、层数、道路名、材料牌号、规范条号。
3. 数值只在图上标注时才引用，且必须注明「图示」；没标注就用定性描述，不许换算成假数字。
4. 判断不了的写「图面未表达，需结合其他图纸确认」。
5. 不写"以人为本""打造新地标"这类空话，每句判断都要能指回图上某个具体位置。
6. 效果图额外提示「效果图≠建成实景」。

**但这仍然是 AI 生成的文本。** 所有尺寸、指标、材料品种，以及所有标注"图面未表达"的地方，都必须由设计人对照原图核实后才能进正式成果。文末自动附了复核提示。

---

## 常见问题

**Q：报错 `未找到 API Key`**
`.env` 没建、名字打错（比如存成了 `.env.txt`）、或者 Key 那一行没写 `DASHSCOPE_API_KEY=`。用 `-v` 看程序有没有加载到 .env。

**Q：HTTP 401**
Key 无效或写错了。

**Q：HTTP 403 `access_denied`**
**Key 本身是好的，是账号没开通这个模型。** 换模型即可：

```bash
python design_description.py 图.png -t plan --model qwen-vl-max
```

如果全都不行，去[百炼控制台](https://bailian.console.aliyun.com/)确认已完成实名认证，并在「模型广场」开通对应模型。

**Q：HTTP 400，提示模型不存在**
模型名写错了，或该 Key 没开通此模型。

**Q：图片太大报错**
压到 4MB 以内、长边 2000px 左右再跑：

```bash
pip install pillow
python -c "from PIL import Image; im=Image.open('大图.png'); im.thumbnail((2000,2000)); im.save('小图.png')"
```

**Q：识别的图纸类型不对**
用 `--type plan` 或 `--type render` 手动指定。

**Q：说明太短 / 太啰嗦**
调 `--max-tokens 3000`；或直接编辑 `design_description.py` 顶部的 `USER_PROMPT_PLAN` / `USER_PROMPT_RENDER`，改完用 `--print-prompt` 预览。

**Q：Windows 控制台中文乱码**
程序已处理：直接输出到控制台时用系统码页（GBK），重定向/管道时用 UTF-8。若仍有乱码，执行 `chcp 65001` 切换为 UTF-8。

---

## 文件说明

| 文件 | 作用 |
| --- | --- |
| `design_description.py` | 主程序。提示词在文件顶部，想改风格改这里 |
| `run.bat` | Windows 双击启动器 |
| `requirements.txt` | 依赖清单 |
| `.env.example` | 配置模板，复制成 `.env` 后填 Key |
| `output/` | 生成的说明文件（自动创建，已 gitignore） |

---

## 说明

- 本项目与阿里云、OpenAI 均无关联，仅调用其公开 API。
- 生成内容仅供设计辅助参考，不构成设计成果，须由设计人复核后使用。
