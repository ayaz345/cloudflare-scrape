# -*- coding: utf-8 -*-

import responses
import re

from requests.compat import urlencode, Morsel
from collections import OrderedDict
from os import path
from io import open

# Fake URL, network requests are not allowed by default when using the decorator
url = 'http://example-site.dev'
# These kwargs will be passed to tests by the decorator
cfscrape_kwargs = dict(
    delay=0.01
)
# Cloudflare challenge fixtures are only read from the FS once
cache = {}


class ChallengeResponse(responses.Response):
    """Simulates a standard IUAM JS challenge response from Cloudflare

    This would be the first response in a test.

    Kwargs:
        Keyword arguments used to override the defaults.
        The request will error if it doesn't match a defined response.
    """

    def __init__(self, **kwargs):
        defaults = (('method', 'GET'),
                    ('status', 503),
                    ('headers', {'Server': 'cloudflare'}),
                    ('content_type', 'text/html'))

        for k, v in defaults:
            kwargs.setdefault(k, v)

        super(ChallengeResponse, self).__init__(**kwargs)


class RedirectResponse(responses.CallbackResponse):
    """Simulate the redirect response that occurs after sending a correct answer

    This would be the second response in a test.
    It will call the provided callback when a matching request is received.
    Afterwards, the default is to redirect to the index page "/" aka fake URL.

    Kwargs:
        Keyword arguments used to override the defaults.
        The request will error if it doesn't match a defined response.
    """

    def __init__(self, callback=lambda request: None, location=None, **kwargs):
        defaults = (('method', 'GET'),
                    ('status', 302),
                    ('headers', {'Location': '/'}),
                    ('content_type', 'text/html'),
                    ('body', ''))

        for k, v in defaults:
            kwargs.setdefault(k, v)

        if location:
            kwargs['headers']['Location'] = location

        args = tuple(kwargs.pop(k) for k in ('status', 'headers', 'body'))
        kwargs['callback'] = lambda request: callback(request) or args

        super(RedirectResponse, self).__init__(**kwargs)


class DefaultResponse(responses.Response):
    """Simulate the final response after the challenge is solved

    This would be the last response in a test and normally occurs after a redirect.

    Kwargs:
        Keyword arguments used to override the defaults.
        The request will error if it doesn't match a defined response.
    """

    def __init__(self, **kwargs):
        defaults = (('method', 'GET'),
                    ('status', 200),
                    ('content_type', 'text/html'))

        for k, v in defaults:
            kwargs.setdefault(k, v)

        super(DefaultResponse, self).__init__(**kwargs)


class CaptchaResponse(ChallengeResponse):
    """Simulates a reCAPTCHA(v2) response from Cloudflare

    This would be the only response in current tests.

    Kwargs:
        Keyword arguments used to override the defaults.
        The request will error if it doesn't match a defined response.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('status', 403)
        super(CaptchaResponse, self).__init__(**kwargs)


def fixtures(filename):
    """Read and cache a challenge fixture

    Returns: HTML (bytes): The HTML challenge fixture
    """
    if not cache.get(filename):
        with open(path.join(path.dirname(__file__), 'fixtures', filename), 'rb') as fp:
            cache[filename] = fp.read()
    return cache[filename]


# This is the page that should be received after bypassing the JS challenge.
requested_page = fixtures('requested_page.html')


# This fancy decorator wraps tests so the responses will be mocked.
# It could be called directly e.g. challenge_responses(*args)(test_func) -> wrapper
def challenge_responses(filename, jschl_answer, redirect_to='/'):
    # This function is called with the test_func and returns a new wrapper.
    def challenge_responses_decorator(test):
        @responses.activate
        def wrapper(self):
            html = fixtures(filename).decode('utf-8')

            params = OrderedDict()

            s = re.search(r'name="s"\svalue="(?P<s_value>[^"]+)', html)
            if s:
                params['s'] = s['s_value']
            params['jschl_vc'] = re.search(r'name="jschl_vc" value="(\w+)"', html)[1]
            params['pass'] = re.search(r'name="pass" value="(.+?)"', html)[1]
            params['jschl_answer'] = jschl_answer

            submit_uri = '{}/cdn-cgi/l/chk_jschl?{}'.format(url, urlencode(params))

            responses.add(ChallengeResponse(url=url, body=fixtures(filename)))

            def on_redirect(request):
                # We don't register the last response unless the redirect occurs
                responses.add(DefaultResponse(url=url, body=requested_page))

            responses.add(RedirectResponse(
                url=submit_uri, callback=on_redirect, location=redirect_to
            ))

            return test(self, **cfscrape_kwargs)

        return wrapper

    return challenge_responses_decorator


def recaptcha_responses(filename):
    def recaptcha_responses_decorator(test):
        @responses.activate
        def wrapper(self):
            responses.add(CaptchaResponse(url=url, body=fixtures(filename)))

            return test(self, **cfscrape_kwargs)
        return wrapper

    return recaptcha_responses_decorator


def cloudflare_cookies():
    # Cloudflare cookie that should be set when challenge is presented
    cfduid = Morsel()
    cfduid.set('__cfduid', 'uid-1', 'uid-1')
    cfduid['path'] = '/'
    cfduid['domain'] = '.example-site.dev'

    # Cloudflare cookie that should be set when challenge is bypassed
    cf_clearance = Morsel()
    cf_clearance.set('cf_clearance', 'uid-2', 'uid-2')
    cf_clearance['path'] = '/'
    cf_clearance['domain'] = '.example-site.dev'

    return cfduid, cf_clearance
