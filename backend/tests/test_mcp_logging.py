import hashlib
import json
import logging

import pytest

from app.transports import mcp_logging
from app.transports.mcp_logging import MCPResponseLoggingMiddleware


def logged(caplog):
    return [json.loads(record.message) for record in caplog.records
            if record.name == mcp_logging.logger.name]




async def exercise(response_body, *, request_body=b'{"method":"tools/list","params":{}}',
                   status=200, read_request=True, path='/mcp'):
    sent = []

    async def endpoint(scope, receive, send):
        if read_request:
            message = await receive()
            assert message['body'] == request_body
        await send({'type': 'http.response.start', 'status': status,
                    'headers': [(b'content-type', b'application/json')]})
        # Capture must observe chunks without regrouping or rewriting the response.
        await send({'type': 'http.response.body', 'body': response_body[:10], 'more_body': True})
        await send({'type': 'http.response.body', 'body': response_body[10:], 'more_body': False})

    async def receive():
        return {'type': 'http.request', 'body': request_body, 'more_body': False}

    async def send(message):
        sent.append(message)

    await MCPResponseLoggingMiddleware(endpoint)(
        {'type': 'http', 'method': 'POST', 'path': path, 'headers': []}, receive, send)
    assert b''.join(message.get('body', b'') for message in sent) == response_body
    assert [message['body'] for message in sent[1:]] == [response_body[:10], response_body[10:]]
    return sent


@pytest.mark.asyncio
async def test_pagination_is_logged_without_disclosing_cursor_values(caplog):
    payload = json.dumps({'result': {'tools': [{'name': 'save_recipe'}], 'nextCursor': 'private-next'}}).encode()
    sent = await exercise(payload, request_body=b'{"method":"tools/list","params":{"cursor":"private-previous"}}')
    entry = logged(caplog)[-1]
    assert entry['request_cursor_present'] is True and entry['next_cursor_present'] is True
    assert entry['tool_count'] == 1 and entry['tool_names'] == ['save_recipe']
    assert ('x-mcp-request-id', entry['request_id']) in [(k.decode(), v.decode()) for k, v in sent[0]['headers']]
    assert 'private-next' not in json.dumps(entry) and 'private-previous' not in json.dumps(entry)


@pytest.mark.asyncio
async def test_auth_rejection_is_visible_even_when_auth_does_not_read_the_body(caplog):
    await exercise(b'{"error":"invalid_token"}', status=401, read_request=False)
    entry = logged(caplog)[-1]
    assert entry['http_status'] == 401 and entry['completed'] is True
    assert entry['rpc_method'] == 'unknown'
    assert entry['response_json_parsed'] is True
    assert caplog.records[-1].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_capture_limit_does_not_truncate_the_client_response(caplog, monkeypatch):
    monkeypatch.setattr(mcp_logging, 'RESPONSE_CAPTURE_LIMIT', 12)
    payload = json.dumps({'result': {'tools': [{'name': 'save_recipe'}]}}).encode()
    await exercise(payload)
    entry = logged(caplog)[-1]
    assert entry['response_capture_truncated'] is True
    assert entry['tool_count'] is None and entry['response_json_parsed'] is False
    assert entry['response_sha256'] == hashlib.sha256(payload).hexdigest()
    assert entry['response_bytes'] == len(payload)


@pytest.mark.asyncio
async def test_invalid_json_diagnostic_and_rpc_error_do_not_expose_error_text(caplog):
    payload = b'{"error":{"code":-32700,"message":"private parsing detail"}}'
    await exercise(payload, request_body=b'invalid private request')
    entry = logged(caplog)[-1]
    assert entry['rpc_method'] == 'unknown' and entry['rpc_error_code'] == -32700
    assert 'private' not in json.dumps(entry)
    assert caplog.records[-1].levelno == logging.WARNING


@pytest.mark.asyncio
async def test_logger_failure_cannot_break_the_mcp_response(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('logger unavailable')

    monkeypatch.setattr(mcp_logging.logger, 'log', fail)
    await exercise(b'{"result":{"tools":[]}}')


@pytest.mark.asyncio
async def test_non_mcp_requests_are_not_logged_or_changed(caplog):
    sent = await exercise(b'{"ok":true}', path='/api/recipes')
    assert sent[0]['headers'] == [(b'content-type', b'application/json')]
    assert logged(caplog) == []
