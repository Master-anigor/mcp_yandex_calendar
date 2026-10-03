# Yandex Calendar MCP Server

A small Python integration that exposes Yandex Calendar through the Model Context Protocol (MCP). It connects an MCP client to CalDAV and provides tools to list, create and delete calendar events.

**Status:** an experimental, single-account integration for local or otherwise trusted use. This is not a public multi-user service. Tool responses currently use Russian text.

[Инструкция на русском](docs/README.ru.md)

## Tools

| Tool | Purpose | Inputs |
| --- | --- | --- |
| `get_upcoming_events` | Read upcoming events as JSON text or readable text | `days` (default 30), `format_type` (`json` or `text`) |
| `create_calendar_event` | Create an event | `title`, `start_date` (`DD.MM.YYYY`), `start_time` (`HH:MM`), optional `duration_minutes` (default 60) and `description` |
| `delete_calendar_event` | Delete an event by UID | `event_uid` |

Create and delete operations modify the configured calendar. Use a dedicated test account/calendar for evaluation. Read the limitations below before using dates or write operations.

## Architecture

`MCP client -> main.py (FastMCP tools) -> yandex_calendar.py (CalDAV adapter) -> Yandex Calendar`

`main.py` handles MCP tool arguments and result formatting. `yandex_calendar.py` discovers the first available calendar, performs CalDAV operations and parses basic iCalendar fields. Blocking read, create and delete calls are dispatched through `asyncio.to_thread`; initial discovery still runs synchronously at startup.

## Local setup

Use Python 3.12 in a virtual environment. Dependencies are pinned in `requirements.txt`; this project uses the MCP Python SDK **1.x** API. Do not upgrade to SDK 2.x without a separate compatibility review.

```bash
git clone https://github.com/Master-anigor/mcp_yandex_calendar.git
cd mcp_yandex_calendar
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp env.example .env
```

On Windows, create the environment with `py -3.12 -m venv .venv`, activate `.venv\Scripts\Activate.ps1` in PowerShell and copy the example with `Copy-Item env.example .env`.

Fill in `.env` using a **Yandex application password for Calendar**, not your main account password. Configure it in [Yandex ID](https://id.yandex.ru/security/app-passwords).

| Variable | Purpose |
| --- | --- |
| `YANDEX_USERNAME` | Yandex account login/email |
| `YANDEX_PASSWORD` | Calendar application password |
| `YANDEX_CALDAV_URL` | Optional; defaults to `https://caldav.yandex.ru` |
| `MCP_HOST` | Bind address; defaults to `127.0.0.1` |

```bash
python main.py
```

Connect a Streamable HTTP MCP client to `http://127.0.0.1:8088/mcp`. This endpoint speaks MCP; it is not a website or a conventional REST endpoint. Example read-tool arguments are `{"days": 7, "format_type": "json"}`.

## Docker

```bash
docker build -t yandex-calendar-mcp .
docker run --rm --env-file .env -e MCP_HOST=0.0.0.0 \
  -p 127.0.0.1:8088:8088 yandex-calendar-mcp
```

The bind override is necessary inside the container. The published port above remains loopback-only on the host. `.dockerignore` excludes environment files, Git history and common local artifacts from the build context. Do not copy secrets into the image or publish the container port on a public interface.

## Tests

```bash
python -W error::RuntimeWarning -m unittest discover -s tests -v
python -m py_compile main.py yandex_calendar.py tests/test_offline.py
```

The 19 isolated unit tests execute the application modules with MCP, dotenv and CalDAV boundaries stubbed. They cover tool delegation, error paths, basic event parsing, sorting and off-event-loop creation. They require only the Python standard library and do not read `.env`, contact Yandex or change calendar data.

These are **not integration tests**: passing them does not verify dependency installation, actual SDK transport behavior, Docker builds or compatibility with Yandex. The CI workflow runs these isolated checks on Python 3.12 and 3.13. Live smoke testing remains a separate step with a disposable calendar.

## Known limitations and next steps

- No application-level authentication or per-user authorization is configured. Keep the service local/private; loopback is a precaution, not a complete security boundary.
- The first discovered calendar is selected automatically. Calendar selection, reconnect behavior and explicit timeout policy still need work.
- The iCalendar parser and writer are deliberately minimal. Timezone handling, all-day/recurring events, folded lines and escaping of event text are incomplete. Avoid relying on this implementation for those cases; a standards-aware parser/writer is planned.
- Validation of durations, date ranges and result formats needs tightening. Errors are often returned as text, and logs/errors can contain event details: do not publish them without review.
- Concurrency safety of the shared CalDAV client, real-client integration tests and dependency/security updates require a separate review.

This repository currently has no open-source license file. No new license is granted by this README.
