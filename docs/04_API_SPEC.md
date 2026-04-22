# 04_API_SPEC.md

## 1. 文档信息
- **Document Title**: DroneDream API Specification
- **Version**: v1.0
- **API Namespace**: `/api/v1`
- **Audience**: Devin、前端工程师、后端工程师、联调人员
- **Purpose**: 定义 DroneDream MVP 的前后端接口契约、请求响应结构、状态码、错误码和内部服务边界。

---

## 2. API Design Principles
- REST 风格
- JSON only
- 返回结构统一
- 错误结构统一
- job 创建接口必须异步返回 `job_id`
- `/api/v1` 作为版本前缀

---

## 3. Common Conventions
- `Content-Type: application/json`
- 时间格式：ISO 8601 UTC
- 状态枚举必须固定
- 前端将所有 ID 作为字符串处理

### Recommended Enums
- job status: `CREATED | QUEUED | RUNNING | AGGREGATING | COMPLETED | FAILED | CANCELLED`
- trial status: `PENDING | RUNNING | COMPLETED | FAILED | CANCELLED`
- track type: `circle | u_turn | lemniscate`
- sensor noise: `low | medium | high`

---

## 4. Standard Response Format

### Success
```json
{
  "success": true,
  "data": {},
  "error": null
}
```

### Error
```json
{
  "success": false,
  "data": null,
  "error": {
    "code": "INVALID_INPUT",
    "message": "Invalid request payload",
    "details": null
  }
}
```

### Pagination
```json
{
  "success": true,
  "data": {
    "items": [],
    "page": 1,
    "page_size": 20,
    "total": 0
  },
  "error": null
}
```

---

## 5. Standard Error Codes
- `INVALID_INPUT`
- `UNAUTHORIZED`
- `FORBIDDEN`
- `JOB_NOT_FOUND`
- `TRIAL_NOT_FOUND`
- `JOB_NOT_RUNNABLE`
- `JOB_ALREADY_COMPLETED`
- `JOB_ALREADY_CANCELLED`
- `WORKER_TIMEOUT`
- `SIMULATION_FAILED`
- `REPORT_NOT_READY`
- `INTERNAL_ERROR`

---

## 6. Public API Endpoints
- `POST /api/v1/jobs`
- `GET /api/v1/jobs`
- `GET /api/v1/jobs/{job_id}`
- `POST /api/v1/jobs/{job_id}/rerun`
- `POST /api/v1/jobs/{job_id}/cancel`
- `GET /api/v1/jobs/{job_id}/trials`
- `GET /api/v1/trials/{trial_id}`
- `GET /api/v1/jobs/{job_id}/report`
- `GET /api/v1/jobs/{job_id}/artifacts`

---

## 7. Job APIs

### POST /api/v1/jobs
请求字段：
- `track_type`
- `start_point`
- `altitude_m`
- `wind`
- `sensor_noise_level`
- `objective_profile`

成功返回：
- `job_id`
- `status = QUEUED`

### GET /api/v1/jobs
返回 jobs 列表，用于 Dashboard / History。

### GET /api/v1/jobs/{job_id}
返回 job 详情，包括：
- 基本输入配置
- `status`
- `progress`
- `created_at`
- `updated_at`
- `completed_at`

### POST /api/v1/jobs/{job_id}/rerun
基于已有 job 配置创建新的 rerun 任务，返回新 `job_id`。

### POST /api/v1/jobs/{job_id}/cancel
取消尚未完成的 job，返回 `status = CANCELLED`。

---

## 8. Trial APIs

### GET /api/v1/jobs/{job_id}/trials
返回 trial 摘要列表，至少包含：
- `id`
- `candidate_id`
- `seed`
- `scenario_type`
- `status`
- `score`

### GET /api/v1/trials/{trial_id}`
返回单个 trial 的详细信息：
- metadata
- metrics
- failure reason（若失败）

---

## 9. Report and Artifact APIs

### GET /api/v1/jobs/{job_id}/report
返回最终报告：
- `best_candidate_id`
- `summary_text`
- `baseline_metrics`
- `optimized_metrics`
- `best_parameters`

### GET /api/v1/jobs/{job_id}/artifacts
返回 artifacts 元数据列表。

---

## 10. Input Validation Rules
- `track_type` 必须在 `circle | u_turn | lemniscate`
- `altitude_m` 必须在 `[1.0, 20.0]`
- `wind.*` 必须在 `[-10, 10]`
- `sensor_noise_level` 必须在 `low | medium | high`
- `objective_profile` 必须在 `stable | fast | smooth | robust | custom`
- 未定义字段推荐直接拒绝

---

## 11. Internal Service Interfaces

### Job Manager ↔ Optimizer
- 输入：job_id、generation_index、previous_results
- 输出：下一批 candidates

### Dispatcher ↔ Worker
- 输入：trial payload
- 包含：job config、candidate params、seed、scenario_type

### Worker → Backend
- 输出：trial status、metrics、failure reason、artifacts

---

## 12. Polling Expectations
- Dashboard / History：手动刷新或按需刷新即可
- Job Detail：对 `QUEUED / RUNNING / AGGREGATING` job 周期性轮询
- Trial Detail：trial 运行中可轮询

---

## 13. Constraints for Devin
- 不要把异步优化流程塞进同步接口
- 不要让同一接口在不同状态下返回完全不同结构
- 错误 object 结构必须稳定
- 状态必须用固定枚举
- API 不应和某一种 simulator 实现强耦合
