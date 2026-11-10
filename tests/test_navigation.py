import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from backend.browser_policy import NavigationPolicy
from backend.browser_worker import InteractiveBrowser
from backend.browser_sessions import BrowserSession


class Page:
    def __init__(self):
        self.main_frame = SimpleNamespace(page=self)
        self.url = 'https://example.org/watch'
        self.goto = AsyncMock()
    def on(self, *_): pass


def browser():
    result = InteractiveBrowser(None)
    page = Page()
    tab_id = result.register(page)
    result.policy.navigation(tab_id, page.url)
    return result, page, tab_id


def route(page, url, method='GET', body=None):
    response = SimpleNamespace(status=200, headers={}, dispose=AsyncMock())
    return SimpleNamespace(request=SimpleNamespace(url=url, frame=page.main_frame,
        is_navigation_request=lambda:True, method=method, post_data_buffer=body,
        headers={'content-type':'application/x-www-form-urlencoded'} if body else {}),
        continue_=AsyncMock(), fulfill=AsyncMock(), abort=AsyncMock(), fetch=AsyncMock(return_value=response))


def test_navigation_permission_is_exact_and_one_use():
    policy = NavigationPolicy()
    policy.grant('tab', 'https://example.org/watch#player')
    assert policy.consume('tab', 'https://example.org/watch')
    assert not policy.consume('tab', 'https://example.org/watch')
    policy.grant('tab', 'https://example.org/watch')
    assert not policy.consume('tab', 'https://ads.example.org/')
    assert not policy.consume('tab', 'https://example.org/watch')


def test_pending_proposals_are_stable_bounded_and_do_not_authorize_urls():
    policy = NavigationPolicy()
    first = policy.propose('tab', 'https://ads.example.org/a', 'popup')
    assert policy.propose('tab', 'https://ads.example.org/a') == first
    for i in range(10): policy.propose('tab', f'https://ads.example.org/{i}')
    assert len(policy.snapshot()) == 4
    assert not policy.consume('tab', 'https://ads.example.org/a')
    assert policy.resolve(first)['url'] == 'https://ads.example.org/a'
    policy.remove_tab('tab')
    assert not policy.snapshot()
    with pytest.raises(ValueError): policy.propose('tab', 'javascript:alert(1)')


def test_page_replacement_is_paused_without_switching_or_loading_destination():
    async def scenario():
        worker, page, tab_id = browser()
        request = route(page, 'https://ads.example.org/redirect')
        await worker.route(request)
        request.fulfill.assert_awaited_once_with(status=204, body='')
        request.continue_.assert_not_awaited()
        request.fetch.assert_not_awaited()
        assert worker.policy.active == tab_id
        assert worker.policy.tabs[tab_id]['url'] == 'https://example.org/watch'
        intent = worker.navigation.snapshot()[0]
        await worker.resolve_navigation(intent['id'], follow=False)
        page.goto.assert_not_awaited()
        assert not worker.navigation.snapshot()
    asyncio.run(scenario())


def test_explicit_go_grants_one_navigation_then_blocks_ad_replacement():
    async def scenario():
        worker, page, tab_id = browser()
        target = 'https://example.org/player'
        request = route(page, target)
        async def goto(*args, **kwargs): await worker.route(request)
        page.goto.side_effect = goto
        await worker.navigate(page, target)
        request.fetch.assert_awaited_once_with(max_redirects=0, timeout=15000)
        request.fulfill.assert_awaited_once_with(response=request.fetch.return_value)
        another = route(page, 'https://ads.example.org/interstitial')
        await worker.route(another)
        another.fetch.assert_not_awaited()
        another.fulfill.assert_awaited_once_with(status=204, body='')
        assert worker.policy.tabs[tab_id]['url'] == target
    asyncio.run(scenario())


def test_http_redirect_requires_its_own_consent():
    async def scenario():
        worker, page, tab_id = browser()
        target = 'https://example.org/player'
        request = route(page, target)
        request.fetch.return_value.status = 302
        request.fetch.return_value.headers = {'location':'https://ads.example.org/landing'}
        worker.navigation.grant(tab_id, target)
        await worker.route(request)
        request.fetch.assert_awaited_once_with(max_redirects=0, timeout=15000)
        request.fulfill.assert_awaited_once_with(status=204, body='')
        assert worker.navigation.snapshot()[0]['url'] == 'https://ads.example.org/landing'
        assert worker.policy.tabs[tab_id]['url'] == target
    asyncio.run(scenario())


def test_form_post_is_preserved_privately_and_replayed_only_after_go():
    async def scenario():
        worker, page, tab_id = browser()
        target = 'https://example.org/login'
        body = b'username=user&password=private'
        request = route(page, target, method='POST', body=body)
        await worker.route(request)
        request.fetch.assert_not_awaited()
        pending = worker.navigation.snapshot()[0]
        assert 'private' not in json.dumps(worker.navigation.snapshot())
        replay_request = route(page, target)
        async def goto(*args, **kwargs): await worker.route(replay_request)
        page.goto.side_effect = goto
        await worker.resolve_navigation(pending['id'], follow=True)
        kwargs = replay_request.fetch.call_args.kwargs
        assert kwargs['method'] == 'POST' and kwargs['post_data'] == body
        assert kwargs['headers']['content-type'] == 'application/x-www-form-urlencoded'
        assert not worker.navigation_requests and not worker.replays
    asyncio.run(scenario())


def test_window_open_proposal_does_not_create_or_activate_a_tab_before_go():
    async def scenario():
        worker, page, tab_id = browser()
        worker.context = SimpleNamespace(new_page=AsyncMock(return_value=Page()))
        worker.proposed_navigation({'page':page}, {'url':'https://external.example.org/video', 'kind':'popup'})
        assert worker.policy.active == tab_id and len(worker.policy.tabs) == 1
        worker.context.new_page.assert_not_awaited()
        pending = worker.navigation.snapshot()[0]
        await worker.resolve_navigation(pending['id'], follow=True)
        worker.context.new_page.assert_awaited_once()
        assert worker.policy.active != tab_id and len(worker.policy.tabs) == 2
    asyncio.run(scenario())


def test_pending_navigation_state_is_public_but_post_payload_is_not():
    worker, page, tab_id = browser()
    worker.propose_request(tab_id, 'https://example.org/login', {'method':'POST','body':b'secret','headers':{}})
    session = BrowserSession(id='a' * 32)
    session.accept({'navigations':worker.navigation.snapshot()})
    assert session.public()['navigations'][0]['hostname'] == 'example.org'
    assert 'secret' not in json.dumps(session.public())
