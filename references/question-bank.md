# V0.4 题库说明

这份文档说明本地题库的结构、用途和选题方式。运行时请直接依赖仓库中的本地 JSON 数据，不依赖在线抓取。

## 本地数据文件

- `data/fundamental_questions.json`：本地八股 / CS 基础题卡
- `data/fundamental_knowledge_base.json`：本地知识库索引
- `data/algorithm_questions.json`：本地算法题卡
- `data/role_profiles.json`：岗位画像配置
- `data/interview_mode_profiles.json`：面试模式配置

这些文件就是面试运行时的 source of truth。

## 八股题卡结构

每张八股题卡通常包含：

- `id`
- `topic`
- `subtopic`
- `difficulty`
- `layer`
- `question`
- `expected_points`
- `followups`
- `related_keywords`
- `role_tags`

题库按主题组织，常见主题包括：

- MySQL
- Redis
- 网络
- 操作系统
- JVM
- 并发
- Spring
- 分布式
- 消息队列
- 系统设计
- AI Agent
- RAG

## 分层规则

- `basic`：适合 `/strength NPC` 或 `/strength 拉满人`
- `standard`：适合 `/strength 人上人`
- `deep`：适合 `/strength 顶级` 或 `/strength 大牛`

## 岗位偏置

示例：

- `backend-java`
  - Spring / JVM / 并发 / MySQL / Redis / 分布式
- `backend-python`
  - 接口设计 / Redis / 网络 / 操作系统 / 高可用
- `backend-go`
  - 网络 / 并发 / Redis / 分布式 / 高可用
- `ai-agent`
  - Agent / 上下文工程 / 工具调用 / 状态管理 / 模型服务化
- `ai-rag`
  - RAG / GraphRAG / 检索重排 / 评估 / 知识更新
- `ai-eval`
  - RAG 评估 / 检索重排 / 知识更新 / 模型评测链路
- `sre-platform`
  - 操作系统 / 网络 / 高可用 / 平台稳定性 / 网关

岗位偏置配置统一来自：

- `data/role_profiles.json`

## 算法题卡结构

每张算法题卡通常包含：

- `id`
- `title`
- `difficulty`
- `tags`
- `prompt`
- `expected_approaches`
- `hints`
- `edge_cases`
- `related_keywords`
- `role_tags`
- `public_release_mode`

公开仓库版算法题库保留本地重写后的题面和元数据，不附带官方 HTML、图片或直链。

## 自动选题

当用户需要：

- 基于简历的面试计划
- 基于 JD 的定向题单
- 八股密集训练
- 算法专项练习
- 结构化选题导出

优先使用：

```bash
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --view interview_mode
```

其他常见例子：

```bash
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --focus "Redis, MySQL, FastAPI" --level 中等 --view interview_mode
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --jd-file jd.txt --mode "JD 定向面" --fundamentals-count 8 --algorithms-count 1 --view interview_mode
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --mode "算法陪练" --level 困难 --algorithms-count 3 --view candidate_mode
python cs-tech-interviewer/scripts/select_questions.py <parsed_dir>/candidate_profile.json --strength 顶级 --target-role backend-java --role-profiles cs-tech-interviewer/data/role_profiles.json --view interview_mode
```

典型输出：

```text
question_selection/
  question_selection.json
  question_selection_interview_mode.md
  question_selection_candidate_mode.md
```

## 视图模式

- `interview_mode`
  - 面试官视角
  - 包含选题理由、标签、岗位偏置和元数据
- `candidate_mode`
  - 候选人视角
  - 只展示候选人需要看到的题面内容

## 选题启发式

选题器会综合这些信号打分：

1. 简历技能、项目技术栈、风险点和推断岗位
2. JD 关键词命中和重复强调项
3. 显式 `/focus`
4. `backend`、`java`、`ai`、`frontend`、`graphics`、`algorithm` 等 role tag
5. `/level` 指定的算法难度

在真实面试流程里，请按题逐个使用，不要默认一次性把整份题单全部丢给候选人。

## 使用边界

题库运行时只保留本地整理好的题卡和元数据。

公开仓库版应避免把外部来源的原始 HTML、图片、直链或数据采集痕迹放进运行时题库文件。
