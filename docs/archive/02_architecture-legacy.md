# 02_02-architecture.md

## 1. 文档信息

- **Document Title**: DroneDream Architecture Specification
- **Version**: v1.0
- **Product Stage**: MVP
- **Audience**: Devin、后端工程师、架构设计者、前端联调人员
- **Purpose**: 定义 DroneDream MVP 的系统分层、模块职责、服务边界、执行闭环、优化闭环、数据流和部署边界，确保实现结果符合产品需求，并为未来接入真实 PX4/Gazebo 仿真保留扩展路径。

---

## 2. Architecture Goals

本架构文档服务于以下目标：

### 2.1 Product Alignment
系统架构必须服务于产品主流程，而不是围绕底层仿真技术自我展开。产品主流程是：

1. 用户创建 job
2. 系统异步执行 baseline 和 candidate trials
3. 系统聚合结果
4. 用户查看状态、结果、失败信息
5. 用户可以 rerun 和查看历史

### 2.2 Separation of Concerns
必须明确分离以下职责：

- 前端交互与展示
- API 接口层
- 任务编排层
- 优化逻辑层
- 仿真执行层
- 数据与观测层
- LLM 解释层

### 2.3 Async-First Execution
仿真与优化必须通过异步 job / trial 执行，不允许在 API 请求内同步跑完整任务。

### 2.4 Mock-First, Real-Simulator-Ready
MVP 必须先能在 mock simulator 模式下完整运行，同时架构上必须预留真实 simulator adapter 的接入边界。

### 2.5 Extensible but Not Overengineered
架构必须支持未来扩展，但不能为尚未进入 MVP 范围的功能进行过度复杂化设计。

---

## 3. Architecture Principles

### 3.1 Task-Centered System Design
系统围绕 `Job` 组织，而不是围绕某个单独控制器、某类日志或某套飞控参数组织。

### 3.2 Deterministic System Core
系统的核心执行链应尽量可重复、可调试、可追踪。优化器、worker、状态机和数据落库必须优先于“智能化叙述”。

### 3.3 LLM as Strategy and Explanation Layer
LLM 只能扮演以下角色：

- 翻译用户目标
- 解释结果
- 总结失败模式
- 生成自然语言摘要

LLM 不得直接：

- 写底层 PX4 参数
- 发送飞行控制命令
- 决定绕过优化器的最终参数
- 修改核心安全边界

### 3.4 Stable Contracts Over Implementation Flexibility
前后端契约、状态枚举、数据模型边界必须比具体实现手段更稳定。

### 3.5 Product Behavior Over Internal Cleverness
允许内部实现简单，但不允许用户看到混乱行为，例如：

- 状态不更新
- 失败无反馈
- 数据不一致
- 页面字段缺失
- rerun 覆盖原任务

---

## 4. System Scope for MVP

## 4.1 Included in MVP

MVP 架构必须覆盖：

- Web 前端页面与交互
- REST API
- 数据库存储
- 异步 job / trial 执行框架
- worker 执行链路
- mock simulator adapter
- baseline + candidate + aggregation 基本优化闭环
- 最终结果页与历史页

## 4.2 Excluded from MVP

以下内容不作为 MVP 架构强制要求：

- 真实 PX4/Gazebo 完整集成
- ROS 2 复杂链路
- 多机仿真
- 多用户实时协作
- 在线学习控制器
- 复杂权限系统
- 生产级大规模调度
- 高级实时流式推送

---

## 5. High-Level Architecture

系统采用前后端分离、异步执行、分层解耦的总体结构。

### 5.1 Logical Architecture Layers

#### A. Presentation Layer
负责用户界面、交互、状态展示、结果可视化。

#### B. API Layer
负责输入校验、资源读写、状态查询和统一错误返回。

#### C. Orchestration Layer
负责 job 生命周期、candidate/trial 编排、状态推进和调度协调。

#### D. Optimization Layer
负责 candidate generation、aggregation、best selection。

#### E. Execution Layer
负责单个 trial 的实际执行，包括 simulator adapter 调用、结果收集和错误处理。

#### F. Data and Observability Layer
负责数据库、artifact 元数据、状态事件、日志和可追踪信息。

#### G. LLM Strategy Layer
负责结果解释、目标翻译和自然语言总结。

---

## 6. High-Level Components

## 6.1 Web Frontend

