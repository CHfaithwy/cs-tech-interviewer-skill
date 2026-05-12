# 选题与追问策略

这份文档说明如何根据简历、JD、岗位方向和面试模式来组织问题、推进追问，并控制算法互动节奏。

## 简历解析重点字段

建议从简历中提取或推断：

```yaml
candidate_profile:
  name:
  education:
    school:
    degree:
    major:
    graduation:
  target_roles: []
  skills:
    languages: []
    frameworks: []
    databases: []
    tools: []
  projects:
    - name:
      role:
      tech_stack: []
      claims: []
      metrics: []
      possible_risks: []
  internships: []
  publications_or_competitions: []
```

## 简历风险信号

这些表述通常更容易被追问：

- 动词很大，但 ownership 不清：例如“参与”“负责核心模块”“优化”“搭建平台”
- 罗列技术名词，但缺少实现细节
- 声称性能提升，却没有基线、指标、方法或观测窗口
- 提到缓存、数据库、并发、模型、Agent、RAG、部署，但说不清失败处理
- 项目结果写得很满，但说不清自己具体做了什么
- 缺少 tradeoff、替代方案、测试、监控或复盘

## JD 解析字段

```yaml
job_description:
  role_title:
  required_skills: []
  preferred_skills: []
  responsibilities: []
  seniority: internship | campus | experienced | unknown
  interview_focus: []
```

JD 用来决定追问权重：

- 如果简历和 JD 关键词强匹配，优先做深挖
- 如果 JD 强调某项能力，但简历缺证据，优先做诊断式追问
- 面后报告里应把这类能力缺口回流到 `jd_fit_gaps`

## 项目深挖维度

| 维度 | 常见问题 |
| --- | --- |
| 背景 | 这个项目解决了什么问题，为什么值得做？ |
| 角色 | 哪部分是你亲自做的，哪部分不是？ |
| 架构 | 主要模块、数据流和依赖关系是什么？ |
| 难点 | 最难的技术问题是什么，为什么难？ |
| 取舍 | 为什么选这个方案，不选其他方案？ |
| 指标 | 怎么衡量效果？前后变化是什么？ |
| 工程闭环 | 怎么测试、部署、监控、处理失败？ |
| 扩展性 | 如果流量或数据量涨 10 倍，先坏在哪里？ |
| 复盘 | 现在回头看，你会怎么重构？ |

## 常见追问链模板

### Redis 缓存

1. 你缓存了什么数据？
2. 为什么这类数据需要缓存？
3. key 和 TTL 怎么设计？
4. 怎么处理缓存穿透、击穿、雪崩？
5. 怎么保证 Redis 和数据库的一致性？
6. 你怎么衡量性能提升？
7. 如果流量涨 10 倍，会先出现什么问题？

### 数据库优化

1. 慢的是哪条 SQL？
2. 你怎么定位瓶颈？
3. `EXPLAIN` 看到了什么？
4. 你改了什么索引或查询写法？
5. 为什么这个索引适合这个查询模式？
6. 新索引引入了什么写入或存储成本？
7. 你怎么验证优化真的生效？

### LLM / RAG / Agent

1. 用户任务是什么？成功指标是什么？
2. 你怎么做切分、检索、排序和上下文组装？
3. 你怎么评估答案质量？
4. 你怎么处理幻觉、知识过期和工具失败？
5. Agent 怎么管理状态、工具调用和重试？
6. 延迟和成本约束是什么？
7. 你平时靠什么日志或 trace 调试？

### 前端项目

1. 核心页面和状态流是什么？
2. 为什么选这个框架和状态管理方式？
3. 做过哪些渲染或加载性能优化？
4. 怎么处理接口错误、鉴权状态和权限控制？
5. 做过哪些测试或组件复用？

## CS 基础主题图

优先根据简历和 JD 选题，其次才是通用高频主题。

| 领域 | 常见主题 |
| --- | --- |
| 操作系统 | 进程/线程、死锁、虚拟内存、上下文切换、IO 模型 |
| 网络 | TCP/UDP、HTTP/HTTPS、三次握手、四次挥手、拥塞控制、DNS |
| 数据库 | 索引、事务、MVCC、隔离级别、慢查询优化 |
| Redis | 数据结构、持久化、淘汰策略、缓存一致性、分布式锁 |
| Java | JVM、GC、集合、并发、线程池、锁 |
| C++ | 内存管理、RAII、智能指针、多态、STL、并发 |
| Python | GIL、装饰器、生成器、async IO、内存模型 |
| 后端工程 | REST、鉴权、限流、日志、监控、部署 |
| AI / ML | Transformer、RAG、Agent、评估、训练和推理链路 |
| 前端 | React/Vue、渲染、事件循环、浏览器缓存、性能 |
| 软件工程 | Git、测试、CI/CD、Code Review、可维护性 |

## 难度分层示例：数据库索引

| 层级 | 示例问题 |
| --- | --- |
| `basic` | 什么是索引，为什么能加速查询？ |
| `standard` | B+ 树和哈希索引有什么区别？ |
| `deep` | 为什么 InnoDB 选 B+ 树而不是红黑树？ |
| 工程化 | 线上慢查询你会怎么定位和修？ |
| 反思 | 索引越多越好吗，为什么不是？ |

## 算法互动流程

1. 给一道符合 `/level` 的题
2. 让候选人复述输入、输出和约束
3. 需要时先说暴力思路
4. 再推进到更优解
5. 追问时间复杂度和空间复杂度
6. 让候选人写代码或伪代码
7. 提供测试样例和边界情况
8. 如有必要，要求调试或修正
9. 最后记录表现并给出总结

## Hint 分级

| 等级 | 提示内容 |
| --- | --- |
| 1 | 只点出方向，例如哈希表、滑动窗口、二分、DFS、DP |
| 2 | 给出关键观察，但不说完整解法 |
| 3 | 描述核心思路 |
| 4 | 接近伪代码 |
| 5 | 给完整解法，并标记为高依赖提示 |

## V0.4 本地题库

如果要生成结构化题单，优先使用本地 V0.4 题库和选题器：

```bash
python cs-tech-interviewer/scripts/select_questions.py <candidate_profile.json> --jd-file <jd.txt> --focus "Redis, MySQL" --level 中等
```

选题器会读取：

- `data/fundamental_questions.json`
- `data/fundamental_knowledge_base.json`
- `data/algorithm_questions.json`
- 可选的 JD 文本和 `/focus`
- `candidate_profile.json`

它会输出 `question_selection.json` 和 `question_selection.md`。这份结果应该被当作起始计划，而不是不可变的死板剧本。

如果你要调整本地题库结构或选题字段，先阅读 [question-bank.md](./question-bank.md)。

## 方向提示图

- 后端：数据库、缓存、网络、操作系统、API 设计、鉴权、部署、日志、测试
- 前端：框架基础、浏览器、JS 事件循环、状态管理、性能、接口联调
- 算法：数据结构、复杂度、DP、图、证明和边界情况
- AI Agent / LLM App：RAG、工具调用、prompt / data flow、评估、成本、延迟、失败恢复
- 数据：SQL、数据建模、ETL、数据质量、调度、数仓基础
- 测试开发：测试设计、自动化、CI、mock、可靠性、缺陷定位
- SRE / DevOps：Linux、网络、容器、监控、故障处理、容量治理
- Graphics / CAD / Geometry：几何算法、数值鲁棒性、空间结构、渲染或 CAD pipeline
