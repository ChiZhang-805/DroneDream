# 07_EXECUTION_PLAN.md

## 1. 文档信息

- **Document Title**: DroneDream Execution Plan
- **Version**: v1.0
- **Product Stage**: MVP
- **Audience**: Devin、产品负责人、前端工程师、后端工程师、架构设计者
- **Purpose**: 定义 DroneDream MVP 的实现顺序、阶段目标、关键里程碑、推荐推进方式和风险控制策略，确保开发过程遵循“先打通产品闭环，再逐步替换真实组件”的路径，而不是一开始陷入过度工程化。

---

## 2. 执行总策略

## 2.1 核心执行原则

DroneDream MVP 的实现必须遵循以下原则：

### Principle A: 先闭环，后增强
先做出一个真实可运行的产品闭环，再逐步替换 mock 组件、增强内部实现和提升体验。

闭环最小定义为：

1. 用户创建 job
2. 系统异步执行
3. 用户看到 job 状态变化
4. 用户看到 baseline vs optimized 结果
5. 用户看到失败摘要
6. 用户可以 rerun

### Principle B: 先稳定契约，后接复杂执行层
前端页面、API 契约、数据模型和状态机必须先稳定，否则后续接 worker / simulator / optimizer 时会出现大量返工。

### Principle C: 先 mock simulator，后真实 simulator adapter
MVP 不应从第一天就强绑定真实 PX4/Gazebo 全链路。应先定义 `SimulatorAdapter` 边界，用 mock simulator 跑通系统，再预留真实实现。

### Principle D: 先异步 job/trial 框架，后优化算法细节
对 MVP 来说，真正重要的是：

- job 生命周期成立
- trial 可以异步执行
- worker 能回传结果
- UI 能展示进度和结果

而不是第一天就把优化算法做到最复杂。

### Principle E: 先可验收，再可炫技
MVP 阶段不优先追求：

- 复杂动画
- 复杂报表
- 复杂权限
- 复杂自定义编辑器
- 复杂部署

优先做“可验证完成”的系统。

---

## 2.2 推荐开发优先级

实现优先级必须严格遵循以下顺序：

### Priority 1: 产品主流程
必须最先打通：

- New Job
- Job Detail
- Dashboard / History
- rerun
- failed state

### Priority 2: 稳定前后端契约
必须固定：

- API shape
- status enums
- 数据实体边界
- UI 所需字段

### Priority 3: 异步执行框架
必须建立：

- job queue 语义
- trial dispatch 语义
- worker 执行边界
- result upload 语义

### Priority 4: mock simulator 闭环
必须让系统在不依赖真实 PX4/Gazebo 的情况下也能跑通：

- baseline
- candidate
- multi-trial
- aggregation
- report

### Priority 5: 结果与错误可视化
必须保证：

- baseline vs optimized 可见
- best params 可见
- 错误摘要可见
- 历史记录可见

---

## 2.3 早期阶段不应优先做的事

以下内容不应在 MVP 早期优先投入：

- 真实 PX4/Gazebo 完整接入
- ROS 2 复杂控制链路
- 高级赛道图形编辑器
- WebSocket 实时推送体系
- 多用户权限体系
- PDF/打印级正式报告导出
- 大规模并发调度
- 复杂自定义参数编辑器
- 过多底层控制参数暴露给终端用户

这些内容可以预留接口，但不应该阻塞 MVP 首次交付。

---

## 3. 交付模型

## 3.1 交付方式

推荐使用 **分阶段可运行交付** 模式，而不是长周期一次性交付。

每个阶段都必须具备：

- 明确目标
- 可见交付物
- 可验证退出条件
- 不破坏前一阶段成果

## 3.2 阶段划分

推荐分为以下 8 个阶段：

- Phase 0: Repo Bootstrap
- Phase 1: Frontend Skeleton + Mock Data
- Phase 2: Real Backend + Persistence
- Phase 3: Async Job / Queue / Worker Framework
- Phase 4: Simulator Adapter Layer
- Phase 5: Optimization Loop
- Phase 6: Results / Reporting / Visualization
- Phase 7: Hardening and Acceptance Pass

