# 湖北政府采购/公共资源（ccgp_hubei）来源占位说明

来源代码：`ccgp_hubei`

- 官网：`https://www.ccgp-hubei.gov.cn/`
- 列表页：`https://www.ccgp-hubei.gov.cn/notice.html`
- Spider 占位：`crawler/tender_crawler/spiders/ccgp_hubei_spider.py`
- Parser 占位：`crawler/tender_crawler/parsers/ccgp_hubei_parser.py`

## 当前阶段

Phase-3 收口版先完成来源配置与占位接入：
- 来源管理页可见、可编辑、可启停
- 可配置 `max_pages / 自动抓取 / 抓取周期`
- 暂未接入可运行抓取逻辑（后续迭代实现 parser 与详情链路）

## 备注

该来源不会影响 `anhui_ggzy_zfcg` 已有可运行能力。
