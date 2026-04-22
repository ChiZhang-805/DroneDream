# 05_DATA_MODEL.md

## 1. 文档信息
- **Document Title**: DroneDream Data Model Specification
- **Version**: v1.0
- **Audience**: Devin、后端工程师、数据库设计者、联调人员
- **Purpose**: 定义 DroneDream MVP 的核心实体、字段结构、状态机、实体关系、索引建议和持久化边界。

---

## 2. Data Modeling Principles
- 数据模型围绕产品主流程组织：Job → Candidate → Trial → Metric → Report
- Job / Candidate / Trial 必须分层
- 历史记录必须保留
- 高频查询字段应结构化，不要全部塞进 JSON
- 可扩展字段可以使用 JSON

---

## 3. Core Entity Overview
MVP 的核心实体如下：
1. `User`
2. `Job`
3. `CandidateParameterSet`
4. `Trial`
5. `TrialMetric`
6. `JobReport`
7. `Artifact`
8. `JobEvent`（推荐）

---

## 4. Entity: User
### Suggested Fields
- `id`
- `email`（optional）
- `display_name`（optional）
- `created_at`
- `updated_at`

### Notes
即使 MVP 为单用户模式，也建议保留 `user_id` 关联。

---

## 5. Entity: Job
### Suggested Fields
- `id`
- `user_id`
- `track_type`
- `start_point_x`
- `start_point_y`
- `altitude_m`
- `wind_north`
- `wind_east`
- `wind_south`
- `wind_west`
- `sensor_noise_level`
- `objective_profile`
- `status`
- `current_phase`
- `progress_completed_trials`
- `progress_total_trials`
- `latest_error_code`
- `latest_error_message`
- `best_candidate_id`
- `baseline_candidate_id`
- `source_job_id`
- `created_at`
- `updated_at`
- `queued_at`
- `started_at`
- `completed_at`
- `cancelled_at`
- `failed_at`

### Status Enum
- `CREATED`
- `QUEUED`
- `RUNNING`
- `AGGREGATING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

---

## 6. Entity: CandidateParameterSet
### Suggested Fields
- `id`
- `job_id`
- `generation_index`
- `source_type`
- `label`
- `parameter_json`
- `aggregated_score`
- `aggregated_metric_json`
- `trial_count`
- `completed_trial_count`
- `failed_trial_count`
- `rank_in_job`
- `is_best`
- `is_baseline`
- `created_at`
- `updated_at`

### source_type Enum
- `baseline`
- `optimizer`
- `manual`
- `rerun_copy`

---

## 7. Entity: Trial
### Suggested Fields
- `id`
- `job_id`
- `candidate_id`
- `seed`
- `scenario_type`
- `scenario_config_json`
- `worker_id`
- `status`
- `attempt_count`
- `failure_reason`
- `failure_code`
- `queued_at`
- `started_at`
- `finished_at`
- `simulator_backend`
- `log_excerpt`

### scenario_type Enum
- `nominal`
- `noise_perturbed`
- `wind_perturbed`
- `combined_perturbed`

### status Enum
- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

---

## 8. Entity: TrialMetric
### Suggested Fields
- `id`
- `trial_id`
- `rmse`
- `max_error`
- `overshoot_count`
- `completion_time`
- `crash_flag`
- `timeout_flag`
- `score`
- `final_error`
- `pass_flag`
- `instability_flag`
- `raw_metric_json`
- `created_at`
- `updated_at`

---

## 9. Entity: JobReport
### Suggested Fields
- `id`
- `job_id`
- `best_candidate_id`
- `summary_text`
- `baseline_metric_json`
- `optimized_metric_json`
- `comparison_metric_json`
- `best_parameter_json`
- `report_status`
- `created_at`
- `updated_at`

### report_status Enum
- `PENDING`
- `READY`
- `FAILED`

---

## 10. Entity: Artifact
### Suggested Fields
- `id`
- `owner_type`
- `owner_id`
- `artifact_type`
- `display_name`
- `storage_path`
- `mime_type`
- `file_size_bytes`
- `created_at`

### owner_type Enum
- `job`
- `trial`
- `job_report`

### artifact_type Enum
- `trajectory_plot`
- `comparison_plot`
- `worker_log`
- `telemetry_json`
- `report_export`

---

## 11. Entity: JobEvent (Recommended)
### Suggested Fields
- `id`
- `job_id`
- `event_type`
- `event_message`
- `payload_json`
- `created_at`

### event_type Examples
- `job_created`
- `job_queued`
- `job_started`
- `baseline_started`
- `candidate_generated`
- `trial_dispatched`
- `trial_completed`
- `aggregation_started`
- `report_generated`
- `job_failed`
- `job_cancelled`

---

## 12. State Machines

### Job State Machine
Allowed States:
- `CREATED`
- `QUEUED`
- `RUNNING`
- `AGGREGATING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

### Trial State Machine
Allowed States:
- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `CANCELLED`

### Report State Machine
Allowed States:
- `PENDING`
- `READY`
- `FAILED`

---

## 13. Relationships
- User → Job：one-to-many
- Job → CandidateParameterSet：one-to-many
- CandidateParameterSet → Trial：one-to-many
- Trial → TrialMetric：one-to-one（推荐）
- Job → JobReport：one-to-one（MVP）
- Artifact 通过 `(owner_type, owner_id)` 泛化关联
- Job → JobEvent：one-to-many

---

## 14. Normalization vs JSON Strategy
### 必须结构化的字段
- job status
- track_type
- altitude_m
- sensor_noise_level
- objective_profile
- trial status
- seed
- scenario_type
- core metrics（如 rmse、score）

### 可以使用 JSON 的字段
- `parameter_json`
- `aggregated_metric_json`
- `scenario_config_json`
- `raw_metric_json`
- `payload_json`
- `best_parameter_json`

---

## 15. Indexing Strategy
### Required Indexes
- Job: `(user_id, created_at desc)`, `status`, `created_at`, `source_job_id`
- Candidate: `(job_id, generation_index)`, `(job_id, is_best)`, `(job_id, is_baseline)`
- Trial: `job_id`, `candidate_id`, `status`, `(candidate_id, seed, scenario_type)`
- TrialMetric: `trial_id`
- JobReport: unique `job_id`
- Artifact: `(owner_type, owner_id)`
- JobEvent: `(job_id, created_at)`

---

## 16. Constraints for Devin
- 不要把 Job、Candidate、Trial 合并成一张表
- 不要通过覆盖记录丢失实验历史
- 不要把高频查询字段全部藏在 JSON 里
- 状态、时间戳、错误字段必须能反映异步执行过程
- 数据模型不能假设只有某一种 simulator backend
