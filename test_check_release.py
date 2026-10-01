import unittest
from urllib.error import URLError
from check_release import check, origin


class ReleaseCheckTests(unittest.TestCase):
    def responses(self, url):
        path = url.removeprefix('https://domovoy.example.org')
        content = {'/health': ('application/json', b'{"ok":true}'),
                   '/api/config': ('application/json', b'{"mode":"max"}'),
                   '/': ('text/html', 'Домовой /app.js /style.css /request.js'.encode()),
                   '/request.js': ('text/javascript', b'function createDomovoyClient() {}'),
                   '/app.js': ('text/javascript', b'const app = true;'),
                   '/style.css': ('text/css', b'body {color: black}')}[path]
        return 200, {'Content-Type': content[0] + '; charset=utf-8',
                     'Content-Security-Policy': "default-src 'self'"}, content[1]

    def test_production_passes(self):
        results = check('https://domovoy.example.org/', self.responses)
        self.assertEqual(len(results), 6)
        self.assertTrue(all(ok for _, ok, _ in results))

    def test_rejects_demo_and_static_fallback(self):
        def demo(url):
            if url.endswith('/api/config'):
                return 200, {'Content-Type': 'application/json'}, b'{"mode":"demo"}'
            if url.endswith('/app.js'):
                return 200, {'Content-Type': 'text/html'}, b'<html>fallback</html>'
            return self.responses(url)
        results = check('https://domovoy.example.org', demo)
        self.assertEqual([path for path, ok, _ in results if not ok], ['/api/config', '/app.js'])

    def test_origin_rejects_sensitive_or_non_https_urls(self):
        for url in ('http://example.org', 'https://user:secret@example.org',
                    'https://example.org/?token=secret', 'https://example.org/#secret',
                    'https://example.org/app', 'https://example.org:bad'):
            with self.subTest(url=url), self.assertRaises(ValueError): origin(url)

    def test_failures_do_not_echo_response_or_url(self):
        def failed(url):
            if url.endswith('/health'): raise URLError('secret-token-in-url')
            return 302, {'Location': 'https://other.example/secret'}, b'secret body'
        results = check('https://domovoy.example.org', failed)
        self.assertFalse(any(ok for _, ok, _ in results))
        self.assertNotIn('secret', str(results))


if __name__ == '__main__': unittest.main()
