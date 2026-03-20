# Phase-1 Acceptance Checklist（第一期验收清单）

## 1. 验收范围

本清单仅覆盖 Phase-1：信息采集与聚合。

不在范围内：
- AI 匹配
- 企业资质库匹配
- 投标文件生成

## 2. 已实现能力与验证方法

| 能力 | 验证方法 | 入口 / curl 示例 | 预期结果 |
|---|---|---|---|
| 健康检查 | 访问健康接口 | `curl "http://127.0.0.1:8000/healthz"` | 返回 `{"status":"ok"...}` |
| 来源列表/详情 | 查看来源信息 | `GET /sources`、`GET /sources/{code}` | 返回来源配置字段 |
| 来源配置更新 | 修改来源运行参数 | `PATCH /sources/{code}` | `is_active/crawl_interval_minutes/supports_js_render/default_max_pages` 生效 |
| 手动触发抓取 | 从来源触发任务 | `POST /sources/{code}/crawl-jobs` | 创建 `manual` 任务并返回任务摘要 |
| 抓取任务查询 | 查看任务状态与统计 | `GET /crawl-jobs`、`GET /crawl-jobs/{id}` | 可按筛选查询，详情含统计字段 |
| 公告检索列表 | 条件检索公告 | `GET /notices?keyword=低压&source_code=anhui_ggzy_zfcg` | 返回筛选后的公告列表 |
| 公告详情与版本 | 查看公告版本/附件信息 | `GET /notices/{id}` | 返回当前版本、历史版本、附件摘要 |
| 公告导出 CSV | 导出筛选结果 | `GET /notices/export.csv?source_code=anhui_ggzy_zfcg` | 返回 `text/csv` |
| 公告导出 JSON | 导出筛选结果 | `GET /notices/export.json?source_code=anhui_ggzy_zfcg` | 返回 `application/json` |
| 原始文档查询 | 查看归档原文记录 | `GET /raw-documents`、`GET /raw-documents/{id}` | 返回原文元数据与关联摘要 |
| 错误事件查询 | 查看抓取异常事件 | `GET /crawl-errors`、`GET /crawl-errors/{id}` | 返回错误信息及关联对象摘要 |
| 统计总览 | 查看系统运行概览 | `GET /stats/overview` | 返回总数、7天趋势、最近失败任务/错误 |
| 管理页-总览 | 查看运营总览页 | `/admin/dashboard` | 展示指标、近期任务与错误 |
| 管理页-来源 | 查看/编辑来源 | `/admin/sources`、`/admin/sources/{code}` | 可查看并编辑来源配置 |
| 管理页-任务 | 查看任务列表与详情 | `/admin/crawl-jobs` | 可筛选并查看详情 |
| 管理页-公告 | 查看公告与导出入口 | `/admin/notices` | 可筛选、查看详情、导出 CSV/JSON |
| 管理页-原始文档 | 查看原文记录 | `/admin/raw-documents` | 可查看详情并按条件筛选 |
| 管理页-错误事件 | 查看错误记录 | `/admin/crawl-errors` | 可筛选并查看错误详情 |

## 3. 推荐验收顺序（演示顺序）

1. 启动服务并通过 `healthz`。
2. 运行 `anhui_ggzy_zfcg` 样板源抓取（建议入库模式）。
3. 验证来源与抓取任务：`/sources`、`/crawl-jobs`。
4. 验证公告链路：`/notices`、`/notices/{id}`。
5. 验证导出：`/notices/export.csv`、`/notices/export.json`。
6. 验证原始文档与错误事件：`/raw-documents`、`/crawl-errors`。
7. 打开 `/admin/dashboard` 与 `/admin/notices` 做页面演示。

## 4. 已知限制

- 仅提供 Phase-1 最小可用能力，不包含智能推荐或自动投标能力。
- 抓取触发为同步最小实现，不包含复杂异步任务编排/分布式调度。
- 样板来源以 `anhui_ggzy_zfcg` 为主，其他来源需按同样模式扩展 spider/parser。
- 权限与多租户控制未纳入第一期范围。
