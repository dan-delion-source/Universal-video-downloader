import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import httpx
import pytest
from backend.browser_policy import TabPolicy, media_response, MAX_TABS
from backend.browser_sessions import BrowserSession, BrowserSessions, IDLE_SECONDS
from backend.browser_auth import cookie_jar
from backend.models import MediaItem, MediaFormat


@pytest.mark.parametrize('url,kind', [
    ('https://cdn.example.org/play?id=1', 'video/mp4'),
    ('https://cdn.example.org/master', 'application/vnd.apple.mpegurl'),
    ('https://cdn.example.org/manifest.mpd?key=1', 'text/plain'),
    ('https://cdn.example.org/v.webm', ''),
])
def test_media_detection(url, kind): assert media_response(url, kind)


@pytest.mark.parametrize('url,kind', [
    ('https://cdn.example.org/segment.ts', 'video/mp2t'),
    ('https://cdn.example.org/segment.m4s', 'video/mp4'),
    ('https://cdn.example.org/audio', 'audio/mp4'),
    ('https://cdn.example.org/ad.js', 'application/javascript'),
    ('file:///tmp/video.mp4', 'video/mp4'),
])
def test_ignore_fragments_audio_and_non_web(url, kind): assert not media_response(url, kind)


def test_popup_requires_explicit_go_and_stay_keeps_original():
    tabs = TabPolicy()
    tabs.add('original', initial=True)
    assert tabs.navigation('original', 'https://example.org/watch')
    tabs.add('ad')
    assert not tabs.navigation('ad', 'https://ads.example.org/interstitial')
    assert tabs.active == 'original' and len(tabs.snapshot()['popups']) == 1
    tabs.remove('ad')
    assert tabs.active == 'original' and not tabs.snapshot()['popups']
    tabs.add('next')
    assert not tabs.navigation('next', 'https://example.org/player')
    tabs.activate('next')
    assert tabs.navigation('next', 'https://example.org/player')
    assert tabs.active == 'next' and not tabs.snapshot()['popups']
    tabs.remove('next')
    assert tabs.active == 'original'


def test_popup_limits_and_invalid_schemes():
    tabs = TabPolicy()
    tabs.add('original', initial=True)
    for i in range(MAX_TABS - 1): tabs.add(str(i))
    with pytest.raises(ValueError): tabs.add('excess')
    with pytest.raises(ValueError): tabs.navigation('0', 'javascript:alert(1)')


def item():
    return MediaItem(id='video1', title='Detected video', source='sniff',
        formats=[MediaFormat(format_id='best')], download_target='https://cdn.example.org/video.mp4').model_dump()


def session():
    result = BrowserSession(id='a' * 32)
    result.accept({'status': 'ready', 'items': [item()], 'auth': {
        'cookies': [{'name': 'session', 'value': 'secret', 'domain': 'cdn.example.org', 'path': '/', 'secure': True}],
        'user_agent': 'Chromium', 'referrers': {item()['download_target']: 'https://example.org/watch'}}, 'frame': 'aGVsbG8='})
    return result


def test_public_snapshot_has_no_auth_or_frame_bytes():
    result = session()
    public = result.public()
    assert 'auth' not in public and 'secret' not in json.dumps(public) and 'frame' not in public
    assert public['has_frame'] and public['frame_version'] == 1
    public['items'].clear()
    assert len(result.state['items']) == 1


def test_download_handoff_only_for_detected_unprotected_media():
    result = session()
    auth = result.download_auth(item()['download_target'])
    assert auth['referer'] == 'https://example.org/watch'
    assert auth['cookies'][0]['value'] == 'secret'
    auth['cookies'].clear()
    assert result.auth['cookies']
    with pytest.raises(ValueError, match='not detected'): result.download_auth('https://other.example.org/video.mp4')
    result.state['items'][0]['drm'] = True
    with pytest.raises(ValueError, match='Protected'): result.download_auth(item()['download_target'])


def test_cookies_respect_domain_path_and_tls():
    cookies = cookie_jar({'cookies': [{'name': 'session', 'value': 'secret', 'domain': 'cdn.example.org', 'path': '/private', 'secure': True}]})
    seen = []
    from urllib.request import Request
    for url in ['https://cdn.example.org/private/video', 'https://other.example.org/private/video',
                'https://sub.cdn.example.org/private/video', 'http://cdn.example.org/private/video',
                'https://cdn.example.org/public/video']:
        request = Request(url)
        cookies.add_cookie_header(request)
        seen.append(request.get_header('Cookie'))
    assert seen == ['session=secret', None, None, None, None]


