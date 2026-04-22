# 01_PRD.md

## 1. 文档信息
- **Document Title**: DroneDream Product Requirements Document
- **Version**: v1.0
- **Product Stage**: MVP
- **Audience**: Devin、产品负责人、前后端工程师
- **Purpose**: 指导从零开始实现一个可运行、可演示、可扩展的网页版无人机赛道仿真与自动调参产品。

---

## 2. Product Overview

### 2.1 Product Name
DroneDream

### 2.2 One-line Definition
DroneDream 是一个基于网页的无人机赛道仿真与自动调参平台，允许用户定义赛道、环境扰动和初始条件，并自动搜索最适合该任务的控制参数，最终以可视化结果和结构化报告的形式返回优化结果。

### 2.3 Problem Statement
当前无人机控制参数调试通常依赖手工修改参数、反复运行仿真、基于经验判断方向，缺少系统化搜索与统一产品界面。对于不同赛道、风场和传感器噪声条件，同一套参数往往表现不同，但缺少便捷的条件化调参工具。

### 2.4 Product Vision
用户不需要理解底层 PX4 参数名，只需要描述赛道、风、噪声和优化偏好，系统就能自动完成仿真调参与结果展示。

---

## 3. Goals

### 3.1 Business Goals
- 构建一个可演示、可持续迭代的无人机仿真调参 Web 产品原型。
- 形成可用于研究展示、项目汇报或后续产品化扩展的基础平台。

### 3.2 User Value Goals
- 降低用户定义仿真任务和调参实验的门槛。
- 让用户无需直接理解飞控底层参数也能发起任务。
- 为用户提供清晰的 baseline vs optimized 对比结果。

### 3.3 Technical Goals
- 支持异步 job / trial 执行模型。
- 支持多次 trial 聚合评分。
- 优化逻辑与 LLM 解释逻辑解耦。
- 支持 mock simulator 和真实 simulator adapter 双轨设计。

### 3.4 MVP Goals
1. 用户可以在网页端创建一个仿真优化任务。
2. 系统可以接收任务并进入异步执行流程。
3. 系统可以产生 baseline 和 optimized 结果。
4. 用户可以看到任务状态、关键指标、最优参数和结果图表。
5. 用户可以查看失败原因并重新运行任务。

---

## 4. Non-Goals
以下内容明确不在 MVP 范围内：
- 多机协同仿真
- 多用户实时协作
- 任意机型上传与自动解析
- 实机无人机接入
- 在线学习型控制器训练
- 分段或连续时变参数调度
- 自定义 3D 场景编辑器
- 任意 PX4 参数自由读写
- 复杂权限系统和组织管理

---

## 5. Target Users

### 5.1 Research / Engineering User
- 具有机器人、控制、无人机、仿真或相关背景
- 关心轨迹误差、成功率、参数搜索效率和实验复现

### 5.2 Product / Demo User
- 不一定理解 PX4、MAVSDK 或飞控参数
- 更关注是否能方便完成配置和查看结果

---

## 6. Core User Scenarios
- 创建标准优化任务
- 监控任务进度
- 查看最终优化结果
- 理解失败并重试
- 查看历史任务

---

## 7. MVP Scope

### In Scope
- 赛道：`circle` / `u_turn` / `lemniscate`
- 环境输入：起点、固定高度、恒定风、三档传感器噪声
- 优化方式：全局恒定参数优化
- 输出：best params、baseline metrics、optimized metrics、对比图、状态信息、失败摘要
- 页面：Dashboard、New Job、Job Detail、History / Reports

### Out of Scope
- 自定义 waypoint 赛道编辑
- 分段参数调度
- 多机型支持
- 实时协作
- 高级报告导出

---

## 8. Functional Requirements
- Create Job
- Validate Input
- Run Baseline Evaluation
- Generate Candidate Parameter Sets
- Execute Trials Asynchronously
- Track Job and Trial Status
- Aggregate Trial Results
- Display Final Results
- Show Failure Reason
- Re-run Job
- View History

---

## 9. Input Specification
- `track_type`: `circle | u_turn | lemniscate`, default `circle`
- `start_x`: number, default `0`
- `start_y`: number, default `0`
- `altitude_m`: number, default `3.0`, range `[1.0, 20.0]`
- `wind_north/east/south/west`: number, default `0`, range `[-10, 10]`
- `sensor_noise_level`: `low | medium | high`, default `medium`
- `objective_profile`: `stable | fast | smooth | robust | custom`, default `robust`

---

## 10. Non-Functional Requirements
- 可用性：非飞控用户也能完成提交
- 可靠性：单个 worker 失败不应拖垮系统
- 可观测性：job、candidate、trial 可追踪
- 可重复性：mock simulator 在相同输入和 seed 下可复现
- 安全性：参数必须经过白名单限制

---

## 11. Success Metrics
- 用户可独立完成创建 job、查看结果、重跑任务的完整流程
- Job 状态流完整、可追踪
- mock 模式下可稳定跑通端到端闭环
- 页面术语统一，错误提示明确

---

## 12. Constraints for Devin
- 以“任务”为产品中心，而不是“参数编辑器”为中心
- 不要直接暴露大量底层 PX4 参数给终端用户
- 必须预留 mock simulator 和真实 simulator adapter 的边界
- 必须使用异步 job/trial 思路，而不是同步阻塞式仿真接口

---

## 13. Summary
DroneDream MVP 的核心不是“让用户手工改参数”，而是“让用户定义任务，由系统自动运行仿真优化并返回结果”。