### Responsibilities
- 展示 Dashboard、New Job、Job Detail、Trial Detail、History
- 提交 job 创建请求
- 轮询 job / trial 状态
- 展示 baseline vs optimized 结果
- 展示错误摘要和历史记录

### Non-Responsibilities
- 不负责优化算法
- 不负责仿真执行
- 不负责参数搜索
- 不负责直接与 simulator 通信

---

## 6.2 API Server

### Responsibilities
- 暴露 REST API
- 校验输入
- 读取和写入核心实体
- 返回统一 envelope 响应
- 处理 rerun / cancel 等资源操作

### Non-Responsibilities
- 不负责长时 trial 执行
- 不负责仿真本体
- 不负责数值优化实现

---

## 6.3 Job Manager

### Responsibilities
- 创建 job 初始执行计划
- 推进 job 状态机
- 创建 baseline candidate
- 触发 candidate generation
- 驱动 aggregation 和 report generation

### Non-Responsibilities
- 不直接执行 trial
- 不直接承担优化器算法本体
- 不直接生成 UI 文案

---

## 6.4 Optimizer Service

### Responsibilities
- 根据已有结果生成下一批 candidate
- 管理搜索空间
- 提供 aggregated score 排序所需逻辑
- 选出 best candidate

### Non-Responsibilities
- 不直接执行 worker
- 不直接渲染页面
- 不直接控制飞行器

### MVP Note
MVP 中该服务可以先很轻量，例如规则化候选生成或简单启发式采样，但必须保留独立服务或独立模块边界。

---

## 6.5 Trial Dispatcher

### Responsibilities
- 将 candidate 拆分成多个 trial
- 生成不同 seed / scenario_type 的执行单元
- 投递给 worker
- 管理 trial 排队与分发

### Non-Responsibilities
- 不负责页面
- 不负责汇总 report
- 不负责 candidate 排序

---

## 6.6 Simulation Worker

### Responsibilities
- 读取 trial payload
- 初始化 simulator adapter
- 执行单个 trial
- 收集 metrics
- 生成 artifact 元数据
- 回传结果
- 更新 trial 状态

### Non-Responsibilities
- 不负责全局 job 决策
- 不负责优化器候选生成
- 不负责产品级汇总展示

---

## 6.7 Simulator Adapter

### Responsibilities
- 封装 simulator 执行接口
- 接收 job config、candidate params、seed、scenario
- 执行 trial
- 返回 trial metrics、artifacts 和错误信息

### MVP Implementations
- `MockSimulatorAdapter`
- `RealSimulatorAdapterStub`

### Future Implementations
- `PX4GazeboAdapter`
- 其他 simulator backends

---

## 6.8 Report Generator

### Responsibilities
- 从 job、candidate、trial、metrics 中生成最终 report
- 生成 baseline vs optimized 摘要
- 提供 summary text
- 为前端结果页提供稳定数据结构

### Non-Responsibilities
- 不负责 trial 执行
- 不负责 UI 排版
- 不负责候选生成

---

## 6.9 LLM Strategy Service

### Responsibilities
- 将 objective_profile 或用户自然语言目标翻译为可读解释
- 解释 best candidate 的效果
- 解释失败模式
- 生成自然语言 summary

### Constraints
- 仅读取结构化摘要输入
- 不直接访问底层执行控制
- 不绕过 optimizer 或 simulator adapter

---

## 6.10 Persistence Layer

Persistence Layer 至少包括：

- relational database
- artifact metadata storage
- optional object storage
- queue / task state persistence
- job event storage

---

## 7. Component Responsibility Matrix

## 7.1 Frontend
负责：
- 页面
- 表单
- 状态轮询
- 图表展示
- 错误提示

不负责：
- worker 执行
- optimizer
- simulator

## 7.2 API Server
负责：
- 资源接口
- 统一错误格式
- 输入验证
- 基础资源操作

不负责：
- 长时任务执行
- candidate 搜索
- 生成 metrics

## 7.3 Job Manager
负责：
- 状态推进
- 编排流程
- 触发 baseline / candidate / aggregation

不负责：
- 单个 trial 的执行

## 7.4 Worker
负责：
- trial 级别执行

不负责：
- job 级别决策

## 7.5 Optimizer
负责：
- candidate 生成
- best candidate 选择

不负责：
- 页面和 API

