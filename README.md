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

## 7. 测试

```bash
pytest
```

当前包含：
- 最小健康检查接口测试 `tests/test_health.py`
- 数据模型约束测试 `tests/test_models.py`
- Crawler parser/pipeline/spider 基础测试 `tests/crawler/*.py`
- 安徽样板源 parser/spider/SQLAlchemy writer 最小测试 `tests/crawler/test_anhui_ggzy_zfcg_*.py`
