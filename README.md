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
├── docs/                   # 设计文档（含 data-model.md）
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

## 6. 测试

```bash
pytest
```

当前包含：
- 最小健康检查接口测试 `tests/test_health.py`
- 数据模型约束测试 `tests/test_models.py`
