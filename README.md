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

## 0.3 去重能力说明（Phase-3 第2步）

当前系统已支持“源站输入级自动去重 + 工作台聚合去重”双层机制：
- 源站输入级自动去重（采集链路）
  - 运行内列表去重：`source_list_item_fingerprint`
  - 入库侧源站重复抑制：`source_duplicate_key + content_hash`
- 工作台聚合去重（展示链路）
  - `/notices` 与 `/admin/notices` 继续按 `dedup` 参数聚合展示

边界：
- 同 `source_duplicate_key` 且正文 `content_hash` 一致：判定源站重复并抑制
- 同 `source_duplicate_key` 但正文变化：判定真实版本更新，继续保留 `notice_version` 新版本

## 0.4 Dashboard 容错与迁移依赖

- Dashboard（`/admin/home`、`/admin/dashboard`）已做空数据容错：
  - 无来源/无抓取/无重复统计时，不再 500
  - 默认降级展示 `0`、空列表或“暂无数据”
- Phase-3 第2步依赖迁移：
  - revision: `20260320_0006`
  - file: `alembic/versions/20260320_0006_add_source_dedup_and_crawl_stats.py`
  - 作用：补齐 `crawl_job.list_items_seen/list_items_unique/list_items_source_duplicates_skipped/detail_pages_fetched/records_inserted/records_updated/source_duplicates_suppressed` 以及 source duplicate key 相关字段
- Phase-3 收口版依赖迁移：
  - revision: `20260320_0007`
  - file: `alembic/versions/20260320_0007_phase3_product_closure.py`
  - 作用：新增 `source_site.official_url/list_url`、`tender_notice.dedup_key`、`notice_version.dedup_key` 并提升 `default_max_pages` 默认值
- 升级命令：

```bash
alembic upgrade head
alembic current
```

- 若出现 `/admin/home` 500 且 traceback 包含 `column crawl_job.list_items_seen does not exist`，表示数据库结构落后于代码，请先执行上述迁移再刷新页面。

## 0.5 Anhui 2026 全量回填（Phase-3 第3步）

- `anhui_ggzy_zfcg` 已支持 `backfill_year` 回填参数，按年份持续翻页抓取，不再依赖固定小页数样抓。
- 列表翻页停止条件：
  - 列表页无记录
  - 当前页全部记录发布时间早于 `backfill_year-01-01`
  - 命中可选 `max_pages` 安全兜底
  - 连续 `stop_after_consecutive_no_new_pages` 页无有效新增（默认 `5`）
- 源站重复自动双重去重：
  - 抓取阶段：同一次 job 内列表重复项不再请求详情
  - 入库阶段：优先按 `external_id/detail_url` 判重，再按 `title+publish_date+issuer+budget+region` 业务键判重
- `crawl_job` 现在会同时写入结构化上下文字段：`job_params_json/runtime_stats_json/failure_reason`；`message` 仅保留面向人的摘要文本。

## 0.6 `/admin/source-sites` 稳定性修复

- 修复了来源运营页在某些运行态下的 500：模板不再依赖 `url_path_for('admin_manual_crawl_source')` 生成表单 action，改为由后端上下文提供稳定 URL。
- `/admin/source-sites` 每条来源数据现在统一整理为稳定字典并补齐默认值（例如 `health_status/last_crawl_result/last_failure_summary/last_new_notice_count/today_ops_summary/last_retry_label/actions`），字段缺失时降级为 `-`、`0` 或 `无`。
- 模板对 `source.actions.*` 改为先取 `source.actions | default({})` 再读子字段，避免某条来源缺少 `actions` 时在渲染阶段触发 `jinja2.exceptions.UndefinedError`。
- 增加回归测试：`tests/test_source_sites_admin_resilience.py`。

## 0.7 同来源抓取互斥（Phase-3 第4步）

- 新增迁移：
  - revision: `20260322_0011`
  - file: `alembic/versions/20260322_0011_add_crawl_job_source_mutex.py`
  - 作用：为 `crawl_job` 增加“同一来源仅允许一个 `pending/running` 活跃任务”的部分唯一索引，并在迁移时自动收敛历史重复活跃任务
- 统一互斥入口：
  - `POST /sources/{code}/crawl-jobs`
  - `POST /crawl-jobs/{job_id}/retry`
  - `POST /admin/sources/{code}/manual-crawl`
  - `POST /admin/sources/{code}/crawl-jobs`
  - 调度器 `_run_scheduled_source`
- 当前行为：
  - 同来源已有 `pending/running` 任务时，API 返回 `409`
  - 后台页面会回显“已有进行中的抓取任务”，并禁用手动触发按钮防连点
  - 自动调度命中互斥时会记为 `last_schedule_status=skipped`，不再误记为失败
  - `pending` 任务现在以 durable queue 形式保留，独立 scheduler/dispatcher 会继续扫描未领取或派发租约过期的任务并重试消费
  - 已补回归测试覆盖：后台入队、pending 延迟消费/派发失败、`running` 租约超时恢复，以及双 scheduler 实例重复触发时的单来源互斥，见 `tests/test_manual_crawl_trigger.py`、`tests/test_crawl_job_service.py`、`tests/test_crawl_job_api.py`、`tests/test_source_schedule_service.py`

## 0.8 异常任务重试并发安全

- `POST /crawl-jobs/{job_id}/retry` 已将“原任务可重试校验 + retry job 创建”统一收口到 `SourceCrawlTriggerService.queue_retry_crawl_for_job()`，避免接口层先查后写带来的竞态窗口。
- 当同一原任务被重复或并发重试时，服务层会统一把唯一约束冲突转换为 `409 Conflict`，响应语义固定为 `job already retried`，不再把数据库 `IntegrityError` 透传成 `500`。
- 已补并发回归测试：`tests/test_crawl_job_api.py::test_crawl_job_retry_concurrent_requests_return_conflict_instead_of_500`，验证两个线程同时重试同一任务时，结果为一个 `201`、一个 `409`，且库内只会落一条 retry job。

