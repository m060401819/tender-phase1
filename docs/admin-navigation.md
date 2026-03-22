# Admin Navigation（Phase-3 第1步）

## 1. 目标

后台页面统一导航与返回路径，避免页面“跳得过去、回不来”。

## 2. 统一顶部导航

通过共享模板片段实现：
- `app/templates/admin/_top_nav.html`
- `app/templates/admin/_breadcrumbs.html`

在以下页面统一可见：
- `/admin/home`
- `/admin/source-sites`
- `/admin/sources/{code}`
- `/admin/crawl-jobs`
- `/admin/crawl-errors`
- `/admin/notices`
- `/admin/dashboard`
- `/admin/settings/health-rules`

## 3. 面包屑（Breadcrumb）

各页面标题区上方显示最小面包屑，例如：
- 首页 / 来源网站列表 / 来源详情
- 首页 / 招标信息汇总工作台 / 公告详情

## 4. 返回路径闭环

二级页面均提供“返回首页/返回上一级”：
- 来源详情：返回来源列表
- 公告详情：返回公告工作台
- 原文详情：返回原文列表，并在有关联公告时支持返回公告详情
- 错误详情：返回错误列表
- 抓取任务详情：返回任务列表

## 5. 入口增强

- 顶部导航将“招标信息工作台”设为高优先级入口（显著样式）
- 首页增加显著卡片按钮，直达 `/admin/notices`
- 来源网站列表页增加显著工作台入口

## 6. 模板改造范围

主要改造模板：
- `app/templates/admin/dashboard.html`
- `app/templates/admin/source_sites_list.html`
- `app/templates/admin/source_detail.html`
- `app/templates/admin/notices_list.html`
- `app/templates/admin/notices_detail.html`
- `app/templates/admin/crawl_jobs_list.html`
- `app/templates/admin/crawl_jobs_detail.html`
- `app/templates/admin/crawl_errors_list.html`
- `app/templates/admin/crawl_errors_detail.html`
- `app/templates/admin/health_rules_settings.html`
