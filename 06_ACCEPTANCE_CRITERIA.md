# 06_ACCEPTANCE_CRITERIA.md

## 1. 文档信息
- **Document Title**: DroneDream Acceptance Criteria
- **Version**: v1.0
- **Product Stage**: MVP
- **Audience**: Devin、产品负责人、前后端工程师、测试人员
- **Purpose**: 定义 DroneDream MVP 的验收标准、功能完成标准、异常场景要求和 Definition of Done。

---

## 2. Acceptance Philosophy
- 验收关注系统行为是否正确、完整、稳定
- MVP 验收优先级：主流程完整 → 核心功能可用 → 异常场景合理 → 数据可追踪 → 为下一阶段扩展预留边界
- 只有静态页面或纯 mock 图表不能视为通过验收

---

## 3. Acceptance Scope
覆盖：
- 产品级验收
- 页面级验收
- 表单与交互验收
- API 级验收
- 数据持久化验收
- Job / Trial 状态机验收
- mock simulator / worker 闭环验收
- 边界和错误场景验收

---

## 4. Product-Level Acceptance

### AC-P1: User Can Create a Job
**Pass Condition**
- 用户可以进入 New Job 页面
- 页面显示完整表单
- 默认值正确
- 合法输入可成功提交
- 系统创建真实 job 记录
- 页面跳转到 Job Detail

### AC-P2: User Can Observe Job Progress
**Pass Condition**
- Job 创建后能进入 `QUEUED` 或 `RUNNING`
- Job Detail 页面能显示当前状态
- 页面能自动刷新或轮询更新
- 页面能显示阶段或进度信息

### AC-P3: User Can View Final Results
**Pass Condition**
- completed job 展示 `COMPLETED`
- 页面显示 baseline metrics
- 页面显示 optimized metrics
- 页面显示 best parameters
- 页面显示至少一个对比图表
- 页面显示最终摘要文本

### AC-P4: User Can Understand Failure and Retry
**Pass Condition**
- failed job 展示 `FAILED`
- 页面显示用户可读失败摘要
- 页面提供 rerun 入口
- rerun 创建新 job
- 原 job 历史被保留

### AC-P5: User Can Review Historical Jobs
**Pass Condition**
- Dashboard 或 History 能显示历史 jobs
- 至少显示 job id、track type、status、created at
- 用户可以点击某个 job 进入详情页

---

## 5. Page-Level Acceptance

### Dashboard
- 显示标题和主要 CTA
- 显示 recent jobs table
- 显示 summary cards
- 具备 loading / empty / error 状态

### New Job
- 展示全部必需字段
- 默认值正确
- 前端验证生效
- 合法提交后成功跳转
- 提交失败后保留表单内容

### Job Detail
- 显示核心 summary
- 支持 running / aggregating / completed / failed / cancelled
- completed 时显示 best params、metrics cards、baseline vs optimized、trial summary、summary text

### Trial Detail
- 显示 trial metadata、metrics、failure reason（若失败）

### History / Reports
- 列出 jobs
- 支持 empty state
- 可进入详情

---

## 6. Form and Interaction Acceptance
- 必填字段不能为空
- 数值字段必须可解析
- altitude 和 wind 范围严格校验
- 枚举字段必须合法
- Create Job flow 完整
- View Job flow 完整
- Retry flow 完整

---

## 7. API-Level Acceptance
- 所有 API 响应使用统一 envelope
- 错误结构一致
- 状态枚举稳定
- `POST /jobs` 创建真实 job
- `GET /jobs` 返回列表数据
- `GET /jobs/{job_id}` 返回详情
- `POST /jobs/{job_id}/rerun` 创建新 job
- `POST /jobs/{job_id}/cancel` 只对可取消 job 生效
- `GET /jobs/{job_id}/trials` 返回 trial summaries
- `GET /trials/{trial_id}` 返回 trial detail
- `GET /jobs/{job_id}/report` 返回最终报告
- report not ready 时返回明确错误

---

## 8. Data-Level Acceptance
- job 记录必须持久化
- job 状态变化必须持久化
- baseline candidate 必须存在
- candidate 记录必须彼此独立
- best candidate 必须可识别
- trial 必须逐条持久化
- trial 的状态和执行元数据必须保存
- trial metrics 必须保存
- completed job 必须生成 report
- artifact 元数据必须可查询

---

## 9. State Machine Acceptance
### Job
- `CREATED -> QUEUED -> RUNNING -> AGGREGATING -> COMPLETED`
- 出错可进入 `FAILED`
- 用户取消可进入 `CANCELLED`
- `COMPLETED / FAILED / CANCELLED` 为终态

### Trial
- `PENDING -> RUNNING -> COMPLETED`
- 或进入 `FAILED / CANCELLED`

### Report
- `PENDING -> READY`
- 或 `PENDING -> FAILED`

---

## 10. Async Execution and Worker Acceptance
- 创建 job 不能同步阻塞到最终结果
- trial 必须由 worker 或等价异步执行单元处理
- worker 失败不能拖垮系统
- timeout 必须显式记录
- MVP 必须能在 mock simulator 模式下跑通完整主流程
- mock 模式也必须遵守真实系统契约

---

## 11. Aggregation and Result Acceptance
- 每个 job 必须执行 baseline
- candidate 的得分必须来自多个 trial 的聚合
- best candidate 选择逻辑必须稳定
- UI 展示的结果必须来自真实持久化数据

---

## 12. Error and Edge Case Acceptance
- 缺失必填字段时前后端都拦截
- 非法枚举时报错
- 数值越界时报错
- job not found 返回 404
- trial not found 返回 404
- report not ready 返回明确错误
- worker timeout 会被记录
- 部分 trial 失败时系统表现合理
- terminal job 不能重复 cancel
- 页面加载失败时必须有用户可读反馈
- 提交失败后不能清空用户输入

---

## 13. Basic Quality Acceptance
- 术语一致
- UI 与 API 契约一致
- 失败可追踪到 job / candidate / trial
- rerun 不覆盖原 job
- 历史记录保留

---

## 14. Definition of Done
当且仅当以下条件全部满足时，MVP 可视为完成：

1. 核心页面可用：Dashboard、New Job、Job Detail、Trial Detail、History / Reports
2. 主流程端到端可跑通：创建 job、看状态、看 completed、看 failed、rerun、看 history
3. API 契约符合 `04_API_SPEC.md`
4. Job、Candidate、Trial、TrialMetric、Report 数据真实持久化
5. job 是异步执行的，trial 由 worker 或等价机制执行
6. 结果页能展示 baseline、optimized、best params、对比图、summary text
7. 常见失败场景被处理
8. mock simulator 模式下可完整演示

---

## 15. Constraints for Devin
- 不能只交付 UI-only prototype
- 不能跳过 baseline
- 不能把 candidate / trial 混成一层
- 不能忽略 failure states
- 不能为了赶工破坏 API 契约和状态枚举