## 0.9 来源创建主键并发安全

- `SourceSiteRepository.create_source()` 不再使用 `max(id)+1` 手工分配 `source_site.id`，统一改为依赖数据库主键生成，避免 PostgreSQL 并发创建来源时出现主键冲突。
- `SourceSite.id` 在 SQLite 测试环境下改为映射到原生 `INTEGER PRIMARY KEY`，这样本地测试与接口创建也能继续使用数据库自动分配 id，而不是在仓储层补号。
- 已补并发回归测试：`tests/test_source_api.py::test_create_source_concurrent_requests_get_distinct_database_ids`，验证两个并发创建请求都会成功，且最终写入的 `source_site.id` 各不相同。

## 0.10 结构化日志与告警基线

- Web、嵌入式调度器、独立调度进程、抓取 worker 已统一输出 JSON Lines 日志，便于接入 ELK / Loki / Cloud Logging 等集中日志平台。
- 默认结构化字段至少包含：`timestamp`、`level`、`logger`、`message`、`request_id`、`event`，抓取任务相关日志会补充 `source_code`、`crawl_job_id`、`job_type`、`triggered_by`。
- Web 请求会透传或自动生成 `X-Request-ID`，并在响应头回写同名 header，便于把页面操作、后台任务和服务日志串到同一链路。
- 建议在日志平台建立以下告警：
  - `event=source_scheduler_startup_skipped`
  - `event=crawl_job_dispatch_retry`
  - `event=crawl_job_dispatch_abandoned`
  - `event=crawl_worker_failed`
  - `crawl_job.status in (pending, running)` 且持续时间超过运营阈值（例如 15 分钟）
- 当前仓库只提供结构化日志字段与告警事件基线；集中日志采集、告警路由和通知升级仍需在部署环境中接入。

## 0.11 `/admin/source-sites` ViewModel 契约收口

- 来源运营页已从“自由字典 + 模板默认值兜底”收口为强类型 ViewModel：
  - 页面上下文：`SourceSitesAdminPageViewModel`
  - 行级数据：`SourceSiteAdminRow`
  - 嵌套字段：`SourceSiteAdminRowActions`、`SourceSiteAdminActiveCrawl`
- `app/api/endpoints/admin_sources.py` 现在会在渲染前统一把来源行校验/归一化为 `SourceSiteAdminRow`，模板只消费固定属性，不再直接依赖 `actions/active_crawl` 的散装字典。
- `app/templates/admin/source_sites_list.html` 已改为读取 `page.sources[*]` 和强类型嵌套属性，移除 `source.actions | default({})` 这类脆弱模板分支。
- 已补契约回归测试：`tests/test_source_sites_admin_resilience.py`
  - 验证稀疏输入会归一化为 `SourceSiteAdminRow`
  - 验证页面关键渲染字段、操作链接和状态文案按契约输出

## 0.12 `scripts/dev_up.sh` 默认重启运行中进程

- 重新执行 `bash scripts/dev_up.sh` 时，如果检测到本项目的 Web 或独立 scheduler 已在运行，脚本现在会默认先停再启，确保最新模板、路由和配置一定被重新加载。
- 这可以避免“代码已经修复，但浏览器仍命中旧进程”的问题；`/admin/source-sites` 这类后台页面不再因为复用陈旧进程而持续看到历史 500。
- 如需保留旧行为并复用现有进程，可显式执行：

```bash
DEV_UP_REUSE_RUNNING=1 bash scripts/dev_up.sh
```

## 0. 交付文档索引

- 演示与接手 Runbook：`docs/runbook.md`
- Phase-2 演示闭环手册：`docs/demo-runbook.md`
- Phase-1 验收清单：`docs/acceptance-checklist.md`
- Phase-2 产品化计划：`docs/product-phase2-plan.md`
- 来源自动调度说明：`docs/source-schedule.md`
- 来源健康度与异常闭环：`docs/source-health.md`
- 健康度阈值配置：`docs/health-rule-config.md`
- 异常任务重试与运营日报：`docs/retry-and-ops-report.md`
- 新增公告提示说明：`docs/new-notice-indicator.md`
- 公告工作台说明：`docs/notice-workbench.md`
- 后台导航闭环说明：`docs/admin-navigation.md`
- 来源手动新增说明：`docs/source-manual-create.md`
- 源站重复抑制与业务去重边界：`docs/source-dedup-strategy.md`
- 已接入来源：
  - `docs/source-anhui-ggzy-zfcg.md`
  - `docs/source-ggzy-gov-cn.md`
- 占位来源：
  - `docs/source-ccgp-gov-cn.md`
  - `docs/source-ccgp-hubei.md`
  - `docs/source-ccgp-jiangsu.md`
- 数据模型：`docs/data-model.md`
- Crawler 架构：`docs/crawler-architecture.md`

## 0.1 快速演示路径（5-10 分钟）

1. 一键启动：`bash scripts/dev_up.sh`
2. 健康检查：
   - 存活检查：`curl "http://127.0.0.1:8000/healthz"`
   - 就绪检查：`curl "http://127.0.0.1:8000/readyz"`
3. 运行样板源抓取（入库，建议先抓 3 页验证翻页）：`python scripts/run_crawl_job.py --spider anhui_ggzy_zfcg --source-code anhui_ggzy_zfcg --job-type manual --writer-backend sqlalchemy --spider-arg max_pages=3`
4. 演示主入口：`/admin/notices`
5. 演示来源运营：`/admin/source-sites`
6. 演示公告导出：`/notices/export.csv`、`/notices/export.json`、`/notices/export.xlsx`
7. 演示异常重试与运营日报：`POST /crawl-jobs/{job_id}/retry`、`/reports/source-ops.xlsx`
8. 演示原始文档/错误/总览：`/admin/raw-documents`、`/admin/crawl-errors`、`/admin/dashboard`

## 0.2 Phase-1 功能地图

