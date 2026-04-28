# DroneDream real_cli Artifact Schema v1

本规范定义 external simulator（如 PX4/Gazebo）、backend `real_cli` 解析器、frontend 轨迹回放之间的稳定契约。

## 1) `trial_result.json`

成功 trial 的标准输出：

```json
{
  "success": true,
  "metrics": {
    "rmse": 0.42,
    "max_error": 1.1,
    "overshoot_count": 0,
    "completion_time": 18.2,
    "score": 94.0
  },
  "artifacts": [
    {
      "artifact_type": "telemetry_json",
      "storage_path": "/abs/or/relative/path/to/telemetry.json"
    }
  ],
  "log_excerpt": "trial summary..."
}
```

约束：
- `success` 必须是 boolean。
- `metrics` 在 `success=true` 时必须存在并满足后端指标字段要求。
- `artifacts` 必须是数组。
- `log_excerpt` 建议提供，便于 UI 快速展示。

## 2) `telemetry_json` artifact

- `artifact_type = "telemetry_json"`
- `mime_type = "application/json"`（缺失时后端可推断）

JSON body：

```json
{
  "schema_version": "dronedream.telemetry.v1",
  "samples": [
    {"t": 0, "x": 0, "y": 0, "z": 3}
  ]
}
```

约束：
- `samples[]` 每个元素至少包含数值类型 `t/x/y/z`。
- 可包含扩展字段（如 `vx/vy/vz/yaw/reference_x/...`）。

## 3) `reference_track_json` artifact

- `artifact_type = "reference_track_json"`
- `mime_type = "application/json"`（缺失时后端可推断）

JSON body：

```json
{
  "schema_version": "dronedream.reference_track.v1",
  "reference_track": [
    {"x": 0, "y": 0, "z": 3}
  ]
}
```

约束：
- `reference_track[]` 每个点必须包含数值类型 `x/y/z`。

## 4) `worker_log/stdout/stderr` artifact 规范

推荐如下类型：
- `worker_log`：worker / runner 自身日志，`mime_type = "text/plain"`
- `simulator_stdout`：底层 simulator stdout，`mime_type = "text/plain"`
- `simulator_stderr`：底层 simulator stderr，`mime_type = "text/plain"`

这些 artifact 的 body 为纯文本；后端允许缺省 `mime_type` 并按 `artifact_type` 推断。

## 5) 本地 artifact 路径安全要求

`artifacts[].storage_path` 指向本地文件时，解析后的绝对路径必须位于 allowed artifact roots 下（例如 `REAL_SIMULATOR_ARTIFACT_ROOT` / 后端配置的 artifact roots）。

- 不在 allowed roots 内的路径会被后端忽略（不注册到 trial artifacts）。
- telemetry/reference JSON 仅在“本地文件存在且位于 allowed roots 下”时做轻量 schema 校验。
- 校验失败只记 `warning`，不应让本次 successful trial 变为失败。