## 7.6 LLM
负责：
- 解释
- 总结
- 文案生成

不负责：
- 直接控制或调参写入

---

## 8. Core Domain Objects

系统的核心领域对象必须明确分层：

### 8.1 Job
一次完整优化任务。

### 8.2 CandidateParameterSet
一组候选参数。

### 8.3 Trial
某个 candidate 在某个 scenario / seed 下的一次具体执行。

### 8.4 TrialMetric
某个 trial 的数值结果。

### 8.5 JobReport
某个 job 的最终聚合结果。

### 8.6 Artifact
图表、日志、telemetry 等产物元数据。

### 8.7 JobEvent
生命周期事件记录。

---

## 9. Primary Execution Flows

## 9.1 Flow A: Create Job

1. 用户在前端填写 New Job 表单
2. Frontend 调用 `POST /api/v1/jobs`
3. API Server 校验输入
4. API Server 创建 `Job`
5. Job 初始状态设为 `QUEUED`
6. Job Manager 接收 job 创建事件
7. 前端跳转到 Job Detail 页面

---

## 9.2 Flow B: Start Baseline Execution

1. Job Manager 检测到新 job
2. 创建 baseline candidate
3. Trial Dispatcher 生成 baseline trials
4. Trials 进入待执行队列
5. Worker 消费这些 trials
6. Worker 通过 SimulatorAdapter 执行
7. Trial 和 TrialMetric 被写入
8. Job progress 更新

---

## 9.3 Flow C: Candidate Evaluation

1. Job Manager 触发 Optimizer Service
2. Optimizer 生成一批 candidates
3. Dispatcher 为每个 candidate 生成 trials
4. Worker 并行执行
5. TrialMetric 回传并落库
6. Aggregation 逻辑计算 aggregated score
7. 记录 candidate 聚合结果

---

## 9.4 Flow D: Best Candidate Selection and Report

1. 所有 required trials 完成
2. Job 进入 `AGGREGATING`
3. Optimizer / Aggregator 计算 best candidate
4. Job 写入 `best_candidate_id`
5. Report Generator 生成 JobReport
6. Job 进入 `COMPLETED`
7. Frontend 在 Job Detail 展示结果

---

## 9.5 Flow E: Failure Handling

1. 某个 trial 失败或 timeout
2. Worker 写入失败状态和 failure reason
3. Job Manager 判断：
   - 是否允许继续
   - 是否标记 job failed
   - 是否进入 partial failure 展示路径
4. Frontend 可读取错误摘要
5. 用户可 rerun

---

## 10. Job Lifecycle Architecture

## 10.1 Job States
- CREATED
- QUEUED
- RUNNING
- AGGREGATING
- COMPLETED
- FAILED
- CANCELLED

## 10.2 Job State Ownership
- API 创建时：`CREATED / QUEUED`
- Job Manager：推进到 `RUNNING / AGGREGATING`
- Aggregation / Report 完成后：推进到 `COMPLETED`
- 错误路径：推进到 `FAILED`
- 用户取消：推进到 `CANCELLED`

## 10.3 Architectural Constraint
Job 的状态推进必须由后端真实流程驱动，不能由前端“猜测状态”或纯 UI 本地模拟。

---

## 11. Trial Lifecycle Architecture

## 11.1 Trial States
- PENDING
- RUNNING
- COMPLETED
- FAILED
- CANCELLED

## 11.2 Trial State Ownership
- Dispatcher 创建 trial 时：`PENDING`
- Worker 开始执行时：`RUNNING`
- Worker 成功写回时：`COMPLETED`
- Worker 失败或 timeout：`FAILED`
- 上层取消时：`CANCELLED`

## 11.3 Architectural Constraint
一个 Trial 必须可以独立追踪、独立诊断、独立展示。

---

## 12. Optimization Architecture

## 12.1 Optimization Responsibilities
优化层至少要完成：

- baseline evaluation
- candidate generation
- multi-trial aggregation
- best candidate selection

## 12.2 MVP Optimization Strategy
MVP 第一版不要求复杂算法，允许：

- 固定扰动采样
- 简单启发式生成
- 轻量排序选优

但必须具备正式的模块边界。

## 12.3 Aggregation Requirements
聚合至少应基于：

- 多个 trial 的 score
- 多个 trial 的核心 metrics
- 失败率或 timeout 情况
- 一致的 best selection 规则

