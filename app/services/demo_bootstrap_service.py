from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SourceSite
from app.services.source_schedule_service import calculate_next_scheduled_run


@dataclass(slots=True)
class DemoSourceSeed:
    code: str
    name: str
    base_url: str
    official_url: str
    list_url: str
    description: str
    is_active: bool
    supports_js_render: bool
    crawl_interval_minutes: int
    default_max_pages: int
    schedule_enabled: bool
    schedule_days: int


DEMO_SOURCE_SEEDS = [
    DemoSourceSeed(
        code="anhui_ggzy_zfcg",
        name="安徽省公共资源交易监管网（政府采购）",
        base_url="https://ggzy.ah.gov.cn/",
        official_url="https://ggzy.ah.gov.cn/",
        list_url="https://ggzy.ah.gov.cn/zfcg/list?bulletinNature=1&time=1",
        description="Phase-3 主样板来源（已实现可运行抓取）",
        is_active=True,
        supports_js_render=False,
        crawl_interval_minutes=1440,
        default_max_pages=50,
        schedule_enabled=True,
        schedule_days=1,
    ),
    DemoSourceSeed(
        code="ccgp_gov_cn",
        name="中国政府采购网",
        base_url="https://www.ccgp.gov.cn/",
        official_url="https://www.ccgp.gov.cn/",
        list_url="https://search.ccgp.gov.cn/bxsearch",
        description="Phase-3 扩展来源占位（待接入可运行 parser）",
        is_active=False,
        supports_js_render=False,
        crawl_interval_minutes=1440,
        default_max_pages=50,
        schedule_enabled=False,
        schedule_days=1,
    ),
    DemoSourceSeed(
        code="ggzy_gov_cn_deal",
        name="全国公共资源交易平台（政府采购）",
        base_url="https://www.ggzy.gov.cn/",
        official_url="https://www.ggzy.gov.cn/",
        list_url="https://www.ggzy.gov.cn/deal/dealList.html?HEADER_DEAL_TYPE=02",
        description="Phase-3 可运行来源（政府采购聚合，支持源级去重）",
        is_active=True,
        supports_js_render=False,
        crawl_interval_minutes=1440,
        default_max_pages=50,
        schedule_enabled=False,
        schedule_days=1,
    ),
    DemoSourceSeed(
        code="ccgp_hubei",
        name="湖北省政府采购网/公共资源交易平台",
        base_url="https://www.ccgp-hubei.gov.cn/",
        official_url="https://www.ccgp-hubei.gov.cn/",
        list_url="https://www.ccgp-hubei.gov.cn/notice.html",
        description="Phase-3 扩展来源占位（待接入可运行 parser）",
        is_active=False,
        supports_js_render=False,
        crawl_interval_minutes=1440,
        default_max_pages=50,
        schedule_enabled=False,
        schedule_days=1,
    ),
    DemoSourceSeed(
        code="ccgp_jiangsu",
        name="江苏政府采购网",
        base_url="https://www.ccgp-jiangsu.gov.cn/",
        official_url="https://www.ccgp-jiangsu.gov.cn/",
        list_url="https://www.ccgp-jiangsu.gov.cn/home/list",
        description="Phase-3 扩展来源占位（待接入可运行 parser）",
        is_active=False,
        supports_js_render=False,
        crawl_interval_minutes=1440,
        default_max_pages=50,
        schedule_enabled=False,
        schedule_days=1,
    ),
]


def bootstrap_demo_sources(session: Session) -> list[SourceSite]:
    """Seed or update demo sources in idempotent mode."""
    saved: list[SourceSite] = []
    for seed in DEMO_SOURCE_SEEDS:
        source = session.scalar(select(SourceSite).where(SourceSite.code == seed.code))
        if source is None and seed.code == "ggzy_gov_cn_deal":
            source = session.scalar(
                select(SourceSite)
                .where(SourceSite.code.in_(["ggzy_gov_cn", "2"]))
                .order_by(SourceSite.id.asc())
                .limit(1)
            )
        if source is None:
            source = SourceSite(
                **_model_create_kwargs(session, SourceSite),
                code=seed.code,
                name=seed.name,
                base_url=seed.base_url,
                official_url=seed.official_url,
                list_url=seed.list_url,
                description=seed.description,
                is_active=seed.is_active,
                supports_js_render=seed.supports_js_render,
                crawl_interval_minutes=seed.crawl_interval_minutes,
                default_max_pages=seed.default_max_pages,
                schedule_enabled=seed.schedule_enabled,
                schedule_days=seed.schedule_days,
            )
        else:
            source.code = seed.code
            source.name = seed.name
            source.base_url = seed.base_url
            source.official_url = seed.official_url
            source.list_url = seed.list_url
            source.description = seed.description
            source.is_active = seed.is_active
            source.supports_js_render = seed.supports_js_render
            source.crawl_interval_minutes = seed.crawl_interval_minutes
            source.default_max_pages = seed.default_max_pages
            source.schedule_enabled = seed.schedule_enabled
            source.schedule_days = seed.schedule_days

        source.next_scheduled_run_at = calculate_next_scheduled_run(
            schedule_enabled=bool(source.schedule_enabled),
            schedule_days=int(source.schedule_days),
            is_active=bool(source.is_active),
        )
        session.add(source)
        saved.append(source)

    session.commit()
    for source in saved:
        session.refresh(source)
    return saved


def _model_create_kwargs(session: Session, model_cls: type) -> dict[str, int]:
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return {}
    persisted_max_id = int(session.scalar(select(func.max(model_cls.id))) or 0)
    pending_max_id = 0
    for pending in session.new:
        if isinstance(pending, model_cls):
            value = getattr(pending, "id", None)
            if value is not None:
                pending_max_id = max(pending_max_id, int(value))
    next_id = max(persisted_max_id, pending_max_id) + 1
    return {"id": next_id}
