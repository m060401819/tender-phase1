# 招标信息聚合平台（Phase-1）

本仓库是“招标信息聚合平台第一期”项目骨架，覆盖：
- 多来源信息采集（Scrapy + Playwright 预留）
- 原始页面/归档信息存储（预留管道）
- 结构化字段抽取（预留解析器）
- 去重与版本跟踪（预留模型与服务）
- 检索/列表/详情 API（FastAPI 预留）
- 最小管理端（后续可在 `app/admin` 扩展）

不包含：
- AI 匹配
- 企业资质库匹配
- 投标文件生成

## 0. 交付文档索引

- 演示与接手 Runbook：`docs/runbook.md`
- Phase-1 验收清单：`docs/acceptance-checklist.md`
- 数据模型：`docs/data-model.md`
- Crawler 架构：`docs/crawler-architecture.md`

## 0.1 快速演示路径（5-10 分钟）

1. 启动数据库并执行迁移：`docker compose up -d postgres && alembic upgrade head`
2. 启动 API：`uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`
3. 健康检查：`curl "http://127.0.0.1:8000/healthz"`
4. 运行样板源抓取（入库）：在 `crawler/` 目录执行 `scrapy crawl anhui_ggzy_zfcg -a max_pages=1`（配合 `sqlalchemy` writer）
5. 演示任务与公告：`/admin/crawl-jobs`、`/admin/notices`
6. 演示导出：`/notices/export.csv`、`/notices/export.json`
7. 演示原始文档/错误/总览：`/admin/raw-documents`、`/admin/crawl-errors`、`/admin/dashboard`

## 0.2 Phase-1 功能地图

- 来源管理与触发抓取：
  - API：`/sources`、`/sources/{code}`、`/sources/{code}/crawl-jobs`
  - 页面：`/admin/sources`
  - 文档：`docs/source-admin.md`、`docs/source-config.md`
- 抓取任务与状态追踪：
  - API：`/crawl-jobs`
  - 页面：`/admin/crawl-jobs`
  - 文档：`docs/crawl-job.md`、`docs/crawl-job-api.md`、`docs/crawl-job-admin.md`
- 公告检索/详情/导出：
  - API：`/notices`、`/notices/{id}`、`/notices/export.csv`、`/notices/export.json`
  - 页面：`/admin/notices`
  - 文档：`docs/notice-api.md`、`docs/notice-export.md`、`docs/notice-admin.md`
- 原始文档归档与查看：
  - API：`/raw-documents`
  - 页面：`/admin/raw-documents`
  - 文档：`docs/raw-document-viewer.md`、`docs/raw-document-admin.md`
- 错误事件记录与排查：
  - API：`/crawl-errors`
  - 页面：`/admin/crawl-errors`
  - 文档：`docs/crawl-error-admin.md`
- 统计总览：
  - API：`/stats/overview`
  - 页面：`/admin/dashboard`
  - 文档：`docs/dashboard.md`

## 1. 技术栈
- Python 3.12
- FastAPI
- Scrapy
- Playwright
- PostgreSQL
- SQLAlchemy
- Alembic
- pytest
- Docker Compose

## 2. 目录结构

```text
.
├── app/                    # FastAPI 应用
│   ├── api/                # API 路由
│   ├── core/               # 配置
│   ├── db/                 # DB 连接与基础定义
│   └── models/             # SQLAlchemy 数据模型
├── crawler/                # 爬虫工程
│   ├── scrapy.cfg
│   └── tender_crawler/
│       ├── connectors/     # 采集连接器（含 Playwright 预留）
│       ├── parsers/        # 结构化解析
│       ├── spiders/        # 每个来源独立 spider
│       └── writers/        # DB/归档写入
├── alembic/                # DB 迁移脚本目录
├── docs/                   # 设计文档（含 data-model/crawler-architecture）
├── tests/                  # pytest
├── docker-compose.yml
└── pyproject.toml
```

## 3. 本地启动（不使用 Docker 跑应用）

1. 创建并激活虚拟环境

```bash
python3.12 -m venv .venv
source .venv/bin/activate
```

2. 安装依赖

```bash
pip install -e ".[dev]"
playwright install chromium
```

3. 启动 PostgreSQL（仅数据库）

