# CS 技术面试官 Skill

> 基于简历与 JD 的中文 CS 技术面试模拟、追问、评分与复盘工具。

它把一场技术面试拆成可配置、可追问、可落盘、可复盘的流程：从简历解析、题库选题、项目深挖，到算法陪练、阶段评分、结构化复盘和简历修改建议。

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![AgentSkills](https://img.shields.io/badge/AgentSkills-Standard-green)](https://agentskills.io)
[![Language](https://img.shields.io/badge/Language-ZH%20%7C%20EN-lightgrey)](README_EN.md)

[安装](#installation) · [快速开始](#quick-start) · [核心能力](#features) · [面试模式](#interview-modes) · [Session 与产物](#session-artifacts) · [English](README_EN.md)

---

## 适用场景

这个 skill 适合想系统准备技术面试的人，尤其是：

- 后端、AI、RAG、SRE 等方向的候选人
- 想围绕简历项目做高强度追问的人
- 想按 JD 做岗位定向模拟的人
- 想把面试过程沉淀成评分、复盘和下一轮计划的人
- 想把面试暴露的问题回流成简历修改建议的人

它不是随机出题器，更像一个中文技术面试控制台：根据简历、JD、岗位画像、题库偏置和会话状态机，组织一场更像真实技术面的模拟。

JD 不只是筛题条件。skill 会把 JD 记成这场面试的岗位语境，用来决定面试官优先追问什么、按什么标准判断匹配度。

公开发布版仓库中的算法题库会保留本地重写后的完整题面、题目身份、标签、难度、选题信号、预期思路和提示，但不分发官方 HTML 题面、图片或直链。

<a id="features"></a>

## 核心能力

| 能力 | 说明 |
| --- | --- |
| 简历解析 | 支持 PDF / DOCX / Markdown / TXT，输出结构化候选人画像 |
| 本地题库 | 内置八股题库、算法题卡片和本地知识库元数据 |
| JD 语境记忆 | 会优先接收 JD，并把它固化成整场面试的岗位语境 |
| `/role` 一等能力 | 支持 `backend-java`、`ai-rag`、`sre-platform` 等角色偏置 |
| 多模式面试 | 支持完整模拟、项目深挖、八股快问快答、算法陪练等模式 |
| Session 状态机 | 每场面试独立落盘，支持暂停、继续、跳题、提示和中途评分 |
| 结构化复盘 | 统一产出 `interview_evaluation.json / md` |
| 简历修改建议 | 支持静态建议，以及面试后结合 transcript 的证据增强建议 |

<a id="installation"></a>

## 安装

这是一个 skill 仓库，不是独立 Web 服务。把它放到 Agent 可读取的 skill 目录即可。

```bash
git clone <your-repo-url> cs-tech-interviewer
cd cs-tech-interviewer
pip install -r requirements.txt
```


如果需要解析 PDF 简历，建议额外安装 `MinerU`。它不是 skill 的硬依赖，但会影响 PDF 简历解析路径。

```bash
pip install -U "mineru[pipeline]"
```



<a id="quick-start"></a>

## 快速开始

在 Codex 中调用这个 skill：

```text
使用 $cs-tech-interviewer 来进行一份基于简历的计算机模拟面试，并生成一份结构化反馈报告。
```

典型路径：

```text
提供简历或简历文本
-> 先提供目标 JD，让面试官记住这场岗位语境
-> 确认 /role /strength /mode /focus
-> /start
-> /score
-> /report
```

如果你直接粘贴一整段岗位描述，不需要先改成命令格式。skill 会把它当作 `/jd` 处理，并记住这份 JD。

常用命令：

| 命令 | 用途 |
| --- | --- |
| `/role <value>` | 设置岗位画像，例如 `backend-java`、`ai-rag` |
| `/jd <text>` | 提供岗位描述，让面试官按这份 JD 建立岗位语境 |
| `/mode <value>` | 设置面试模式 |
| `/focus <topics>` | 指定重点追问方向 |
| `/start` | 开始当前 session |
| `/hint` | 获取提示 |
| `/skip` | 跳过当前题 |
| `/score` | 生成当前阶段评分 |
| `/report` | 生成最终结构化复盘 |

<a id="interview-modes"></a>

## 面试模式

| 模式 | 适合场景 |
| --- | --- |
| `完整模拟` | 走完整技术面链路：自我介绍、项目、八股、算法、反问、复盘 |
| `项目深挖` | 专门拷打项目 ownership、架构取舍、指标和工程闭环 |
| `八股快问快答` | 高频 CS 基础知识密集抽查 |
| `算法陪练` | 多题算法练习，重点看思路、复杂度、边界和 hint 依赖 |
| `JD 定向面` | 围绕岗位 JD 做能力匹配和风险追问 |
| `简历拷打` | 盯住简历里最容易被质疑的表述 |
| `复盘教练` | 基于 transcript 或结构化记录生成复盘 |

模式行为的 source of truth 是：

```text
data/interview_mode_profiles.json
```

它统一维护 stage sequence、题量、选题策略、评分策略、报告重点和自动判题偏置。

<a id="session-artifacts"></a>

## Session 与产物

每场面试都会落为独立 session 目录。

如果不传 `--sessions-root`，默认写到用户当前工作目录下的：

```text
./sessions/
```

典型产物：

```text
<session_dir>/
  session_state.json
  session_brief.md
  transcript.json
  question_selection.json
  question_selection/
    question_selection.md
    question_selection_interview_mode.md
    question_selection_candidate_mode.md
  score_snapshot.json
  score_snapshot.md
  interview_evaluation.json
  interview_evaluation.md
```

其中：

- `session_state.json` 记录当前状态机运行状态
- `session_state.json.current_question` 会带 `jd_context`，保证运行态也记住岗位语境
- `session_brief.md` 是这场 session 的开场摘要卡，方便快速查看 `/role`、`/strength`、`/focus` 与 Top 5 selected topics
- `transcript.json` 记录作答证据
- `question_selection.json` 记录本场选题结果
- `question_selection.md` 是默认的人类可读选题摘要，并显式展示 `JD Context`
- `score_snapshot.json / md` 是中途评分
- `interview_evaluation.json` 是最终复盘的 machine-readable source of truth
- `interview_evaluation.md` 是人类可读复盘报告

## 仓库结构

```text
cs-tech-interviewer/
├── SKILL.md
├── agents/
│   └── openai.yaml
├── data/
├── scripts/
├── references/
└── .gitignore
```

| 路径 | 作用 |
| --- | --- |
| `SKILL.md` | skill 主说明与交互规则 |
| `agents/` | skill 元信息 |
| `data/` | 题库、岗位画像、模式配置 |
| `scripts/` | 简历解析、选题、状态机、评分与复盘脚本 |
| `references/` | 细化说明、schema 和 prompt 模板 |

## 边界与隐私

这个仓库默认不附带真实简历或运行产物。

这个 skill 的目标是帮助候选人发现问题、组织表达、准备下一轮面试，不承诺“包过面试”。

## 数据来源

- 八股 / 知识库的主题组织参考了 [`Snailclimb/JavaGuide`](https://github.com/Snailclimb/JavaGuide)
- 算法题的高频分布参考了 [`afatcoder/LeetcodeTop`](https://github.com/afatcoder/LeetcodeTop)

若有侵权将立即删除。

## 项目状态

当前版本 V1.0：

```text
简历解析 -> 自动选题 -> 多模式面试 -> 作答记录 -> 阶段评分 -> 结构化复盘 -> 简历修改建议
```
