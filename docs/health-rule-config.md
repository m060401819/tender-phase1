# Health Rule Config（Phase-2 第7步）

## 1. 目标

将来源健康度判断从“写死规则”升级为“可配置阈值”，并提供最小 API + 管理页面修改能力。

## 2. 配置项

当前支持：

- `recent_error_warning_threshold`
- `recent_error_critical_threshold`
- `consecutive_failure_warning_threshold`
- `consecutive_failure_critical_threshold`
- `partial_warning_enabled`

默认值：

- `recent_error_warning_threshold = 3`
- `recent_error_critical_threshold = 6`
- `consecutive_failure_warning_threshold = 1`
- `consecutive_failure_critical_threshold = 1`
- `partial_warning_enabled = true`

## 3. 接口

- `GET /settings/health-rules`
- `PATCH /settings/health-rules`

`PATCH` 校验规则：

- 阈值必须为非负数
- `warning_threshold` 不能大于对应 `critical_threshold`

## 4. 页面

- `GET /admin/settings/health-rules`
- `POST /admin/settings/health-rules`

页面能力：

- 展示当前阈值
- 修改并保存阈值
- 保存后显示“配置已更新”
- 页面内含最小规则说明（正常/警告/异常判定逻辑）

## 5. 健康度统一计算

健康度计算统一收敛到：

- `app/services/health_rule_service.py`
- `app/services/source_health_service.py`

`/admin/source-sites`、`/admin/sources/{code}`、`/sources/{code}/health` 均复用同一套规则。
