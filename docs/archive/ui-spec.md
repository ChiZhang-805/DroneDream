# 03_UI_SPEC.md

## 1. 文档信息
- **Document Title**: DroneDream UI / UX Specification
- **Version**: v1.0
- **Product Stage**: MVP
- **Audience**: Devin、前端工程师、产品设计者、后端联调人员
- **Purpose**: 定义 MVP 的页面结构、组件布局、用户交互、表单规则、页面状态和错误展示方式。

---

## 2. UI Design Principles
- 任务中心化，不暴露底层飞控复杂度
- 非飞控用户也能完成基本流程
- 长任务必须提供明确状态反馈
- 结果页必须突出 baseline vs optimized、best params 和关键指标
- 全站术语统一：Job / Trial / Candidate / Baseline / Optimized / Metrics / Report

---

## 3. Global Navigation and Layout
### Navigation
- Dashboard
- New Job
- History / Reports
- Settings（可选）

### Layout
- Left Sidebar
- Top Header
- Main Content Area

### Global States
- Loading
- Empty
- Error

---

## 4. Page Inventory
1. Dashboard
2. New Job
3. Job Detail
4. Trial Detail
5. History / Reports

---

## 5. Dashboard Page
### Required Sections
- Page Header
- Status Summary Cards
- Recent Jobs Table
- Empty State

### Required Columns
- Job ID
- Track Type
- Status
- Objective Profile
- Created At
- Updated At
- Action

### States
- Loading
- Empty
- Success
- Error

---

## 6. New Job Page
### Required Sections
- Track Configuration
- Environment Configuration
- Optimization Objective
- Submission Controls

### Required Fields
- Track Type
- Start X
- Start Y
- Altitude
- Wind North / East / South / West
- Sensor Noise
- Optimization Goal

### Defaults
- `track_type = circle`
- `start_x = 0`
- `start_y = 0`
- `altitude = 3.0`
- `wind_* = 0`
- `sensor_noise = medium`
- `objective_profile = robust`

### Validation
- 必填字段不能为空
- altitude 范围 `[1.0, 20.0]`
- wind 范围 `[-10, 10]`

### Submit Behavior
- 点击 `Create Job`
- 校验通过后调用 `POST /jobs`
- 成功跳转到 Job Detail
- 失败保留表单内容并显示错误

---

## 7. Job Detail Page
### Required Sections
- Job Header
- Job Summary Card
- Status Badge
- Progress Section
- Metrics Cards
- Baseline vs Optimized Comparison
- Best Parameters Section
- Trial Summary Table
- Diagnostics / Logs Panel

### Supported States
- Queued
- Running
- Aggregating
- Completed
- Failed
- Cancelled

### Polling
对 `QUEUED / RUNNING / AGGREGATING` 状态的 job 自动轮询更新。

---

## 8. Trial Detail Page
### Required Sections
- Trial Header
- Trial Metadata
- Trial Metrics
- Trial Plot / Visualization
- Failure Details

### States
- Loading
- Success
- Failed Trial
- Error / Not Found

---

## 9. History / Reports Page
### Required Sections
- Page Header
- Filter Bar
- Jobs Table
- Empty State

### Required Columns
- Job ID
- Track Type
- Objective Profile
- Status
- Created At
- Updated At
- Action

---

## 10. Shared Components
- Status Badge
- Metric Card
- Section Card
- Data Table
- Alert / Notice

---

## 11. Error Handling
### Required Cases
- Failed to load page data
- Invalid form submission
- Job execution failure
- Trial execution failure
- Missing resource / 404

错误文案必须用户可读，不直接显示底层堆栈。

---

## 12. Accessibility and Usability
- 所有字段必须有 label
- 错误提示必须与字段关联
- 状态颜色不能成为唯一识别方式
- MVP 优先桌面端，但中等宽度下不能完全失效

---

## 13. Constraints for Devin
- 不要在 MVP 中先做复杂图形编辑器
- 不要优先做复杂动画
- 优先实现 Dashboard / New Job / Job Detail / Trial Detail / History
- 共用组件应可复用
- 术语必须保持一致
