"""Exercise the local proxy's trust boundary with an actual HTTP upstream."""
import json
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.demo_dashboard import Dashboard, SERVICES


class Upstream(BaseHTTPRequestHandler):
    def do_GET(self):
        self.respond(200, {'path': self.path})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.respond(202 if body.get('sensor_id') == 'known' else 422,
                     {'detail': 'upstream response', 'request': body})

    def respond(self, status, data):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class DashboardTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.temp = tempfile.TemporaryDirectory()
        cls.clock = Path(cls.temp.name) / 'event-clock.txt'
        cls.dashboard = Dashboard(('127.0.0.1', 0), {s: cls.upstream.server_port for s in SERVICES}, cls.clock)
        cls.threads = []
        for server in (cls.upstream, cls.dashboard):
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            cls.threads.append(thread)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.dashboard, cls.upstream):
            server.shutdown()
            server.server_close()
        for thread in cls.threads:
            thread.join(timeout=2)
        cls.temp.cleanup()

    def request(self, path, method='GET', body=None, headers=None):
        req = Request(f'http://127.0.0.1:{self.dashboard.server_port}{path}',
                      data=body, method=method, headers=headers or {})
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.headers, response.read()

    def test_assets_and_security_headers(self):
        for path in ('/', '/dashboard.js', '/styles.css'):
            status, headers, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertTrue(body)
            self.assertEqual(headers['X-Frame-Options'], 'DENY')
            self.assertIn("connect-src 'self'", headers['Content-Security-Policy'])

    def test_query_forwarding(self):
        status, _, body = self.request('/api/analytics/traffic/summaries?intersection_id=demo&limit=2')
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['path'], '/traffic/summaries?intersection_id=demo&limit=2')

    def test_upstream_validation_status_and_body_are_preserved(self):
        payload = b'{"sensor_id":"unknown"}'
        status, _, body = self.request('/api/ingestion/readings', 'POST', payload,
                                      {'X-Demo-Token': self.dashboard.token})
        self.assertEqual(status, 422)
        self.assertEqual(json.loads(body)['request']['sensor_id'], 'unknown')

    def test_reject_cross_origin_missing_token_and_arbitrary_routes(self):
        self.assertEqual(self.request('/config', headers={'Host':'evil.example'})[0], 403)
        self.assertEqual(self.request('/config', headers={'Origin':'https://evil.example'})[0], 403)
        self.assertEqual(self.request('/api/ingestion/readings', 'POST', b'{}')[0], 403)
        self.assertEqual(self.request('/api/analytics/metrics')[0], 405)
        self.assertEqual(self.request('/api/registry/sensors/../secrets')[0], 405)
        self.assertEqual(self.request('/api/registry/sensors', 'DELETE')[0], 501)

    def test_reject_malformed_and_oversized_json(self):
        headers = {'X-Demo-Token': self.dashboard.token}
        self.assertEqual(self.request('/api/ingestion/readings', 'POST', b'{bad', headers)[0], 400)
        self.assertEqual(self.request('/api/ingestion/readings', 'POST', b' ' * 65537, headers)[0], 413)

    def test_accepted_event_clock_survives_restart_and_never_moves_backwards(self):
        headers = {'X-Demo-Token': self.dashboard.token}
        for stamp in ('2026-11-23T08:44:10Z', '2026-11-23T08:41:00Z'):
            payload = json.dumps({'sensor_id':'known','observed_at':stamp}).encode()
            self.assertEqual(self.request('/api/ingestion/readings', 'POST', payload, headers)[0], 202)
        _, _, body = self.request('/config')
        observed = json.loads(body)['lastObserved']
        self.assertEqual(observed, 1795423450000)
        restarted = Dashboard(('127.0.0.1', 0), {}, self.clock)
        try:
            self.assertEqual(restarted.last_observed, observed)
        finally:
            restarted.server_close()


if __name__ == '__main__':
    unittest.main()