```bash
docker compose up -d postgres
```

4. 配置环境变量

```bash
cp .env.example .env
```

5. 初始化数据库结构

```bash
alembic upgrade head
```

6. 启动 FastAPI

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

7. 健康检查

```bash
curl http://127.0.0.1:8000/healthz
```

期望返回：

```json
{"status":"ok","service":"tender-phase1"}
```

## 4. 一键 Docker Compose 启动（app + postgres）

```bash
docker compose up --build
```

访问：
- API: `http://127.0.0.1:8000`
- 健康检查: `http://127.0.0.1:8000/healthz`

## 5. 数据库初始化与迁移

首次初始化（已提供初始化迁移 `20260319_0001`）：

```bash
alembic upgrade head
```

查看当前迁移版本：

```bash
alembic current
```

回滚一步：

```bash
alembic downgrade -1
```

后续新增迁移（示例）：

```bash
alembic revision -m "add some table"
alembic upgrade head
```

数据模型说明见：`docs/data-model.md`

## 6. Scrapy 采集启动

先查看可用 spider：

```bash
cd crawler
scrapy list
```

### 6.1 运行真实样板源（安徽省公共资源交易监管网-政府采购）

最小抓取（1 页，默认写入本地 `jsonl`）：

```bash
cd crawler
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```

输出说明：
- 原始页面归档到 `data/raw/`
- 结构化数据写入 `data/staging/*.jsonl`

字段映射和数据流详见：
- `docs/source-anhui-ggzy-zfcg.md`
- `docs/crawler-architecture.md`

### 6.2 写入数据库（PostgreSQL）

确保数据库已迁移到最新后，使用 `sqlalchemy` writer：

```bash
cd crawler
CRAWLER_WRITER_BACKEND=sqlalchemy \
CRAWLER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1 \
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```

可用以下 SQL 验证入库：

```sql
SELECT COUNT(*) FROM raw_document;
SELECT COUNT(*) FROM tender_notice;
SELECT COUNT(*) FROM notice_version;
SELECT COUNT(*) FROM tender_attachment;
SELECT COUNT(*) FROM crawl_error;
```

### 6.3 去重与版本策略（第一期）

写入层统一固化以下规则（与具体 spider 解耦）：
- URL 去重：`normalized_url -> url_hash`，同源同 URL upsert 到 `raw_document`
- 内容去重：同源 `content_hash` 命中标记重复内容；`notice_version` 按 `content_hash` 去重
- 公告归并：`external_id` > `detail_page_url` > `title` 生成 `tender_notice.dedup_hash`
- 版本跟踪：
  - 重复抓取且内容未变：不新增 `notice_version`
  - 内容变化：新增版本并更新 `tender_notice.current_version_id`
  - `tender_notice` 保存当前快照，`notice_version` 保存历史快照
- 公告类型规范化：统一为 `announcement/change/result`，非法值回退 `announcement`

详细说明见：
- `docs/data-model.md`
- `docs/crawler-architecture.md`

### 6.4 公告附件管理（第一期）

附件处理链路：
1. parser 从公告正文抽取附件链接（支持相对链接转绝对链接）
2. `AttachmentArchivePipeline` 可选归档：
   - 默认 `noop`（不下载，仅管理元数据）
   - `local`（下载并归档到本地）
3. writer 将附件 upsert 到 `tender_attachment`，并关联：
   - `tender_notice`
   - `notice_version`（优先 `notice_version_no`，否则当前版本）
   - `raw_document`（若存在同 URL 的归档记录）

附件去重：
- `file_url` 标准化后计算 `url_hash`
- 同源同 `url_hash` 不重复写入，执行更新（upsert）

启用本地附件归档示例：

```bash
cd crawler
ATTACHMENT_ARCHIVER_BACKEND=local \
ATTACHMENT_ARCHIVE_DIR=../data/attachments \
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```

### 6.5 抓取任务管理与调度基础（第一期）

第一期提供最小 `crawl_job` 工作流：
- `job_type`：`manual / scheduled / backfill`
- `status`：`pending / running / succeeded / failed / partial`
- 统计字段：`pages_fetched / documents_saved / notices_upserted / deduplicated_count / error_count`