---

## 4. Phase 0: Repo Bootstrap

## 4.1 目标

建立项目的基础工程结构，为后续开发提供统一环境和组织方式。

## 4.2 必须交付

- 初始化代码仓库
- 明确 monorepo 或多 repo 结构
- 提供项目 README
- 提供环境变量模板
- 配置 lint / format / type-check
- 提供本地开发启动命令
- 提供基础 Docker 配置或等价开发环境方式

## 4.3 推荐目录结构

下面是推荐结构，Devin 可根据技术栈微调，但必须保证前后端边界清晰：

/drone-dream  
  /frontend  
  /backend  
  /worker  
  /docs  
  /scripts  
  .env.example  
  README.md  
  docker-compose.yml  

如果采用 monorepo，也应保证：

- `frontend/`
- `backend/`
- `worker/`
- `docs/`

至少是清晰独立的模块。

## 4.4 技术选型原则

技术栈可由 Devin 选择，但必须满足：

- 前端易于快速搭页面和状态流
- 后端易于定义 REST API
- 数据库支持结构化实体
- worker 机制支持异步任务
- 本地开发成本低

## 4.5 退出条件

以下条件同时满足，Phase 0 完成：

- 项目依赖可安装
- 前端空壳项目可启动
- 后端空壳项目可启动
- 代码规范工具可运行
- README 至少说明基本启动方式

---

## 5. Phase 1: Frontend Skeleton + Mock Data

## 5.1 目标

先用 mock data 搭出完整页面骨架和主要交互流程，让产品结构先成立。

## 5.2 本阶段关注什么

本阶段只关注：

- 页面是否完整
- 交互路径是否清楚
- UI 状态是否完整
- 组件是否可复用

不强制要求真实后端逻辑已接入。

## 5.3 必须交付的页面

- Dashboard
- New Job
- Job Detail
- Trial Detail
- History / Reports

## 5.4 必须交付的通用组件

- Status Badge
- Metric Card
- Section Card
- Data Table
- Alert / Error Notice
- Loading Skeleton 或等价状态组件

## 5.5 页面要求

### Dashboard
必须能展示：

- recent jobs table
- status summary cards
- new job 入口
- empty / loading / error 状态

### New Job
必须能展示：

- track config
- environment config
- objective profile
- 表单校验状态
- submit 按钮状态

### Job Detail
必须至少支持 mock 展示：

- queued / running / aggregating / completed / failed
- best params
- metrics cards
- comparison chart area
- trial summary table
- diagnostics panel

### Trial Detail
必须支持：

- 基本 trial 信息
- metrics 展示
- failed 场景展示

### History / Reports
必须支持：

- 历史列表
- 空状态
- 跳转详情

## 5.6 实现约束

- mock data 的字段名必须与 API 规范一致
- 状态名必须与文档一致
- 不允许前端自创 undocumented 字段
- 页面状态必须完整，不得只做 success 态

## 5.7 退出条件

以下条件同时满足，Phase 1 完成：

- 所有核心页面可访问
- 页面跳转流完整
- New Job 表单默认值正确
- Job Detail 至少能用 mock 数据演示 running / completed / failed
- UI 不依赖真实后端即可完整演示 MVP 主流程

---

## 6. Phase 2: Real Backend + Persistence

## 6.1 目标

将前端从 mock data 切换到真实后端与真实数据库持久化。

## 6.2 本阶段关注什么

本阶段重点是：

- API 契约落地
- 数据模型落地
- 前后端真实联调
- 基础 job 操作成立

## 6.3 必须交付的 API

至少完成以下公开接口：

- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/rerun`
- `POST /api/v1/jobs/{job_id}/cancel`
- `GET /api/v1/jobs/{job_id}/trials`
- `GET /api/v1/trials/{trial_id}`
- `GET /api/v1/jobs/{job_id}/report`
- `GET /api/v1/jobs/{job_id}/artifacts`

即使部分接口返回空数据或 not ready，也必须遵循正式 response shape。

## 6.4 必须落地的数据实体

至少落地：

- User（可简化）
- Job
- CandidateParameterSet
- Trial
- TrialMetric
- JobReport
- Artifact

`JobEvent` 推荐在本阶段一起落地，但不是绝对强制。

## 6.5 联调要求

- 前端改为调用真实 API
- Dashboard / History 读取真实 jobs 列表
- New Job 提交创建真实 job
- Job Detail 读取真实 job 详情
- 错误 response 能被前端正确展示

## 6.6 本阶段允许的简化

- trial 列表可以先为空
- report 可以先返回 `REPORT_NOT_READY`
- candidate 聚合逻辑可以先不完整
- worker 还未真正执行也可以，但 job 创建和读取必须是真实数据流

## 6.7 退出条件

以下条件同时满足，Phase 2 完成：

- 前端不再依赖 mock API
- job 可真实创建
- job 可真实读取
- rerun / cancel 基础语义成立
- 数据库中有真实 job 数据
- API 错误结构统一稳定

---

## 7. Phase 3: Async Job / Queue / Worker Framework

## 7.1 目标

建立真正的异步任务执行框架，让 job 和 trial 从“静态记录”变成“可推进的执行流”。

## 7.2 本阶段关注什么

重点不是先接真实 simulator，而是先让以下结构成立：

- job 可以被异步推进
- candidate 可以被生成
- trial 可以被拆分和调度
- worker 可以执行单个 trial
- worker 可以回传结果
- job 可以基于 trial 结果推进状态

## 7.3 必须交付的能力

### A. Job Asynchronous Execution
- job 创建后不阻塞 API 请求
- job 进入 `QUEUED`
- 后台执行器将 job 推进到 `RUNNING`

### B. Baseline Candidate Creation
- 每个 job 自动生成 baseline candidate
- baseline candidate 写入数据库
- baseline candidate 关联到 job

### C. Trial Generation
- 系统可根据 candidate 生成 trials
- 每个 trial 具有独立记录
- 每个 trial 具有 seed 和 scenario_type

### D. Worker Execution
- worker 能获取待执行 trial
- worker 能更新 trial 为 `RUNNING`
- worker 能生成 trial result
- worker 能上传 metrics 和状态

### E. Job Progress Update
- job 能基于 trial 完成数更新进度
- job 能进入 `AGGREGATING`
- job 能进入 `COMPLETED` 或 `FAILED`

## 7.4 推荐实现方式

Devin 可自由选择具体实现，例如：

- background worker process
- task queue
- queue + scheduler
- database-backed polling worker

但必须满足以下硬约束：

1. API 请求线程不能长时间阻塞等待仿真结束  
2. trial 必须由独立执行单元处理  
3. job 状态必须来源于真实后台推进，而不是纯前端假刷新  

## 7.5 最小可运行闭环

本阶段最小闭环建议为：

1. 用户创建 job
2. 系统写入 job 记录
3. 系统自动生成 baseline candidate
4. 系统自动生成若干 baseline trials
5. worker 消费这些 trials
6. worker 产生 mock metrics
7. 系统聚合 baseline 结果
8. 系统可先直接生成一个 mock optimized candidate 或进入下一阶段再做
9. job 最终进入 `COMPLETED`

## 7.6 本阶段允许的简化

- 先只跑 baseline，不跑多轮 optimizer candidate
- 先固定 trial 数量，例如每个 candidate 3 个或 4 个 trial
- 先使用 mock metrics
- 先不做复杂重试策略
- 先不做高级 worker 调度公平性

## 7.7 退出条件

以下条件同时满足，Phase 3 完成：

- job 创建后能自动进入异步执行
- 至少 baseline candidate 会被自动创建
- trials 会被自动生成
- worker 能执行 trial 并写回结果
- Job Detail 页面能看到状态真实变化
- job 最终能进入 `COMPLETED` 或 `FAILED`

---

## 8. Phase 4: Simulator Adapter Layer

## 8.1 目标

引入 simulator adapter 抽象层，使系统既能使用 mock simulator，也能为未来接真实 PX4/Gazebo 留出明确边界。

## 8.2 为什么必须单独做这一层

如果 worker 直接把“仿真逻辑”写死在内部，会带来以下问题：

- mock simulator 与真实 simulator 无法平滑切换
- 后续接入 PX4/Gazebo 需要大改 worker
- 难以测试
- 难以复用 trial execution 逻辑
- 难以让优化器保持与仿真实现解耦

## 8.3 必须定义的抽象接口

至少需要一个明确的 `SimulatorAdapter` 或等价抽象，其语义应覆盖：

- 准备一个 trial 执行环境
- 接收 job config
- 接收 candidate parameter set
- 接收 scenario / seed
- 执行 trial
- 返回 trial metrics
- 返回 optional artifacts
- 返回 failure information

## 8.4 推荐接口能力

Devin 可以自定义具体函数名，但建议至少包含下列能力：

- `prepare_trial_context(...)`
- `run_trial(...)`
- `collect_metrics(...)`
- `collect_artifacts(...)`
- `cleanup(...)`

## 8.5 必须交付的实现

### A. MockSimulatorAdapter
这是 MVP 的主路径，必须完整可运行。

其职责包括：

- 根据输入生成稳定的 mock trial 结果
- 支持成功与失败两种路径
- 返回结构符合 TrialMetric 和 Artifact 契约
- 不破坏状态机和异步执行逻辑

### B. RealSimulatorAdapterStub
即使暂不接真实 PX4/Gazebo，也必须预留 stub 或接口骨架，确保后续接入时不推翻系统结构。

## 8.6 Mock Simulator 的最低要求

mock simulator 至少要支持：

- baseline trial
- optimized candidate trial
- nominal scenario
- perturbed scenario
- deterministic or semi-deterministic result generation
- failure injection（例如 timeout / simulation failure）

## 8.7 退出条件

以下条件同时满足，Phase 4 完成：

- worker 通过 simulator adapter 执行 trial
- mock adapter 可独立产出 trial metrics
- mock adapter 可产出 failure case
- real adapter 至少有清晰 stub / interface
- worker 代码中不再写死仿真逻辑

---

## 9. Phase 5: Optimization Loop

## 9.1 目标

让系统从“只会跑 trial 的异步框架”升级为“真正具备 baseline、candidate generation、aggregation 和 best selection 的优化系统”。

## 9.2 本阶段关注什么

重点不是一开始就实现复杂优化算法，而是先建立完整优化结构：

- baseline candidate
- optimizer candidate(s)
- multi-trial evaluation
- aggregation
- best candidate selection

## 9.3 必须交付的能力

### A. Baseline Evaluation
- 每个 job 自动产生 baseline candidate
- baseline candidate 有独立 score / metrics

### B. Candidate Generation
- 系统至少能生成一批 optimizer candidates
- candidates 具有 `generation_index`
- candidates 具有独立 `parameter_json`

### C. Multi-Trial Evaluation
- 每个 candidate 对应多个 trials
- trials 在不同 seed / scenario 下运行
- 结果分别保存

### D. Aggregation
- 系统将多个 trial 结果聚合为 candidate score
- 保存 `aggregated_score`
- 保存 `aggregated_metric_json`

### E. Best Candidate Selection
- 系统明确选出 best candidate
- 将其写入 job / report
- UI 可以读取 best params

## 9.4 推荐最小优化器实现

MVP 第一版优化器可采用简单方式，例如：

- baseline 周围固定扰动采样
- 规则化生成有限数量候选参数
- 简单排序选优
- 轻量 heuristic optimizer

重点在于让“优化闭环”成立，而不是一开始追求算法最优。

## 9.5 本阶段不要求

- 复杂 Bayesian Optimization
- CMA-ES
- 高维黑盒搜索
- LLM 主导参数更新
- 分段时变参数优化
- 自适应 schedule

## 9.6 Candidate 数量建议

MVP 初版建议：

- baseline 1 组
- optimizer candidates 2–5 组
- 每组 candidate 运行 3–5 个 trials

这样可以先建立闭环，而不会让系统复杂度过高。

## 9.7 退出条件

以下条件同时满足，Phase 5 完成：

- 每个 job 至少包含 baseline 和一批 optimizer candidates
- 每个 candidate 至少有多个 trials
- 系统能计算 aggregated score
- 系统能明确 best candidate
- job / report 中存在 best params
- Job Detail 页面能看到 baseline vs optimized 结果来源于真实数据

---

## 10. Phase 6: Results / Reporting / Visualization

## 10.1 目标

把系统已有的真实执行结果转化为用户能理解、能比较、能操作的结果页面与报告。

## 10.2 本阶段关注什么

重点是结果产品化，而不是单纯“把 JSON 打出来”。

用户必须能快速读懂：

- 当前 job 状态
- baseline 表现
- optimized 表现
- 最优参数
- trial 摘要
- 失败信息

## 10.3 必须交付的结果展示能力

### A. Job Detail Result Sections
必须完整展示：

- Job Summary Card
- Status Badge
- Progress / Phase 信息
- Metrics Cards
- Baseline vs Optimized Comparison
- Best Parameter Card
- Trial Summary Table
- Diagnostics / Logs Summary

### B. Trial Detail Result Sections
必须展示：

- trial metadata
- metrics
- failure reason（若失败）
- optional artifact links

### C. History / Reports
必须展示：

- 历史 jobs 列表
- 已完成/失败任务可回看
- 可进入 Job Detail

## 10.4 Report 内容最低要求

每份 report 至少应包含：

- `job_id`
- `best_candidate_id`
- `summary_text`
- `baseline_metrics`
- `optimized_metrics`
- `best_parameter_json`

## 10.5 Summary Text 实现要求

- 可以先使用模板化文案生成
- 不强制第一版接 LLM
- 文案必须基于真实数据
- 文案不得与真实 metrics 矛盾

例如可以先用模板：

- `Optimized parameters improved RMSE from X to Y.`
- `The best candidate performed better under the selected noise and wind profile.`

## 10.6 图表最低要求

MVP 至少应实现以下之一：

- baseline vs optimized trajectory plot
- baseline vs optimized metric comparison chart

只要能清楚表达优化前后差异即可。

## 10.7 退出条件

以下条件同时满足，Phase 6 完成：

- completed job 结果页完整
- failed job 详情页完整
- baseline vs optimized 差异清晰
- report 接口可真实驱动页面
- 历史页可回看旧结果
- trial detail 可用于查看单次结果

---

## 11. Phase 7: Hardening and Acceptance Pass

## 11.1 目标

对 MVP 做最后一轮系统收口，确保它不是“基本能演示”，而是“可以依据验收标准判断完成”。

## 11.2 本阶段关注什么

- 边界场景
- 错误处理
- 状态机一致性
- 文档与实现一致性
- 字段名和枚举一致性
- acceptance criteria 逐项检查

## 11.3 必须完成的清理项

### A. 错误处理清理
至少补齐以下场景：

- invalid input
- job not found
- trial not found
- report not ready
- worker timeout
- simulation failed
- rerun conflict
- cancel conflict
- page load failure

### B. 状态机检查
必须确认：

- Job 状态转换合法
- Trial 状态转换合法
- terminal states 不会回流
- rerun 创建新 job，不重置旧 job

### C. 字段和术语一致性检查
必须确认：

- `sensor_noise_level` 全栈一致
- `objective_profile` 全栈一致
- `best_candidate_id` 全栈一致
- 页面术语一致使用 Job / Trial / Candidate / Baseline / Optimized

### D. UI State Completeness
必须确认页面具备：

- loading
- empty
- success
- error
- failed / cancelled（在适用页面）

### E. Acceptance Checklist Pass
必须以 `06_ACCEPTANCE_CRITERIA.md` 为准逐项核对。

## 11.4 测试重点建议

MVP 不要求复杂自动化测试体系，但至少应对以下内容进行重点验证：

- Create Job flow
- Job status polling
- Completed result rendering
- Failed result rendering
- Rerun flow
- History flow
- Invalid input handling
- Job/trial not found handling

## 11.5 退出条件

以下条件同时满足，Phase 7 完成：

- 关键错误场景可处理
- 状态机与文档一致
- 页面字段与 API 一致
- acceptance criteria 主要条目通过
- MVP 可以稳定演示并可被验收

---

## 12. Milestones

## 12.1 M1: Project Skeleton Ready
表示项目工程底座完成。

**必须具备**：
- repo 结构
- 可启动前后端空壳
- 统一开发入口

## 12.2 M2: UI Skeleton Ready
表示前端页面骨架完成。

**必须具备**：
- 核心页面齐全
- 页面之间能跳转
- mock data 能驱动主流程

## 12.3 M3: Backend Contract Ready
表示真实 API 与数据库基础完成。

**必须具备**：
- 真实创建 job
- 真实读取 job
- 数据真实持久化

## 12.4 M4: Async Execution Ready
表示 job / trial 的异步结构成立。

**必须具备**：
- worker 能消费 trial
- 状态能真实推进
- trial metrics 能写回

## 12.5 M5: Optimization Loop Ready
表示 baseline + candidate + aggregation 成立。

**必须具备**：
- baseline candidate
- optimizer candidate
- multi-trial aggregation
- best candidate

## 12.6 M6: Reporting Ready
表示结果展示完整可读。

**必须具备**：
- best params
- baseline vs optimized
- summary text
- history page

## 12.7 M7: MVP Acceptance Ready
表示进入最终交付状态。

**必须具备**：
- 通过主要 acceptance criteria
- 常见失败场景可处理
- 文档与实现基本一致

---

## 13. 建议任务顺序（给 Devin 的明确执行顺序）

为了减少返工，建议 Devin 严格按以下顺序执行：

### Step 1
先搭前端页面和共用组件，不接真实后端。

### Step 2
用 mock data 跑通 New Job → Job Detail → History 主流程。

### Step 3
实现真实 API 和数据库，让 job 能真实创建和读取。

### Step 4
把前端从 mock data 切换到真实 API。

### Step 5
引入异步 job / trial 执行框架和 worker。

### Step 6
接入 mock simulator adapter，让 worker 能产出真实格式 trial result。

### Step 7
实现 baseline + candidate generation + aggregation + best selection。

### Step 8
补齐 report、trial detail、rerun、cancel、history。

### Step 9
完成错误清理、状态机检查和 acceptance pass。

如果顺序打乱，最容易出现的问题是：

- 前端字段与后端反复漂移
- worker 过早复杂化
- simulator 集成阻塞整体进度
- 结果页没有真实数据支撑

---

## 14. 风险与缓解策略

## 14.1 风险：过早接真实 PX4/Gazebo

**后果**：
- 开发速度大幅变慢
- UI / API 契约长期不稳定
- worker 调试复杂度陡增

**缓解**：
- 先实现 mock simulator adapter
- 真实 simulator 只作为 Phase 4 后续扩展项

## 14.2 风险：字段名漂移

**后果**：
- 前后端联调大量返工
- 页面渲染异常
- 文档失效

**缓解**：
- 严格以 `05-api-reference.md` 为准
- 一旦 Phase 2 完成，不随意改字段名

## 14.3 风险：数据模型过度简化

**后果**：
- candidate / trial 无法分层
- rerun 不好实现
- report 难以生成

**缓解**：
- 严格按 `06-data-model.md` 建模
- 不把所有内容塞进单个 job JSON

## 14.4 风险：worker 与 API 耦合过紧

**后果**：
- API 请求阻塞
- 状态推进混乱
- 后续难扩展

**缓解**：
- trial 必须异步执行
- worker 必须独立于 API 请求路径

## 14.5 风险：只做 happy path

**后果**：
- 演示时遇到失败场景就崩
- 无法通过验收

**缓解**：
- Phase 7 专门做错误与边界场景收口
- 用 `06_ACCEPTANCE_CRITERIA.md` 做逐项检查

---

## 15. 建议检查点

为了在中途及时纠偏，建议 Devin 在以下节点做检查。

## Checkpoint A: After Phase 1
检查：

- 页面是否齐全
- 页面状态是否完整
- 术语是否统一
- mock shape 是否符合 API 规范

## Checkpoint B: After Phase 2
检查：

- API 是否稳定
- 前后端字段是否一致
- job 数据是否真实持久化

## Checkpoint C: After Phase 3
检查：

- job 是否真实异步执行
- trial 是否由 worker 执行
- 状态是否真实推进

## Checkpoint D: After Phase 5
检查：

- baseline 是否真实存在
- candidate / trial 分层是否成立
- aggregation 是否不是伪造结果

## Checkpoint E: Before Final Delivery
检查：

- acceptance criteria 是否通过
- 是否还有 undocumented 字段
- 是否还有只在 success path 下成立的功能

---

## 16. 最终交付物清单

MVP 最终至少应交付以下内容。

## 16.1 产品交付物
- 可运行的 Web 前端
- 可运行的后端 API
- 可运行的 worker
- mock simulator 模式下的完整闭环

## 16.2 文档交付物
- `01_PRD.md`
- `03_UI_SPEC.md`
- `05-api-reference.md`
- `06-data-model.md`
- `06_ACCEPTANCE_CRITERIA.md`
- `07_EXECUTION_PLAN.md`

## 16.3 技术交付物
- 数据库 schema
- API implementation
- worker implementation
- simulator adapter abstraction
- mock simulator implementation
- report generation path

## 16.4 验证交付物
- 一组 successful end-to-end demo
- 一组 failed-flow demo
- acceptance checklist 自检结果

---

## 17. 执行成功的定义

当以下条件全部满足时，可以认为 `07_EXECUTION_PLAN.md` 所描述的执行路径是成功的：

1. Devin 没有被真实仿真接入过早阻塞
2. MVP 能在 mock simulator 模式下完整跑通
3. 前端、API、数据模型和状态机彼此一致
4. job / candidate / trial / report 分层成立
5. 用户可以完成主流程
6. 常见失败场景可处理
7. 结果展示来自真实持久化数据
8. 后续接真实 PX4/Gazebo 不需要推翻整个系统架构

---

## 18. 给 Devin 的最终执行约束

为了保证 MVP 不偏离目标，Devin 在实现时必须遵守：

- 不要跳过 mock simulator 阶段
- 不要把 job 做成同步阻塞式接口
- 不要省略 baseline
- 不要把 candidate 和 trial 混为一层
- 不要只做 success path
- 不要为了赶工改变 API 契约却不更新文档
- 不要优先做复杂功能而忽略主流程稳定性

必须始终优先保证：

- 主流程成立
- 状态流真实
- 数据持久化真实
- 失败可处理
- 结果可展示
- 文档与实现一致

---

## 19. Summary

`07_EXECUTION_PLAN.md` 的核心作用，不是描述“理论上系统可以如何构建”，而是明确：

- 应该先做什么
- 应该后做什么
- 哪些内容现在不做
- 每个阶段做到什么算完成
- 如何减少返工
- 如何确保 Devin 最终交付的是一个可运行、可验收、可扩展的 MVP

对 DroneDream 来说，最合理的执行路径是：

**页面骨架 → 真实 API 和数据库 → 异步 job/trial 框架 → simulator adapter → optimization loop → reporting → acceptance pass**

这条路径既能保证 MVP 尽快落地，也能为未来接入真实 PX4/Gazebo 保留清晰的扩展边界。