- 来源管理与触发抓取：
  - API：`/sources`（含 `POST /sources`）、`/sources/{code}`、`/sources/{code}/schedule`、`/sources/{code}/health`、`/sources/{code}/crawl-jobs`、`/settings/health-rules`
  - 页面：`/admin/source-sites`、`/admin/sources`、`/admin/sources/new`
  - 文档：`docs/source-admin.md`、`docs/source-manual-create.md`、`docs/source-config.md`、`docs/source-schedule.md`、`docs/source-health.md`、`docs/health-rule-config.md`
- 抓取任务与状态追踪：
  - API：`/crawl-jobs`、`/crawl-jobs/{job_id}/retry`
  - 页面：`/admin/crawl-jobs`
  - 文档：`docs/crawl-job.md`、`docs/crawl-job-api.md`、`docs/crawl-job-admin.md`、`docs/retry-and-ops-report.md`
- 公告检索/详情/导出：
  - API：`/notices`（支持 `dedup/sort_by/sort_order/date_from/date_to`）、`/notices/{id}`、`/notices/export.csv`、`/notices/export.json`、`/notices/export.xlsx`
  - 页面：`/admin/notices`
  - 文档：`docs/notice-api.md`、`docs/notice-export.md`、`docs/notice-admin.md`、`docs/notice-workbench.md`
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
- 来源运营日报导出：
  - API：`/reports/source-ops.xlsx`
  - 页面入口：`/admin/source-sites`、`/admin/sources/{code}`
  - 文档：`docs/retry-and-ops-report.md`

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

## 1.1 认证与权限边界

- 后台与运营写接口已默认启用 HTTP Basic 认证；真实生效的登录凭据来源是 `AUTH_BASIC_USERS_JSON`，未配置账号时受保护接口会返回 `401`。
- `docker-compose.yml` 与 `.env.example` 的本地开发示例默认提供以下账号：
  - `viewer_user / change-me-viewer`
  - `ops_user / change-me-ops`
  - `admin_user / change-me-admin`
- 通过 `.env` 或运行环境注入 `AUTH_BASIC_USERS_JSON`，格式必须是 JSON 数组，例如：

```json
[
  {"username": "viewer_user", "password": "change-me-viewer", "role": "viewer"},
  {"username": "ops_user", "password": "change-me-ops", "role": "ops"},
  {"username": "admin_user", "password": "change-me-admin", "role": "admin"}
]
```

- 角色边界：
  - `viewer`：可访问只读后台页面（如 `/admin/dashboard`、`/admin/notices`、`/admin/raw-documents`、`/admin/crawl-jobs`）。
  - `ops`：继承 `viewer`，可访问 `/admin/source-sites`、触发抓取、重试失败任务、导出运营日报。
  - `admin`：继承 `ops`，可新增来源、修改来源配置、修改调度配置、维护健康规则。
- `ADMIN_AUTH_SECRET` 不参与 HTTP Basic 账号匹配；它只用于为后台页面签发/校验 `admin_csrf_token` 的签名，保护已登录管理员的 `/admin/*` 写操作不被伪造请求利用。
- 后台写操作现在统一启用 CSRF 防护：
  - 服务端会为后台页面签发 `admin_csrf_token` Cookie，并在后台写表单中注入隐藏字段 `csrf_token`。
  - 所有 `/admin/*` 写操作都会同时校验 Cookie 与表单 token；缺失、错误或过期时返回 `403` 中文错误页，不会直接抛 `500`。
  - 失败日志会记录 `event=csrf_validation_failed`，便于排查被拦截的提交。
- 当前已收口的受保护入口：
  - 后台页面：`/admin/*`
  - 运营报表：`/reports/source-ops.xlsx`
  - 配置接口：`POST /sources`、`PATCH /sources/{code}`、`PATCH /sources/{code}/schedule`、`/settings/health-rules`
  - 运维写接口：`POST /sources/{code}/crawl-jobs`、`POST /crawl-jobs/{job_id}/retry`
- 公开查询接口仍保持开放，例如：`/healthz`、`/readyz`、`/sources`、`/sources/{code}`、`/sources/{code}/health`、`/notices`、`/raw-documents`。

## 1.2 运行时配置约束

- `docker-compose.yml` 现在只用于开发联调，保留本地 `postgres` 与开发默认值。
- 生产部署请改用 `docker-compose.prod.example.yml` 作为模板，不要直接复用开发 Compose。
- `APP_ENV=prod` / `APP_ENV=production` 时，应用会在导入/启动阶段强制校验以下变量是否显式提供：
  - `APP_ENV`
  - `DATABASE_URL`
  - `ADMIN_AUTH_SECRET`
  - `LOG_LEVEL`
- 生产环境若缺少上述任一变量，进程会直接拒绝启动。
- `AUTH_BASIC_USERS_JSON` 不是所有进程共享的全局强制项，但 Web 后台真实登录就依赖它；生产 `app` 服务若不注入该变量，`/admin/*` 与其他受保护入口会持续返回 `401`。
- 生产环境若 `DATABASE_URL` 仍等于默认开发库 `postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1`，进程也会直接拒绝启动，避免误连本地/默认口令数据库。
- `LOG_LEVEL` 支持：`DEBUG`、`INFO`、`WARNING`、`ERROR`、`CRITICAL`（兼容 `WARN`/`FATAL` 别名）。
- `.env.example` 仅作为开发示例，不可直接当作生产配置文件使用。

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
├── docker-compose.prod.example.yml
├── .env.example
└── pyproject.toml
```

## 2.1 开发与测试环境安装

本仓库默认使用 Python `3.12` 虚拟环境；如果你的机器没有 `python` 命令，请统一使用 `python3`。

开发环境安装（本地联调、跑服务、跑测试统一推荐）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[dev]
python scripts/check_env.py --profile dev
```

最小测试环境安装（仅跑测试时可选）：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .[test]
python scripts/check_env.py --profile test
```

仅运行服务 / 迁移 / 数据库脚本：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
python scripts/check_env.py --profile runtime
```