使用 CLI 手动触发（会自动创建 job、注入 `crawl_job_id`、结束后回写状态）：

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=1
```

常见可选参数：
- `--spider-arg KEY=VALUE`：透传给 spider（可重复）
- `--setting KEY=VALUE`：透传给 Scrapy `-s`
- `--database-url <url>`：覆盖数据库连接
- `--fail-on-partial`：当状态为 `partial` 时返回非 0 退出码

说明：
- spider 外部运行方式不变，仍可直接 `scrapy crawl ...`
- 若要记录 `crawl_job` 统计，请使用 `crawl_job_id` 并开启 `sqlalchemy` writer

详情见：`docs/crawl-job.md`

### 6.6 Crawl Job 查询 API（第一期）

启动 FastAPI 后可直接查询任务记录：

```bash
curl "http://127.0.0.1:8000/crawl-jobs?source_code=anhui_ggzy_zfcg&status=running&limit=20&offset=0"
```

```bash
curl "http://127.0.0.1:8000/crawl-jobs/1"
```

接口能力：
- 列表筛选：`source_code / status / job_type`
- 列表排序：`order_by=started_at|id`（均为倒序）
- 列表分页：`limit / offset`
- 详情字段：包含执行状态、统计字段及 `recent_crawl_error_count`

详细字段说明见：`docs/crawl-job-api.md`

### 6.7 Crawl Job 管理页面（第一期）

最小任务看板页面：
- 列表：`/admin/crawl-jobs`
- 详情：`/admin/crawl-jobs/{id}`

公告管理页入口：

```bash
http://127.0.0.1:8000/admin/crawl-jobs
```

页面能力：
- 列表展示任务核心字段与统计字段
- 支持 `source_code / status / job_type` 筛选
- 支持分页（`limit / offset`）
- 详情页展示 `recent_crawl_error_count` 与原始 JSON 调试区

说明文档见：`docs/crawl-job-admin.md`

### 6.8 Source 管理/配置与手动触发 API（第一期）

新增最小来源管理接口：
- `GET /sources`
- `GET /sources/{code}`
- `PATCH /sources/{code}`
- `POST /sources/{code}/crawl-jobs`

示例：

```bash
curl "http://127.0.0.1:8000/sources"
```

```bash
curl "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg"
```

```bash
curl -X PATCH "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg" \
  -H "Content-Type: application/json" \
  -d '{"is_active": true, "crawl_interval_minutes": 30, "supports_js_render": false, "default_max_pages": 5}'
```

```bash
curl -X POST "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg/crawl-jobs" \
  -H "Content-Type: application/json" \
  -d '{"max_pages": 1, "triggered_by": "api"}'
```

说明：
- `PATCH` 可更新来源最小运行配置：
  - `is_active`
  - `crawl_interval_minutes`
  - `supports_js_render`
  - `default_max_pages`
- `POST` 会创建 `manual` 类型 `crawl_job`
- 同步触发一次 spider 执行（当前最小实现，不依赖队列）
- 支持最小 spider 参数：`max_pages`
- 返回创建后的任务摘要、执行命令和进程返回码

### 6.9 Source 管理页面（第一期）

新增最小来源管理页面：
- 来源列表：`/admin/sources`
- 来源详情：`/admin/sources/{code}`

能力：
- 查看来源基础信息（`code/name/base_url/is_active/supports_js_render/crawl_interval_minutes/default_max_pages`）
- 在详情页编辑来源配置（`is_active/supports_js_render/crawl_interval_minutes/default_max_pages`）
- 在来源详情页通过表单触发一次抓取（`max_pages`）
- 配置保存后回到当前来源详情页（显示最新值）
- 手动抓取提交后跳转到对应 `crawl_job` 详情页

说明文档见：`docs/source-admin.md`、`docs/source-config.md`

### 6.10 Notice 检索与详情 API（第一期）

新增最小公告查询接口：
- `GET /notices`
- `GET /notices/{id}`
- `GET /notices/export.csv`
- `GET /notices/export.json`

列表能力：
- 关键词搜索：`keyword`（匹配 `title / issuer / region`）
- 筛选：`source_code / notice_type / region`
- 排序：按 `published_at` 倒序
- 分页：`limit / offset`

列表示例：

```bash
curl "http://127.0.0.1:8000/notices?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&limit=20&offset=0"
```

详情示例：

```bash
curl "http://127.0.0.1:8000/notices/1"
```

导出示例：

```bash
curl "http://127.0.0.1:8000/notices/export.csv?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

