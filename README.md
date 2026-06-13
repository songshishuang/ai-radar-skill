# ai-radar

> 一句话要一份 AI 行业情报研报。聚合国外核心 AI 源 → 宿主 agent 直接出中文金字塔研报，**零 API key、零部署**。

ai-radar 是一个 [Agent Skill](https://docs.claude.com/en/docs/claude-code/skills)。装好后，在你的 agent 工具里说一句「**给我今天的 AI 日报**」即可触发：脚本抓取 → agent 摘要/分类/评分/解读 → 输出一份 2 分钟读完的中文研报（⚡速览 → 🔥必读 → 📌关注 → 📚附录）。

## 它能做什么

- **聚合**：OpenAI / Anthropic / Google / Meta / Mistral 等厂商官方源 + Hacker News + HuggingFace 论文与模型 + TechCrunch/The Verge 等媒体 + X 关键人物（共 26 源，可增删）。
- **加工**：中文摘要、8 类分类、实体标注、重要度评分——全部由宿主 agent 完成，不调任何外部 LLM API。
- **多视角**：`pm`（默认）/ `engineer` / `investor` / `researcher`，同一批资讯按你的身份重新加权与解读。
- **三档**：日报（36h）/ 周报（7d）/ 月报（30d）。
- **双模式**：连得到你自建的「AI 情报站」就直接拉它已生成的报告（同源）；连不到就本地现抓现做。

## 安装

### Claude Code

```bash
# 方式一：复制到个人 skills 目录
cp -r ai-radar ~/.claude/skills/ai-radar

# 方式二：放进项目的 .claude/skills/ 让团队共享
mkdir -p .claude/skills && cp -r ai-radar .claude/skills/
```

重启 / 新开会话后，说「AI 日报」「今天 AI 有什么」即可触发。

### 其它 agent 工具

skill 是纯文件（SKILL.md + scripts + references），跨平台通用。按你的工具的 skill 安装路径放入即可：

| 平台 | 安装路径 |
|---|---|
| Claude Code / Desktop | `~/.claude/skills/ai-radar/` |
| Cursor | `<project>/.cursor/skills/ai-radar/` |
| Codex / 其它 | 各自的 skills 目录 |

唯一运行依赖：**Python 3.8+**（抓取脚本用标准库即可，无需 pip install；装了 `feedparser`/`httpx` 会自动启用更鲁棒的解析）。

## 用法

```
你：给我今天的 AI 日报
你：从工程师视角看这周的 AI 动态        # lens=engineer, range=weekly
你：这个月 AI 投资圈发生了什么          # lens=investor, range=monthly
你：只看大厂和开源，今天的             # categories=vendor,community
```

## 连接你自己的 AI 情报站（可选，数据同源）

如果你部署了完整版「AI 情报站」（含定时管道 + 网站 + 邮件/IM 订阅），设置环境变量即可让 skill 直接复用它已生成的报告：

```bash
export AI_RADAR_API=http://localhost:8000          # 或你的 VPS 域名
```

此后 skill 进入**连接模式**，输出与你的网站/邮件字节级同源。详见 `references/deploy.md`。

完整版（持续运行 + 订阅推送）部署见主仓库 `deploy/`（VPS 五容器）或 `.github/workflows/`（GitHub Pages 静态站）。在线 demo：https://songshishuang.github.io/ai-radar/

## 自定义数据源

编辑 `scripts/sources.json`：`enabled:false` 禁用某源；`method:dynamic` 的源由 agent 用 WebSearch 补抓（适合 X/Twitter 等无 RSS 的源）。

## 结构

```
ai-radar/
├── SKILL.md                  # 触发 + 双模式工作流 + 参数
├── scripts/
│   ├── fetch.py              # 自包含抓取器（stdlib 优先，零必装依赖）
│   └── sources.json          # 26 源清单
├── references/
│   ├── report-format.md      # 金字塔研报模板
│   ├── lenses.md             # 4 视角加权与解读重点
│   └── deploy.md             # 连接模式契约 + 自托管指引
├── assets/
│   └── sample-report.md      # 样例输出
└── tests/
    └── test_fetch.py         # 抓取器离线解析测试
```