def test_missing_browser_extra_and_expired_session():
    async def scenario():
        sessions = BrowserSessions()
        with patch('backend.browser_sessions.importlib.util.find_spec', return_value=None):
            with pytest.raises(ValueError, match='browser extra'): await sessions.start('https://example.org')
        sessions.sessions['expired'] = BrowserSession(id='expired', touched=0)
        with pytest.raises(KeyError): sessions.get('expired')
    asyncio.run(scenario())


def test_browser_close_stops_worker_but_retains_download_handoff():
    async def scenario():
        sessions = BrowserSessions()
        current = session()
        current.process = SimpleNamespace(returncode=None)
        sessions.sessions[current.id] = current
        process = current.process
        with patch('backend.browser_sessions.stop_process', new_callable=AsyncMock) as stop:
            await sessions.close(current.id)
            stop.assert_awaited_once_with(process)
        assert current.process is None
        assert current.state['status'] == 'closed' and not current.public()['has_frame']
        assert current.download_auth(item()['download_target'])['cookies']
        await sessions.shutdown()
        assert not sessions.sessions
    asyncio.run(scenario())


def test_frame_consumer_stops_hung_or_invalid_worker():
    async def scenario():
        sessions = BrowserSessions()
        current = BrowserSession(id='test')
        current.process = SimpleNamespace(stdout=SimpleNamespace(readline=AsyncMock(return_value=b'not json\n')))
        with patch('backend.browser_sessions.stop_process', new_callable=AsyncMock) as stop:
            await sessions.consume(current)
            assert current.state['status'] == 'error'
            stop.assert_awaited_once()
    asyncio.run(scenario())


def test_async_browser_api_redacts_auth_validates_commands_and_handoffs():
    from backend.main import app, browsers, manager
    async def scenario():
        current = session()
        browsers.sessions[current.id] = current
        transport = httpx.ASGITransport(app=app)
        try:
            async with httpx.AsyncClient(transport=transport, base_url='http://127.0.0.1') as client:
                with patch('backend.main.browsers.command', new_callable=AsyncMock) as command:
                    response = await client.get(f'/api/browser/sessions/{current.id}')
                    assert response.status_code == 200 and 'secret' not in response.text
                    assert (await client.get(f'/api/browser/sessions/{current.id}/frame')).content == b'hello'
                    endpoint = f'/api/browser/sessions/{current.id}/command'
                    assert (await client.post(endpoint, json={'action':'navigate', 'url':'file:///etc/passwd'})).status_code == 400
                    assert (await client.post(endpoint, json={'action':'click', 'x':-1})).status_code == 422
                    assert (await client.post(endpoint, json={'action':'key', 'key':'malicious'})).status_code == 400
                    assert (await client.post(endpoint, json={'action':'stay', 'tab_id':'popup'})).status_code == 200
                    command.assert_awaited_once()
                    assert (await client.post(endpoint, json={'action':'back'}, headers={'Origin':'https://evil.example'})).status_code == 403
                with patch.object(manager, 'add', return_value=SimpleNamespace(id='job')) as add:
                    response = await client.post('/api/download', json={'url': item()['download_target'], 'browser_session_id':current.id})
                    assert response.status_code == 200
                    assert add.call_args.args[2]['cookies'][0]['value'] == 'secret'
                    assert 'secret' not in response.text
                    response = await client.post('/api/download', json={'url':'https://other.example.org/v.mp4', 'browser_session_id':current.id})
                    assert response.status_code == 400
                assert (await client.post(f'/api/browser/sessions/{current.id}/close', json={})).status_code == 200
                assert current.state['status'] == 'closed'
        finally: browsers.sessions.pop(current.id, None)
    asyncio.run(scenario())


def test_cookie_scope_is_preserved_across_manifest_redirects():
    from backend.extractors.static_extractor import fetch_document
    cookies = cookie_jar({'cookies': [{'name': 'session', 'value': 'secret', 'domain': 'cdn.example.org', 'path': '/', 'secure': True}]})
    seen = []
    def handle(request):
        seen.append((str(request.url), request.headers.get('cookie')))
        if len(seen) == 1: return httpx.Response(302, headers={'location':'https://sub.cdn.example.org/manifest'})
        return httpx.Response(200, text='#EXTM3U')
    original = httpx.Client
    with patch('backend.extractors.static_extractor.httpx.Client', side_effect=lambda **kw: original(transport=httpx.MockTransport(handle))), patch('backend.extractors.static_extractor.validate_url'):
        fetch_document('https://cdn.example.org/master', 'unused', cookies=cookies)
    assert seen[0][1] == 'session=secret' and seen[1][1] is None