```bash
curl "http://127.0.0.1:8000/notices/export.json?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&region=合肥"
```

详情返回：
- `tender_notice` 主要字段
- 当前 `notice_version` 主要字段
- `versions` 历史版本列表（含 `raw_document` 摘要）
- 附件摘要列表
- 来源基础信息

说明文档见：`docs/notice-api.md`、`docs/notice-export.md`

### 6.11 Notice 管理页面（第一期）

新增最小公告管理页面：
- 列表：`/admin/notices`
- 详情：`/admin/notices/{id}`

页面能力：
- 列表展示 `id/source_code/title/notice_type/issuer/region/published_at/deadline_at/budget_amount`
- 支持 `keyword / source_code / notice_type / region` 筛选
- 支持 `limit / offset` 分页
- 支持导出 CSV/JSON（保留当前筛选条件）
- 详情展示公告主字段、当前版本、历史版本、附件列表、来源信息与原始 JSON 调试区
- 版本区中的 `raw_document` 摘要可跳转到原始文档详情页

访问示例：

```bash
http://127.0.0.1:8000/admin/notices
```

说明文档见：`docs/notice-admin.md`

### 6.12 Notice 版本追踪与原文查看增强（第一期）

增强点：
- `GET /notices/{id}` 新增 `versions` 字段，支持查看同一公告的历史版本
- 每个版本可返回 `raw_document` 摘要（`id/document_type/fetched_at/storage_uri`）
- `/admin/notices/{id}` 新增“历史版本”区域
- 附件列表展示所属版本号（`version_no`）

说明文档见：`docs/notice-versioning.md`

### 6.13 Notice 版本联动查看（第一期）

`/admin/notices/{id}` 进一步增强为可按版本联动查看：

- 支持通过 `version_id` 或 `version_no` 选择指定版本
- 展示选中版本详情字段（`title/notice_type/issuer/region/published_at/deadline_at/content_hash`）
- 展示选中版本关联的 `raw_document` 摘要
- 附件区域仅展示该版本附件

访问示例：

```bash
# 默认查看当前版本
http://127.0.0.1:8000/admin/notices/101

# 按 version_no 查看
http://127.0.0.1:8000/admin/notices/101?version_no=1

# 按 version_id 查看
http://127.0.0.1:8000/admin/notices/101?version_id=204
```

说明文档见：`docs/notice-version-viewer.md`

### 6.14 Raw Document 最小查看能力（第一期）

新增最小原文查询接口：
- `GET /raw-documents`
- `GET /raw-documents/{id}`

列表筛选能力：
- `source_code`
- `document_type`
- `crawl_job_id`
- `content_hash`
- 分页：`limit / offset`
- 排序：`fetched_at desc`

列表示例：

```bash
curl "http://127.0.0.1:8000/raw-documents?source_code=anhui_ggzy_zfcg&document_type=html&crawl_job_id=1&limit=20&offset=0"
```

返回字段：
- 列表项与详情均包含 `raw_document` 摘要字段：`id/source_code/crawl_job_id/url/normalized_url/document_type/fetched_at/storage_uri/mime_type/title/content_hash`
- 若存在关联，补充 `notice_version` 与 `tender_notice` 最小摘要

详情示例：

```bash
curl "http://127.0.0.1:8000/raw-documents/401"
```

新增最小原始文档管理页：
- 列表：`/admin/raw-documents`
- 详情：`/admin/raw-documents/{id}`
- 下载：`/admin/raw-documents/{id}/download`（仅当 `storage_uri` 对应本地可访问文件时可用）

访问示例：

```bash
http://127.0.0.1:8000/admin/raw-documents
```

```bash
http://127.0.0.1:8000/admin/raw-documents/401
```

说明文档见：`docs/raw-document-viewer.md`
说明文档见：`docs/raw-document-admin.md`

### 6.15 Crawl Error 最小查询与管理（第一期）