---

## 13. Simulator Integration Architecture

## 13.1 Why Adapter Architecture Is Required
通过 adapter 解耦的原因：

- mock 与 real backend 切换容易
- worker 不被特定 simulator 锁死
- 便于测试
- 便于后续替换真实 PX4/Gazebo

## 13.2 Mock Simulator Path
MVP 主路径必须依赖 MockSimulatorAdapter，以支撑完整可演示闭环。

## 13.3 Real Simulator Path
真实 PX4/Gazebo 接入不属于 MVP 必须项，但架构必须允许其作为新的 adapter 实现接入，而无需重写 API、DB 和 Frontend。

---

## 14. Data Flow Architecture

## 14.1 Inbound Flow
Frontend -> API Server -> Job record creation

## 14.2 Orchestration Flow
Job Manager -> Optimizer / Dispatcher -> Worker

## 14.3 Execution Flow
Worker -> SimulatorAdapter -> Trial result

## 14.4 Persistence Flow
Worker / Job Manager / Report Generator -> Database + Artifact metadata

## 14.5 Outbound Flow
API Server -> Frontend pages

---

## 15. Observability Architecture

## 15.1 Required Observability Entities
系统至少需要可追踪以下层级：

- Job
- Candidate
- Trial
- TrialMetric
- JobEvent
- Artifact metadata

## 15.2 Required Visibility
必须能够回答以下问题：

- 某个 job 当前在哪个阶段
- 某个 candidate 的 aggregated score 是多少
- 某个 trial 是否失败
- 失败原因是什么
- 哪个 candidate 被选为 best
- report 是否已生成

## 15.3 Logging Strategy
MVP 不要求复杂日志平台，但至少要求：

- job 级状态日志
- trial 级失败摘要
- worker 执行错误可追踪
- artifact 元数据可查询

---

## 16. Security and Safety Boundaries

## 16.1 Input Safety
所有 job 输入必须经前后端双重校验。

## 16.2 Parameter Safety
参数搜索必须通过白名单，不允许任意底层参数进入搜索空间。

## 16.3 LLM Safety
LLM 不能直接控制执行层，也不能拥有写底层参数的权限。

## 16.4 Execution Safety
worker 与 API 必须逻辑解耦，避免因为 trial 执行导致 API 卡死。

---

## 17. Failure Handling Architecture

## 17.1 Types of Failures
必须考虑：

- invalid input
- resource not found
- trial failure
- worker timeout
- simulator failure
- report not ready
- rerun / cancel conflict

## 17.2 Failure Ownership
- 输入错误：API Server
- trial 执行错误：Worker
- job 级失败判定：Job Manager
- 文案解释：Report / LLM layer
- UI 呈现：Frontend

## 17.3 Architectural Requirement
失败必须以结构化方式持久化，不允许只存在于临时日志中。

---

## 18. Deployment Architecture

## 18.1 Local Development Mode
- Frontend
- API Server
- Database
- Queue 或等价异步机制
- Worker
- Mock Simulator Adapter

## 18.2 Single-Node MVP Deployment
可在一台机器上部署：
- Frontend
- API Server
- DB
- Worker
- Queue
- Artifact storage

## 18.3 Scaled Future Deployment
未来可扩展为：
- API 多实例
- Worker pool
- 独立 object storage
- 更强的 task queue system

MVP 不强制实现，但架构上不能阻断。

---

## 19. Architectural Constraints for Devin

实现时必须遵守以下硬约束：

### 19.1 Do Not Collapse Layers
不要把 API、Job Manager、Worker、Optimizer、Simulator 写成一个巨型模块。

### 19.2 Do Not Skip Async Execution
不要把完整仿真优化做成同步 API。

### 19.3 Do Not Make LLM Part of the Execution Core
LLM 不能位于 trial 执行主链路的关键节点。

### 19.4 Do Not Bind the System Directly to One Simulator
必须通过 adapter 做抽象。

### 19.5 Do Not Merge Candidate and Trial
Candidate 是参数层，Trial 是执行层，不能混。

### 19.6 Do Not Optimize UX Before Core State Flow Exists
优先真实状态流，而不是先做复杂页面效果。

---

## 20. Recommended MVP Technical Shape

虽然具体技术栈可由 Devin 自主选择，但架构形态应至少满足以下模式：