补充说明：
- CI 请固定执行 `python -m pip install -e .[dev]`，不要只安装基础依赖，否则 `fastapi.testclient.TestClient` 相关测试会因缺少 `httpx` 在 collection 阶段直接失败。
- 如果需要启用 Playwright 的 JS 渲染能力，除 Python 包外还需安装浏览器二进制：

```bash
python -m playwright install chromium
```

- 后台真实浏览器 E2E（`tests/test_admin_e2e_playwright.py`）同样依赖上述 Chromium；测试会自行拉起临时 FastAPI + SQLite，不依赖你手动先跑 `uvicorn`。

## 3. 本地一键启动

### 3.1 Linux / WSL

启动：

```bash
bash scripts/dev_up.sh
```

停止：

```bash
bash scripts/dev_down.sh
```

`dev_up.sh` 会自动完成：
1. 自动切换到项目根目录并激活 `.venv`
2. 启动 `postgres`：`docker compose up -d postgres`
3. 等待 `postgres` healthy 可用
4. 执行迁移：`alembic upgrade head`
5. 检查并处理 `8000` 端口占用（避免重复启动本项目 uvicorn）
6. 后台启动 Web：`uvicorn app.main:app --host 0.0.0.0 --port 8000`
7. 后台启动独立调度进程：`python -m app.run_source_scheduler`
8. Web / Scheduler 日志分别写入：`logs/dev_web.log`、`logs/dev_scheduler.log`，且为 JSON Lines 结构化日志
9. 打印访问地址，并在检测到 `xdg-open` 时自动打开浏览器

访问入口：
- Web 地址：`http://127.0.0.1:8000/admin/home`
- Docs 地址：`http://127.0.0.1:8000/docs`
- 健康探针：
  - `/healthz`：轻量 liveness，仅用于确认 Web 进程仍在存活
  - `/readyz`：readiness，会检查数据库连通性、关键表可查询，以及 Alembic revision 是否已到代码 head；容器 healthcheck 与流量接入应使用该接口

### 3.2 Windows

可直接双击以下脚本：
- `scripts/dev_up.bat`
- `scripts/dev_down.bat`

### 3.3 手动命令（高级排障用）

如果需要逐步排查启动问题，可使用手动命令：

```bash
cd /path/to/tender-phase1
source .venv/bin/activate
docker compose up -d postgres
alembic upgrade head
APP_ENV=dev python scripts/seed_sources.py --demo  # 仅演示环境需要
```

生产部署约束：
- 不要直接使用仓库内的 `docker-compose.yml`。
- 请从 `docker-compose.prod.example.yml` 复制出自己的生产编排文件，并显式注入 `APP_ENV/DATABASE_URL/ADMIN_AUTH_SECRET/LOG_LEVEL`；其中 `app` 服务还需要额外注入 `AUTH_BASIC_USERS_JSON` 作为后台 Basic 认证账号来源。
- 若缺少关键变量，或 `DATABASE_URL` 仍是默认开发库地址，应用会直接拒绝启动。

终端 1 启动 Web：

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

终端 2 启动独立 scheduler：

```bash
python -m app.run_source_scheduler
```

手动停止示例：

```bash
bash scripts/dev_down.sh --keep-postgres
docker compose stop postgres
```

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

### 5.1 容器启动职责边界

- `scripts/app_entrypoint.sh`：只负责等待数据库并启动 `uvicorn`，不会自动执行迁移，也不会写入 demo 数据。
- `scripts/migrate_entrypoint.sh`：一次性迁移入口，适合部署时作为 `migration job` 单独执行。
- `scripts/seed_demo_entrypoint.sh`：一次性 demo 来源初始化入口，只应用于演示/开发环境。
- `python scripts/seed_sources.py --demo` 现在要求显式设置 `APP_ENV=dev/local/test/demo`；未设置或为 `prod/production` 时会直接拒绝执行。
- 生产运行态必须显式提供 `APP_ENV`、`DATABASE_URL`、`ADMIN_AUTH_SECRET`、`LOG_LEVEL`；缺失任一项时，Web / scheduler / worker 进程都会在启动前失败退出。
- `AUTH_BASIC_USERS_JSON` 的真实用途是 Web 后台 HTTP Basic 认证；`docker-compose.prod.example.yml` 已要求仅对 `app` 服务显式注入该变量，避免把“后台登录账号”误写成所有运行进程的统一强制项。
- `docker-compose.yml` 仅保留开发默认值；生产请使用 `docker-compose.prod.example.yml` 模板并接入外部 PostgreSQL。
- Web 容器健康检查应探测 `/readyz`，不要再用 `/healthz` 代替真实可接流状态；`/healthz` 仅保留为轻量存活探针。
- 因为 `/readyz` 会校验 Alembic head，若数据库尚未执行 `alembic upgrade head`，`app` 容器会持续显示 `unhealthy`；这属于真实未就绪，而不是探针误报。
- 生产部署建议按职责拆分为：`migration job` -> `app runtime` -> `scheduler runtime`（`python -m app.run_source_scheduler`，同时负责 schedule refresh + pending dispatcher）-> `worker subprocess/runtime`，避免 Web 容器启动即改库或污染真实数据。

## 6. Scrapy 采集启动

先查看可用 spider：

```bash
cd crawler
scrapy list
```

### 6.0 初始化真实样板来源（Phase-2 第8步）

推荐先执行来源初始化脚本，确保产品页非空态且可直接演示：

```bash
APP_ENV=dev python scripts/seed_sources.py --demo
```

脚本行为：
- 初始化（或更新）`source_site.code=anhui_ggzy_zfcg`
- 初始化（或更新）`source_site.code=ggzy_gov_cn_deal`
- 写入默认官网 URL、启用状态、自动调度配置、`default_max_pages`
- 幂等可重复执行，已有来源不会重复插入
- 仅允许在显式非生产环境执行；生产环境请不要运行 demo seed

### 6.1 运行真实样板源（安徽省公共资源交易监管网-政府采购）