新增最小错误查询接口：
- `GET /crawl-errors`
- `GET /crawl-errors/{id}`

列表筛选能力：
- `source_code`
- `stage`
- `crawl_job_id`
- `error_type`
- 分页：`limit / offset`
- 排序：`created_at desc`

列表返回字段：
- `id/source_code/crawl_job_id/stage/error_type/message/url/created_at`

列表示例：

```bash
curl "http://127.0.0.1:8000/crawl-errors?source_code=anhui_ggzy_zfcg&stage=parse&crawl_job_id=801&error_type=ParserError&limit=20&offset=0"
```

详情返回字段：
- `id/source_code/crawl_job_id/stage/error_type/message/detail/url/traceback/created_at`
- 若存在，补充关联 `raw_document / notice / notice_version` 摘要

详情示例：

```bash
curl "http://127.0.0.1:8000/crawl-errors/601"
```

新增最小错误管理页面：
- 列表：`/admin/crawl-errors`
- 详情：`/admin/crawl-errors/{id}`

访问示例：

```bash
http://127.0.0.1:8000/admin/crawl-errors
```

```bash
http://127.0.0.1:8000/admin/crawl-errors/601
```

说明文档见：`docs/crawl-error-admin.md`

### 6.16 Dashboard 统计总览（第一期）

新增最小统计接口：
- `GET /stats/overview`

返回能力：
- 核心计数：`source_count/active_source_count/crawl_job_count/crawl_job_running_count/notice_count/raw_document_count/crawl_error_count`
- 最近 7 天趋势：
  - `recent_7d_crawl_job_counts`
  - `recent_7d_notice_counts`
  - `recent_7d_crawl_error_counts`
- 最近摘要：
  - `recent_failed_or_partial_jobs`
  - `recent_crawl_errors`

示例：

```bash
curl "http://127.0.0.1:8000/stats/overview"
```

新增最小总览页面：
- `/admin/dashboard`

访问示例：

```bash
http://127.0.0.1:8000/admin/dashboard
```

说明文档见：`docs/dashboard.md`

## 7. 测试

```bash
pytest
```

当前包含：
- 最小健康检查接口测试 `tests/test_health.py`
- 数据模型约束测试 `tests/test_models.py`
- Crawler parser/pipeline/spider 基础测试 `tests/crawler/*.py`
- 安徽样板源 parser/spider/SQLAlchemy writer 最小测试 `tests/crawler/test_anhui_ggzy_zfcg_*.py`
- crawl_job 服务/API/管理页测试 `tests/test_crawl_job_*.py`
- source 管理 API/页面测试 `tests/test_source_*.py`
- notice 检索/详情 API 测试 `tests/test_notice_api.py`
- notice 管理页面测试 `tests/test_notice_admin_pages.py`
- raw_document 详情 API 测试 `tests/test_raw_document_api.py`
- raw_document 管理页面测试 `tests/test_raw_document_admin_pages.py`
- crawl_error 查询 API 测试 `tests/test_crawl_error_api.py`
- crawl_error 管理页面测试 `tests/test_crawl_error_admin_pages.py`
- stats overview API 测试 `tests/test_stats_api.py`
- dashboard 页面测试 `tests/test_dashboard_admin_pages.py`

### 7.1 最小 Smoke 验证清单（README 版）

1. 服务健康检查：
```bash
curl "http://127.0.0.1:8000/healthz"
```
2. 样板源抓取（入库模式）：
```bash
cd crawler
CRAWLER_WRITER_BACKEND=sqlalchemy \
CRAWLER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1 \
scrapy crawl anhui_ggzy_zfcg -a max_pages=1
```
3. 任务链路验证：
```bash
curl "http://127.0.0.1:8000/crawl-jobs?limit=5&offset=0"
```
4. 公告链路验证：
```bash
curl "http://127.0.0.1:8000/notices?limit=5&offset=0"
curl "http://127.0.0.1:8000/notices/export.csv?source_code=anhui_ggzy_zfcg"
curl "http://127.0.0.1:8000/notices/export.json?source_code=anhui_ggzy_zfcg"
```
5. 管理页面验证：访问 `/admin/dashboard`、`/admin/notices`、`/admin/raw-documents`。
