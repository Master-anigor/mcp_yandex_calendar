"""Isolated unit tests: SDK/CalDAV boundaries are stubbed; no credentials or network.

These execute the actual application modules, not copied implementations.
They do not validate MCP transport, the installed dependency set, or Yandex.
"""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import threading
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]


def load_file(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


caldav_stub = ModuleType('caldav')
caldav_stub.DAVClient = Mock(side_effect=AssertionError('No live CalDAV in unit tests'))
with patch.dict('sys.modules', {'caldav': caldav_stub}):
    adapter = load_file('_calendar_under_test', 'yandex_calendar.py')


class FastMCPStub:
    """Only the constructor/decorator boundary; not a simulated MCP server."""
    def __init__(self, **kwargs):
        self.options = kwargs

    def tool(self):
        return lambda func: func


def load_facade(host=None):
    sdk = ModuleType('mcp.server.fastmcp')
    sdk.FastMCP = FastMCPStub
    sdk.Context = object
    dotenv = ModuleType('dotenv')
    dotenv.load_dotenv = lambda: None
    modules = {
        'mcp': ModuleType('mcp'),
        'mcp.server': ModuleType('mcp.server'),
        'mcp.server.fastmcp': sdk,
        'dotenv': dotenv,
        'yandex_calendar': adapter,
    }
    env = {} if host is None else {'MCP_HOST': host}
    with patch.dict('sys.modules', modules), patch.dict(os.environ, env, clear=True):
        return load_file('_facade_under_test', 'main.py')


class CalendarTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = adapter.YandexCalendar()
        self.calendar = Mock()
        self.client.caldav_calendar = self.calendar
        self.start = dt.datetime(2026, 10, 10, 14, 0)
        self.end = dt.datetime(2026, 10, 10, 15, 0)

    async def test_unconfigured_operations_return_error(self):
        self.client.caldav_calendar = None
        self.assertEqual(await self.client.get_upcoming_events(), 'CalDAV не настроен')
        self.assertEqual(await self.client.create_event('Demo', self.start, self.end), 'CalDAV не настроен')
        self.assertEqual(await self.client.delete_event('fake-uid'), 'CalDAV не настроен')

    def test_simple_event_fields(self):
        parsed = self.client._parse_ical_event(
            'BEGIN:VEVENT\nUID:demo\nSUMMARY:Demo\nDTSTART:20261010T140000\n'
            'DTEND:20261010T150000\nSEQUENCE:2\nEND:VEVENT'
        )
        self.assertEqual(parsed['uid'], 'demo')
        self.assertEqual(parsed['title'], 'Demo')
        self.assertEqual(parsed['start_time'], '2026-10-10T14:00:00')
        self.assertEqual(parsed['sequence'], 2)

    async def test_create_runs_io_off_event_loop(self):
        loop_thread = threading.get_ident()
        worker_threads = []
        self.calendar.add_event.side_effect = lambda payload: worker_threads.append(threading.get_ident())
        result = await self.client.create_event('Demo', self.start, self.end, 'Example')
        self.assertIn('успешно', result)
        self.assertEqual(len(worker_threads), 1)
        self.assertNotEqual(worker_threads[0], loop_thread)
        payload = self.calendar.add_event.call_args.args[0]
        self.assertIn('DTSTART:20261010T140000', payload)
        self.assertIn('SUMMARY:Demo', payload)

    async def test_create_failure_returns_error(self):
        self.calendar.add_event.side_effect = RuntimeError('fake failure')
        result = await self.client.create_event('Demo', self.start, self.end)
        self.assertIn('Ошибка создания события', result)

    async def test_delete_existing(self):
        event = Mock()
        self.calendar.object_by_uid.return_value = event
        result = await self.client.delete_event('fake-uid')
        self.calendar.object_by_uid.assert_called_once_with('fake-uid')
        event.delete.assert_called_once_with()
        self.assertIn('успешно', result)

    async def test_delete_missing(self):
        self.calendar.object_by_uid.return_value = None
        self.assertEqual(await self.client.delete_event('fake-uid'), 'Событие не найдено')

    async def test_empty_calendar_formats(self):
        self.calendar.date_search.return_value = []
        self.assertEqual(await self.client.get_upcoming_events(), {'events': [], 'count': 0})
        self.assertEqual(await self.client.get_upcoming_events(format_type='text'), 'Нет предстоящих событий')

    async def test_list_sorted_events(self):
        self.calendar.date_search.return_value = [
            SimpleNamespace(data='UID:later\nDTSTART:20261011T140000\nSUMMARY:Later', url='https://example.invalid/2'),
            SimpleNamespace(data='UID:earlier\nDTSTART:20261010T140000\nSUMMARY:Earlier', url='https://example.invalid/1'),
        ]
        result = await self.client.get_upcoming_events(days=14)
        self.assertEqual(result['count'], 2)
        self.assertEqual([e['uid'] for e in result['events']], ['earlier', 'later'])
        kwargs = self.calendar.date_search.call_args.kwargs
        self.assertEqual(kwargs['end'] - kwargs['start'], dt.timedelta(days=14))

    async def test_read_failure_is_structured(self):
        self.calendar.date_search.side_effect = RuntimeError('fake failure')
        result = await self.client.get_upcoming_events()
        self.assertIn('error', result)
        self.assertIn('fake failure', result['error'])


class FacadeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.app = load_facade()
        self.service = SimpleNamespace(
            caldav_calendar=True,
            get_upcoming_events=AsyncMock(return_value={'events': [], 'count': 0}),
            create_event=AsyncMock(return_value='Событие успешно создано'),
            delete_event=AsyncMock(return_value='Событие успешно удалено'),
        )
        self.app.calendar_event = self.service
        self.ctx = SimpleNamespace(info=AsyncMock(), error=AsyncMock())

    def test_default_host_is_loopback(self):
        self.assertEqual(self.app.mcp.options['host'], '127.0.0.1')

    def test_explicit_host_is_respected(self):
        self.assertEqual(load_facade('0.0.0.0').mcp.options['host'], '0.0.0.0')

    async def test_list_json(self):
        result = await self.app.get_upcoming_events(days=7, ctx=self.ctx)
        self.assertEqual(json.loads(result), {'events': [], 'count': 0})
        self.service.get_upcoming_events.assert_awaited_once_with(7, 'json')

    async def test_list_text_passthrough(self):
        self.service.get_upcoming_events.return_value = 'No events'
        result = await self.app.get_upcoming_events(format_type='text')
        self.assertEqual(result, 'No events')

    async def test_list_error_logging_is_awaited(self):
        self.service.get_upcoming_events.side_effect = RuntimeError('fake failure')
        result = await self.app.get_upcoming_events(ctx=self.ctx)
        self.ctx.error.assert_awaited_once_with(result)

    async def test_create_unconfigured_logging_is_awaited(self):
        self.service.caldav_calendar = None
        result = await self.app.create_calendar_event('Demo', '10.10.2026', '14:00', ctx=self.ctx)
        self.ctx.error.assert_awaited_once_with(result)
        self.service.create_event.assert_not_awaited()

    async def test_delete_unconfigured_logging_is_awaited(self):
        self.service.caldav_calendar = None
        result = await self.app.delete_calendar_event('fake-uid', ctx=self.ctx)
        self.ctx.error.assert_awaited_once_with(result)
        self.service.delete_event.assert_not_awaited()

    async def test_invalid_date_rejected(self):
        result = await self.app.create_calendar_event('Demo', '31.02.2026', '14:00', ctx=self.ctx)
        self.assertIn('Ошибка формата даты', result)
        self.service.create_event.assert_not_awaited()
        self.ctx.error.assert_awaited_once_with(result)

    async def test_create_delegates_times(self):
        await self.app.create_calendar_event('Demo', '10.10.2026', '14:00', 45, 'Example', ctx=self.ctx)
        self.service.create_event.assert_awaited_once_with(
            'Demo', dt.datetime(2026, 10, 10, 14), dt.datetime(2026, 10, 10, 14, 45), 'Example'
        )

    async def test_delete_delegates_uid(self):
        await self.app.delete_calendar_event('fake-uid', ctx=self.ctx)
        self.service.delete_event.assert_awaited_once_with('fake-uid')


if __name__ == '__main__':
    unittest.main()