最小抓取（1 页，默认写入本地 `jsonl`）：

```bash
cd crawler
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
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
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
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
- 源站重复抑制：`source_duplicate_key` 命中且 `content_hash` 一致时抑制重复输入
- 列表运行内去重：`source_list_item_fingerprint` 在单次 crawl run 内跳过重复列表项
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
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
```

### 6.5 抓取任务管理与调度基础（第一期）

第一期提供最小 `crawl_job` 工作流：
- `job_type`：`manual / scheduled / backfill`
- `status`：`pending / running / succeeded / failed / partial`
- 队列/租约字段：`queued_at / picked_at / heartbeat_at / timeout_at`
- 兼容字段：`lease_expires_at`（与 `timeout_at` 同步回写，便于旧页面/旧查询兼容）
- 统计字段：`pages_fetched / documents_saved / notices_upserted / deduplicated_count / error_count`
- 采集质量字段：`list_items_seen / list_items_unique / list_items_source_duplicates_skipped / detail_pages_fetched / records_inserted / records_updated / source_duplicates_suppressed`
- 独立抓取日志：`logs/crawl_jobs/crawl_job_{job_id}.log`

使用 CLI 手动触发（会自动创建 job、注入 `crawl_job_id`、结束后回写状态）：

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=3
```

2026 回填任务示例（推荐用于 `anhui_ggzy_zfcg`）：

```bash
python scripts/run_crawl_job.py \
  --spider anhui_ggzy_zfcg \
  --source-code anhui_ggzy_zfcg \
  --job-type backfill \
  --writer-backend sqlalchemy \
  --spider-arg backfill_year=2026 \
  --spider-arg max_pages=10000
```

全国公共资源交易平台（政府采购）手动抓取示例：

```bash
python scripts/run_crawl_job.py \
  --spider ggzy_gov_cn_deal \
  --source-code ggzy_gov_cn_deal \
  --job-type manual \
  --writer-backend sqlalchemy \
  --spider-arg max_pages=5
```

常见可选参数：
- `--spider-arg KEY=VALUE`：透传给 spider（可重复）
- `--setting KEY=VALUE`：透传给 Scrapy `-s`
- `--database-url <url>`：覆盖数据库连接
- `--fail-on-partial`：当状态为 `partial` 时返回非 0 退出码

说明：
- spider 外部运行方式不变，仍可直接 `scrapy crawl ...`
- 若要记录 `crawl_job` 统计，请使用 `crawl_job_id` 并开启 `sqlalchemy` writer
- 任务创建/运行/完成/失败时会把上下文稳定写入 `crawl_job.job_params_json`、`crawl_job.runtime_stats_json`、`crawl_job.failure_reason`
- `crawl_job.message` 仅保留人类可读摘要；后台详情页、失败摘要与 retry 参数继承都改为读取结构化字段，不再依赖字符串切分
- `pending -> running` 的 worker 启动改为数据库原子领取：单条条件 `UPDATE` 只允许一个 worker 成功把同一 `crawl_job_id` 切到 `running`
- 重复启动同一 `crawl_job_id` 时，后续 worker 会在真正执行 spider 前直接退出，不会出现两个 worker 同时跑同一任务
- `running -> running` 不再视为合法“重复启动”；若 `running` 任务租约超时，会先由过期收敛逻辑标记为 `failed`，再走人工重试/新任务恢复
- 允许被重新领取的只有 `pending` 任务：首次未领取，或 dispatcher 启动租约超时后的 `pending` 任务；`running` 任务不直接接管
- `running` 任务在心跳租约过期后会被查询/API/统计入口自动收敛为 `failed`
- `pending` 任务不会再因为“尚未被 dispatcher 领取”而自动失败；只有派发重试耗尽时才会显式进入 `failed`

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
- 支持业务化异常筛选：`仅看异常 / 仅看今日失败 / 仅看 partial`
- 支持分页（`limit / offset`）
- 详情页展示 `recent_crawl_error_count` 与原始 JSON 调试区
- 异常任务支持单次人工重试（`failed/partial`）
- 列表/详情页展示“是否已重试、重试任务链接、重试结果”

异常任务重试 API 示例：

```bash
curl -X POST "http://127.0.0.1:8000/crawl-jobs/102/retry" \
  -H "Content-Type: application/json" \
  -d '{"triggered_by":"api-retry"}'
```

说明文档见：`docs/crawl-job-admin.md`

### 6.8 Source 管理/配置与手动触发 API（第一期）

新增最小来源管理接口：
- `GET /sources`
- `GET /sources/{code}`
- `PATCH /sources/{code}`
- `GET /sources/{code}/schedule`
- `PATCH /sources/{code}/schedule`
- `GET /sources/{code}/health`
- `POST /sources/{code}/crawl-jobs`
- `GET /settings/health-rules`
- `PATCH /settings/health-rules`

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

```bash
curl "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg/schedule"
```

```bash
curl -X PATCH "http://127.0.0.1:8000/sources/anhui_ggzy_zfcg/schedule" \
  -H "Content-Type: application/json" \
  -d '{"schedule_enabled": true, "schedule_days": 2}'
```

```bash
curl "http://127.0.0.1:8000/settings/health-rules"
```

```bash
curl -X PATCH "http://127.0.0.1:8000/settings/health-rules" \
  -H "Content-Type: application/json" \
  -d '{"recent_error_warning_threshold": 2, "recent_error_critical_threshold": 5, "consecutive_failure_warning_threshold": 1, "consecutive_failure_critical_threshold": 2, "partial_warning_enabled": true}'