- 一个 Web frontend
- 一个 REST API backend
- 一个 relational database
- 一个 async worker system
- 一个 simulator adapter layer
- 一个 optimizer module
- 一个 report generation module

---

## 21. Future Extension Points

当前架构应允许后续平滑扩展以下能力：

- 真实 PX4/Gazebo Adapter
- 更多赛道类型
- 更多 scenario types
- 更复杂优化算法
- 分段参数调度
- LLM 更丰富的解释能力
- 多机型支持
- 报告导出
- 多用户系统

---

## 22. Summary

`02_02-architecture.md` 的核心作用，是确保 DroneDream 不会被实现成：

- 一个只有页面的 demo
- 一个和 simulator 强绑定的脚本集合
- 一个没有异步任务语义的同步后端
- 一个让 LLM 直接参与执行控制的高风险系统

对 Devin 来说，这份架构文档要求构建的是：

- **任务中心化**
- **异步执行**
- **分层解耦**
- **mock-first**
- **结果导向**
- **可扩展但不过度复杂**

MVP 的正确架构路径应是：

**Frontend + API + DB + Job Manager + Worker + Simulator Adapter + Optimizer + Report Generator + Optional LLM Strategy Layer**

这套结构必须能够支撑：
- 创建 job
- 执行 baseline 和 candidates
- 聚合结果
- 展示结果
- 处理失败
- 保留历史

---

## Phase 8 addendum — real simulator adapter + iterative GPT tuning

Phase 8 extends this architecture without changing the existing layering.
All Phase 7 flows (mock simulator, heuristic optimizer, baseline + optimizer
dispatch, aggregation, report generation) remain intact.

**New modules**

| Layer | Module | Role |
|---|---|---|
| Simulator Execution | `backend/app/simulator/real_cli.py` | `RealCliSimulatorAdapter` — subprocess adapter that speaks the JSON file protocol defined in `archive/phase8-real-sim-and-gpt-tuning.md`. Registered in `simulator/factory.py` as `real_cli`. |
| Simulator Execution | `scripts/simulators/example_real_simulator.py` | Reference external simulator used by tests and by the `real_cli` demo. |
| Orchestration | `backend/app/orchestration/acceptance.py` | `evaluate_candidate()` — deterministic acceptance check (pass-rate, RMSE, max-error). |
| Optimization Strategy | `backend/app/orchestration/llm_parameter_proposer.py` | Server-side OpenAI client; validates + clamps + dedups proposals. Emits `llm_proposal_{started,completed,failed}` `JobEvent`s. |
| Secrets | `backend/app/secrets.py` | Fernet-based encryption for the per-job OpenAI API key. |
| Persistence | `backend/app/models.py` (extended) | New `JobSecret` table, Phase 8 `Job` columns, `CandidateParameterSet.source_type="llm_optimizer"`. |

**Iterative loop**

`job_manager.start_job` now dispatches only the baseline. When a generation
finishes, `aggregation.finalize_job_if_ready` calls the acceptance evaluator:

- pass → mark best, generate report, `status=COMPLETED`,
  `optimization_outcome="success"`;
- fail & more budget → dispatch the next generation via heuristic optimizer
  or GPT proposer;
- fail & budget exhausted → finalize with a best-so-far report and
  `optimization_outcome` ∈ {`max_iterations_reached`, `no_usable_candidate`,
  `llm_failed`}.

Per-job simulator backend selection lives in `trial_executor`; the legacy
`SIMULATOR_BACKEND` env var still wins when set (Phase 7 backward
compatibility), otherwise the per-job `simulator_backend_requested` column
is used.

**Security boundary**

- OpenAI calls are **server-side only**; the frontend never contacts OpenAI.
- The API key is stored encrypted (`JobSecret.encrypted_api_key`) with
  `APP_SECRET_KEY` and is soft-deleted on terminal state. It is never
  echoed by any API response and never logged.
- GPT can **only** emit structured JSON proposals that match the
  `PARAMETER_SAFE_RANGES` schema; the backend clamps and validates before
  persisting a new `CandidateParameterSet`. GPT cannot control the worker
  or execute simulations directly.

See [`archive/phase8-real-sim-and-gpt-tuning.md`](archive/phase8-real-sim-and-gpt-tuning.md)
for the adapter protocol, prompt/response schemas, env vars, and
verification commands.