def test_protected_state_resets_on_main_document_navigation():
    from backend.browser_worker import InteractiveBrowser
    browser = InteractiveBrowser(context=None)
    main = object()
    page = SimpleNamespace(main_frame=main)
    browser.protected_pages.add('tab')
    browser.documents['tab'] = 1
    old = item()
    old['drm'] = True
    browser.items['old'] = MediaItem.model_validate(old)
    browser.navigated('tab', page, object())
    assert 'tab' in browser.protected_pages  # subframe navigation is not a new document
    browser.navigated('tab', page, main)
    assert 'tab' not in browser.protected_pages and browser.documents['tab'] == 2
    assert browser.items['old'].drm


def test_first_popup_request_is_paused_and_go_explicitly_activates_it():
    from backend.browser_worker import InteractiveBrowser
    async def scenario():
        class Page:
            def __init__(self):
                self.events = {}
                self.main_frame = SimpleNamespace(page=self)
            def on(self, name, callback): self.events[name] = callback
            async def close(self): self.events['close']()
        browser = InteractiveBrowser(None)
        original, popup = Page(), Page()
        original_id = browser.register(original)
        browser.policy.navigation(original_id, 'https://example.org/watch')
        route = SimpleNamespace(request=SimpleNamespace(url='https://ads.example.org/new',
            frame=popup.main_frame, is_navigation_request=lambda:True), abort=AsyncMock(), continue_=AsyncMock(), fulfill=AsyncMock())
        await browser.route(route)
        route.fulfill.assert_awaited_once_with(status=204, body="")
        route.abort.assert_not_awaited()
        route.continue_.assert_not_awaited()
        popup_id = browser.page_ids[popup]
        assert browser.policy.active == original_id
        assert browser.policy.snapshot()['popups'][0]['url'] == 'https://ads.example.org/new'
        browser.navigate = AsyncMock()
        with patch('backend.browser_worker.asyncio.to_thread', new_callable=AsyncMock) as read:
            read.side_effect = [json.dumps({'action':'activate','tab_id':popup_id}), json.dumps({'action':'close'})]
            await browser.commands()
        browser.navigate.assert_awaited_once_with(popup, 'https://ads.example.org/new', replay={'method':'GET','body':None,'headers':{}})
        assert browser.policy.active == popup_id
    asyncio.run(scenario())


def test_stay_closes_popup_without_navigating_original():
    from backend.browser_worker import InteractiveBrowser
    async def scenario():
        class Page:
            def __init__(self): self.events = {}; self.main_frame = object()
            def on(self, name, callback): self.events[name] = callback
            async def close(self): self.events['close']()
        browser = InteractiveBrowser(None)
        original_id = browser.register(Page())
        browser.policy.navigation(original_id, 'https://example.org/watch')
        popup_id = browser.register(Page())
        browser.policy.navigation(popup_id, 'https://ads.example.org/new')
        with patch('backend.browser_worker.asyncio.to_thread', new_callable=AsyncMock) as read:
            read.side_effect = [json.dumps({'action':'stay','tab_id':popup_id}), json.dumps({'action':'close'})]
            await browser.commands()
        assert browser.policy.active == original_id and popup_id not in browser.policy.tabs
        assert browser.policy.tabs[original_id]['url'] == 'https://example.org/watch'
    asyncio.run(scenario())


def test_network_media_preserves_embedded_player_referrer():
    from backend.browser_worker import InteractiveBrowser
    async def scenario():
        class Page:
            main_frame = object()
            def on(self, *_): pass
        browser = InteractiveBrowser(None)
        page = Page()
        tab_id = browser.register(page)
        browser.policy.navigation(tab_id, 'https://example.org/watch')
        response = SimpleNamespace(url='https://cdn.example.org/video.mp4', status=206,
            headers={'content-type':'video/mp4'}, request=SimpleNamespace(frame=SimpleNamespace(page=page),
                headers={'referer':'https://embed.example.org/player'}))
        await browser.response(response)
        assert browser.items[response.url].page_url == 'https://example.org/watch'
        assert browser.referrers[response.url] == 'https://embed.example.org/player'
    asyncio.run(scenario())