```

说明：
- `PATCH` 可更新来源最小运行配置：
  - `is_active`
  - `crawl_interval_minutes`
  - `supports_js_render`
  - `default_max_pages`
- `POST` 会创建 `manual` 类型 `crawl_job`
- API 请求只负责创建任务并返回 `job_id`
- 实际 spider 运行由独立子进程异步接管，不再阻塞 HTTP worker
- 支持最小 spider 参数：`max_pages`
- 返回创建后的任务摘要（含 `queued_at / picked_at / heartbeat_at / timeout_at`）
- 同来源若已存在 `pending/running` 任务，会直接返回 `409`，避免重复派发同一来源
- 前端/API 调用方应通过 `GET /crawl-jobs/{id}` 或后台详情页轮询任务状态
- 自动调度配置支持固定周期：`1/2/3/7` 天
- 可通过 `GET /sources/{code}/schedule` 查看下次计划抓取时间与最近调度结果
- 可通过 `GET /sources/{code}/health` 查看来源运行健康摘要（Phase-2 Step-5）
- 可通过 `GET/PATCH /settings/health-rules` 查看并修改健康度阈值（Phase-2 Step-7）

### 6.9 Source 管理页面（第一期）

新增最小来源管理页面：
- 来源列表：`/admin/sources`
- 来源详情：`/admin/sources/{code}`
- 来源运营列表：`/admin/source-sites`
- 新增来源表单：`/admin/sources/new`

能力：
- 查看来源基础信息（`code/name/base_url/is_active/supports_js_render/crawl_interval_minutes/default_max_pages`）
- 在详情页编辑来源配置（`is_active/supports_js_render/crawl_interval_minutes/default_max_pages`）
- 在详情页配置自动抓取（开关 + 周期：1/2/3/7 天）
- 可查看调度摘要（下次抓取时间、上次计划抓取时间、最近调度结果）
- 在来源详情页通过表单触发一次抓取（`max_pages`）
- 配置保存后回到当前来源详情页（显示最新值）
- 手动抓取提交后跳转到 `/admin/crawl-jobs?source_code={code}&created_job_id={job_id}`
- 来源运营列表支持“新增来源网站”入口
- 新增来源提交成功后返回来源运营列表并显示“新增成功”

来源网站运营页（Phase-2）：
- `/admin/source-sites`
- 健康规则配置页：`/admin/settings/health-rules`

新增来源 API：
- `POST /sources`

说明文档见：`docs/source-admin.md`、`docs/source-manual-create.md`、`docs/source-config.md`、`docs/source-schedule.md`、`docs/source-health.md`

### 6.9.1 自动抓取配置使用说明（Phase-2 第2步）

开启自动抓取（网页）：
1. 访问 `/admin/source-sites` 或 `/admin/sources/{code}`
2. 在来源详情页“自动抓取配置”中将开关设为启用
3. 选择周期：`1天一次 / 2天一次 / 3天一次 / 7天一次`
4. 保存后页面会提示“配置已更新”

查看下次抓取时间：
- 来源详情页：`/admin/sources/{code}` 查看 `next_scheduled_run_at`
- API：`GET /sources/{code}/schedule`

运行方式与限制：
- Web 进程默认**不再内嵌** APScheduler，避免多 `uvicorn worker` / 多容器 / 多副本重复恢复并注册同一批来源调度
- 自动调度应通过独立进程或容器启动：`python -m app.run_source_scheduler`，`docker-compose.yml` 已提供 `scheduler` 服务
- 独立 scheduler 会每 `SOURCE_SCHEDULER_REFRESH_INTERVAL_SECONDS` 秒（默认 `30`）从数据库刷新来源调度配置，并清理已删除来源的陈旧 job
- 同一个独立 scheduler 也会每 `CRAWL_JOB_DISPATCH_INTERVAL_SECONDS` 秒（默认 `5`）扫描 `pending` 抓取任务，并派发 `worker` 子进程执行
- 如需本地临时启用嵌入式模式，可设置 `SOURCE_SCHEDULER_EMBEDDED_ENABLED=true`
- 即使误部署多个 scheduler 副本，数据库层的来源活跃任务唯一索引也会把同来源重复触发收敛为“1 个执行 + 其余 skipped/冲突返回”；这能防止重复执行，但不是 leader election 的替代方案
- 当前仍为单个 APScheduler 实例，不包含 Celery/Redis/RabbitMQ；若部署多个 `scheduler` 副本，仍需要额外的 leader election 或分布式锁方案

### 6.9.2 来源健康度与异常闭环（Phase-2 第5步）

来源运营页 `/admin/source-sites` 增强：
- 健康度分级：正常 / 警告 / 异常
- 展示最近抓取结果、最近失败原因摘要
- 快速入口：手动抓取 / 查看任务 / 查看错误 / 配置

来源详情页 `/admin/sources/{code}` 增强：
- 新增“运行健康摘要”模块（最近抓取状态、最近7天统计、最近失败原因）
- 顶部提供“立即手动抓取”入口（`POST /admin/sources/{code}/manual-crawl`）

从后台手动抓取（全新 manual 任务，不复用 retry）：
1. 打开 `/admin/source-sites`
2. 点击目标来源的“手动抓取”（页面使用 `POST /admin/sources/{code}/manual-crawl` 表单提交，不走 `<a href>` 直链；后台会同步校验 CSRF token）
3. 系统创建 `job_type=manual` 且 `triggered_by=admin_ui` 的新任务
4. 自动跳转到 `/admin/crawl-jobs?source_code={code}&created_job_id={job_id}`，任务看板会显示新建任务编号
5. 若任务创建失败，来源运营页会直接回显错误，不再静默跳转
6. Web 进程只负责把任务 durable enqueue 到 `crawl_job(status=pending)`，不再依赖请求生命周期内的 `BackgroundTasks`
7. 独立 scheduler/dispatcher 会扫描未领取的 `pending` 任务并派发 `worker`；派发时补齐 `picked_at / timeout_at`，worker 真正开始执行时再写入 `started_at`
   同一 `crawl_job_id` 的 `pending -> running` 领取使用数据库原子条件更新，重复启动的后续 worker 会直接跳过
8. 若 Web 在返回 `303` 后退出，只要数据库中的 `pending` 任务仍在，后续 dispatcher 仍可继续消费
9. 若 dispatcher 派发失败，会记录 `crawl_job_dispatch_retry / crawl_job_dispatch_abandoned` 日志；重试耗尽后任务会显式落为 `failed`
10. `/admin/crawl-jobs`、`/admin/crawl-jobs/{id}`、`/admin/source-sites` 在存在活跃任务时会自动刷新，并实时显示当前抓取阶段与累计统计（列表页、详情页、公告、归档、错误）
11. `running` 任务在心跳租约过期后会被页面、查询 API、来源健康摘要和统计总览自动收敛为 `failed`；`pending` 任务则保留为可恢复消费状态，直到派发放弃
12. 同一个 `crawl_job_id` 不支持 `running -> running` 直接接管；若执行进程超时，先收敛为 `failed`，再由人工重试或新任务继续，避免两个 worker 并行执行同一任务
13. 当抓取过程中已记录 `fetch` 错误且列表未成功取回时，任务会按 `failed` 落库，不再误显示为 `succeeded`
14. 同一来源若已有 `pending/running` 任务，后台会直接提示“已有进行中的抓取任务”，不会再重复创建新任务
15. `/admin/source-sites` 与 `/admin/sources/{code}` 的手动抓取按钮会在活跃任务存在时禁用，并在提交瞬间进入防连点状态

健康辅助 API：
- `GET /sources/{code}/health`

说明文档见：`docs/source-health.md`

### 6.9.3 异常任务重试与来源运营日报（Phase-2 第6步）

手动重试异常任务：
1. 访问 `/admin/crawl-jobs`
2. 对 `failed/partial` 且未重试任务点击“重试”（后台会校验当前页面下发的 CSRF token）
3. 页面会显示“重试任务已创建”，并可跳转新任务详情
4. 重试入口只负责创建 `manual_retry` 任务；实际抓取由独立 worker 子进程执行
5. 后台详情页与任务看板会自动轮询，直到任务从 `pending/running` 收敛为最终状态
6. 单次任务日志写入 `logs/crawl_jobs/crawl_job_{job_id}.log`，与 Web 请求日志解耦

导出来源运营日报：
- 列表页入口：`/admin/source-sites` 顶部“导出运营日报”
- 来源详情页入口：`/admin/sources/{code}` 顶部“导出运营日报”
- API：

```bash
curl -L "http://127.0.0.1:8000/reports/source-ops.xlsx?recent_hours=24" -o source-ops-report.xlsx
```

```bash
curl -L "http://127.0.0.1:8000/reports/source-ops.xlsx?recent_hours=24&source_code=anhui_ggzy_zfcg" -o source-ops-report-anhui.xlsx
```

已知限制：
- 当前仅支持单次人工重试（不包含复杂自动重试策略）
- 调度仍为单进程本地实现（非分布式）

### 6.9.4 健康度阈值可配置（Phase-2 第7步）

配置入口：
- 页面：`/admin/settings/health-rules`
- API：`GET /settings/health-rules`、`PATCH /settings/health-rules`

默认阈值：
- `recent_error_warning_threshold = 3`
- `recent_error_critical_threshold = 6`
- `consecutive_failure_warning_threshold = 1`
- `consecutive_failure_critical_threshold = 1`
- `partial_warning_enabled = true`

说明：
- 修改阈值后，`/admin/source-sites`、`/admin/sources/{code}`、`/sources/{code}/health` 会立即按新规则重新计算显示，无需手工改来源数据。
- `/admin/settings/health-rules` 的保存动作同样要求有效 CSRF token，防止已登录管理员被跨站页面伪造提交。
- 技术上应用初始化已迁移到 FastAPI `lifespan`，统一管理调度器启动/关闭。

### 6.10 Notice 检索与详情 API（第一期）

新增最小公告查询接口：
- `GET /notices`
- `GET /notices/{id}`
- `GET /notices/export.csv`
- `GET /notices/export.json`
- `GET /notices/export.xlsx`

列表能力：
- 关键词搜索：`keyword`（匹配 `title / issuer / region`）
- 筛选：`source_code / notice_type / region`
- 最近新增筛选：`recent_hours`（推荐值：`24`）
- 日期筛选：`date_from / date_to`
- 去重开关：`dedup`（默认 `true`）
- 排序：`sort_by=published_at|deadline_at|budget_amount|source_name` + `sort_order=asc|desc`
- 分页：`limit / offset`

列表示例：

```bash
curl "http://127.0.0.1:8000/notices?keyword=低压&source_code=anhui_ggzy_zfcg&notice_type=announcement&dedup=true&sort_by=published_at&sort_order=desc&limit=20&offset=0"
```

```bash
curl "http://127.0.0.1:8000/notices?recent_hours=24&limit=20&offset=0"
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

