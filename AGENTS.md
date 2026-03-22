# AGENTS.md

## Project
Build phase-1 of a tender aggregation platform.

## Phase-1 scope
Only implement:
- multi-source tender crawling
- raw page/archive storage
- structured field extraction
- deduplication and version tracking
- search/list/detail APIs
- minimal admin UI

Do NOT implement:
- AI matching
- enterprise qualification matching
- bid document generation

## Business tags
The platform serves smart terminal business in power distribution and consumption.
Important tags include:
- low-voltage transparency
- load management
- virtual power plant
- asset digitization
- RFID identification
- near-field O&M
- plug-and-play
- carbon metering
- safety electricity usage

## Tech stack
- Python 3.12
- Scrapy
- Playwright
- FastAPI
- PostgreSQL
- SQLAlchemy
- Alembic
- pytest
- Docker Compose

## Rules
- Keep spiders isolated per source
- Archive raw HTML/PDF metadata
- Separate crawling, parsing, and DB writing
- Every task must include tests
- Every task must update README
- Run tests before marking complete

## Review and reporting language
- All audit reports, review summaries, risk analysis, and remediation plans must be written in Simplified Chinese.
- File paths, function names, class names, and code identifiers may remain in English.
- Be specific and actionable. Always include file paths and relevant functions/classes/modules when possible.