```bash
curl "http://127.0.0.1:8000/notices/export.csv?recent_hours=24"
curl "http://127.0.0.1:8000/notices/export.json?recent_hours=24"
curl -L "http://127.0.0.1:8000/notices/export.xlsx?recent_hours=24" -o notices.xlsx
```

详情返回：
- `tender_notice` 主要字段
- 当前 `notice_version` 主要字段
- `versions` 历史版本列表（含 `raw_document` 摘要）
- 附件摘要列表
- 来源基础信息

说明文档见：`docs/notice-api.md`、`docs/notice-export.md`

### 6.11 Notice 管理页面（第一期）

新增公告管理工作台页面：
- 列表：`/admin/notices`
- 详情：`/admin/notices/{id}`

页面能力：
- 默认按业务去重展示（`dedup=true`，按 `dedup_hash` 或稳定回退键聚合）
- 业务汇总表展示 `标题/来源/来源名称/公告类型/地区/发布日期/截止日期/预算金额/最近新增/版本重复数`
- 支持 `keyword / source_code / notice_type / region / recent_hours / date_from / date_to / dedup` 筛选
- 支持“最近新增（24小时）”快捷筛选（`recent_hours=24`）
- 支持排序：`published_at / deadline_at / budget_amount / source_name`（`asc/desc`）
- 支持纵向滚动浏览（sticky 表头）
- 支持 `limit / offset` 分页
- 支持导出 CSV/JSON/Excel（继承当前筛选 + 去重 + 排序条件）
- 页面顶部显示 `今日新增` 与 `最近24小时新增`，无新增时提示“暂无新增”
- 每行支持“查看版本/重复项”入口
- 详情展示公告主字段、版本/重复记录、当前版本、历史版本、附件列表、来源信息与原始 JSON 调试区
- 版本区中的 `raw_document` 摘要可跳转到原始文档详情页

访问示例：

```bash
http://127.0.0.1:8000/admin/notices
```

说明文档见：`docs/notice-admin.md`、`docs/new-notice-indicator.md`、`docs/notice-workbench.md`、`docs/admin-navigation.md`

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

页面增强（Phase-2 Step-5）：
- 列表页新增“最近失败原因（按来源聚合，近7天）”摘要视图
- 可直接从摘要跳转最近错误详情
- 新增最近重试结果摘要与重试任务跳转（Phase-2 Step-6）

访问示例：

```bash
http://127.0.0.1:8000/admin/crawl-errors
```

```bash
http://127.0.0.1:8000/admin/crawl-errors/601
```

说明文档见：`docs/crawl-error-admin.md`、`docs/retry-and-ops-report.md`

### 6.16 Dashboard 统计总览（第一期）

新增最小统计接口：
- `GET /stats/overview`

返回能力：
- 核心计数：`source_count/active_source_count/crawl_job_count/crawl_job_running_count/notice_count/today_new_notice_count/recent_24h_new_notice_count/raw_document_count/crawl_error_count`
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
- `/admin/home`（Phase-2 Step-1 产品化首页入口）
- `/admin/source-sites`（Phase-2 Step-1 来源网站运营列表）

访问示例：

```bash
http://127.0.0.1:8000/admin/dashboard
```

```bash
http://127.0.0.1:8000/admin/home
```

```bash
http://127.0.0.1:8000/admin/source-sites
```

说明文档见：`docs/dashboard.md`、`docs/product-phase2-plan.md`、`docs/new-notice-indicator.md`

## 7. 测试

```bash
source .venv/bin/activate
python scripts/check_env.py --profile test
pytest
```

当前包含：
- 健康检查接口测试（liveness/readiness）`tests/test_health.py`
- 数据模型约束测试 `tests/test_models.py`
- Alembic 真实迁移 smoke / 数据修复测试 `tests/test_alembic_migrations.py`
  - 覆盖空库 `alembic upgrade head`
  - 覆盖 `20260322_0009_add_crawl_job_leases.py`
  - 覆盖 `20260322_0010_add_crawl_job_queue_timestamps.py`
  - 覆盖 `20260322_0011_add_crawl_job_source_mutex.py` 以及历史重复活跃任务收敛逻辑
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
- 来源运营日报导出 API 测试 `tests/test_reports_api.py`
- 健康规则配置 API/页面/服务测试 `tests/test_settings_api.py`、`tests/test_health_rule_admin_pages.py`、`tests/test_health_rule_service.py`
- lifespan 启停测试 `tests/test_app_lifespan.py`
- 演示来源初始化与闭环 smoke 测试 `tests/test_demo_bootstrap.py`
- dashboard 页面测试 `tests/test_dashboard_admin_pages.py`
- 后台真实浏览器 E2E 测试 `tests/test_admin_e2e_playwright.py`
  - `/admin/source-sites` 点击“手动抓取”后的按钮禁用、页面跳转与任务状态自动刷新
  - `/admin/sources/{code}` 修改自动抓取配置后的回跳与持久化结果
  - `/admin/crawl-jobs` 点击“重试”后的按钮禁用、重试任务创建与列表状态联动
  - `/admin/source-sites` 对停用来源回显手动抓取错误提示

### 7.1 测试依赖与运行约束

- 开发机统一推荐：`python -m pip install -e .[dev]`
- 仅测试环境可使用：`python -m pip install -e .[test]`
- CI 必须固定安装：`python -m pip install -e .[dev]`
- 执行 pytest 前先跑：`python scripts/check_env.py --profile test`
- 若要单独执行后台 E2E，可使用：

```bash
source .venv/bin/activate
python -m playwright install chromium
pytest tests/test_admin_e2e_playwright.py -q
```

- `tests/test_alembic_migrations.py` 默认使用临时 SQLite 数据库执行真实 Alembic 升级链；这样即使本机没起 PostgreSQL，也能在 CI 里尽早发现迁移脚本断裂或数据修复逻辑回归。
- 若要补跑 PostgreSQL 迁移路径，先启动本地开发库后执行：

```bash
docker compose up -d postgres
TEST_POSTGRESQL_ADMIN_URL=postgresql+psycopg://postgres:postgres@localhost:5432/postgres \
pytest tests/test_alembic_migrations.py -q
```

- 上述 PostgreSQL 路径会为每个测试创建并销毁临时数据库，不会复用 `tender_phase1` 主开发库。
- 若要验证抓取链路或 JS 渲染来源，额外确认：
  - `scrapy` 已随基础依赖安装
  - `playwright` Python 包已安装
  - 浏览器二进制已执行 `python -m playwright install chromium`

### 7.2 最小 Smoke 验证清单（README 版）

1. 服务健康检查：
```bash
curl "http://127.0.0.1:8000/healthz"
curl "http://127.0.0.1:8000/readyz"
```
2. 样板源抓取（入库模式）：
```bash
cd crawler
CRAWLER_WRITER_BACKEND=sqlalchemy \
CRAWLER_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/tender_phase1 \
scrapy crawl anhui_ggzy_zfcg -a max_pages=3
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
curl -L "http://127.0.0.1:8000/notices/export.xlsx?source_code=anhui_ggzy_zfcg" -o notices.xlsx
```
5. 管理页面验证：访问 `/admin/dashboard`、`/admin/notices`、`/admin/raw-documents`。
