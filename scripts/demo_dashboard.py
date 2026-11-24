"""Local demo GUI for the real cloud APIs. No new AWS resources or credentials in JS.

Run: python scripts/demo_dashboard.py --connect
Ctrl+C stops the dashboard and only the port-forward processes it started.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hmac
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import threading
import time
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SERVICES = {
    'registry': 'sensor-registry', 'ingestion': 'traffic-ingestion',
    'recommendations': 'signal-recommendation', 'analytics': 'traffic-analytics',
    'incidents': 'incident-manager',
}
ROUTES = {
    'registry': {'GET': r'/(healthz|sensors/[^/]+|intersections/[^/]+)',
                 'POST': r'/(sensors|intersections)'},
    'ingestion': {'GET': r'/(healthz|readyz)', 'POST': r'/readings'},
    'recommendations': {'GET': r'/(healthz|readyz|recommendations)'},
    'analytics': {'GET': r'/(healthz|readyz|traffic/summaries)'},
    'incidents': {'GET': r'/(healthz|incidents/[^/]+)', 'POST': r'/incidents'},
}


class Dashboard(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, targets, clock_file=None):
        self.targets = targets
        self.token = secrets.token_urlsafe(32)
        self.clock_file = clock_file
        self.clock_lock = threading.Lock()
        try:
            self.last_observed = int(clock_file.read_text()) if clock_file else 0
        except (OSError, ValueError):
            self.last_observed = 0
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    server: Dashboard

    def reply(self, status, body, content_type='application/json'):
        if not isinstance(body, bytes):
            body = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def dispatch(self):
        allowed_hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed_hosts:
            return self.reply(403, {'detail': 'Use the dashboard localhost address.'})
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + h for h in allowed_hosts}:
            return self.reply(403, {'detail': 'Cross-origin requests are not allowed.'})
        parsed = urlsplit(self.path)
        if self.command == 'GET' and parsed.path == '/config':
            return self.reply(200, {'csrf': self.server.token, 'services': SERVICES,
                                    'lastObserved': self.server.last_observed,
                                    'connection': 'Deployed EKS APIs through authenticated local tunnels'})
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/dashboard.js': ('dashboard.js', 'application/javascript; charset=utf-8'),
                  '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
        if self.command == 'GET' and parsed.path in assets:
            file, kind = assets[parsed.path]
            return self.reply(200, (ROOT / 'gui' / file).read_bytes(), kind)
        match = re.fullmatch(r'/api/([a-z]+)/(.+)', parsed.path)
        if not match:
            return self.reply(404, {'detail': 'Unknown dashboard route.'})
        service, suffix = match.groups()
        route = '/' + unquote(suffix)
        rule = ROUTES.get(service, {}).get(self.command)
        if not rule or not re.fullmatch(rule, route) or '..' in route:
            return self.reply(405, {'detail': 'This demo operation is not allowed.'})
        body = None
        if self.command == 'POST':
            if not hmac.compare_digest(self.headers.get('X-Demo-Token', ''), self.server.token):
                return self.reply(403, {'detail': 'Refresh the dashboard before submitting.'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    return self.reply(413, {'detail': 'Request must be between 1 and 65536 bytes.'})
                body = self.rfile.read(length)
                json.loads(body)
            except (ValueError, UnicodeError):
                return self.reply(400, {'detail': 'Expected a JSON request body.'})
        target = self.server.targets[service]
        connection = http.client.HTTPConnection('127.0.0.1', target, timeout=22)
        try:
            path = '/' + suffix + ('?' + parsed.query if parsed.query else '')
            connection.request(self.command, path, body=body, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            if service == 'ingestion' and self.command == 'POST' and response.status == 202:
                try:
                    observed = int(datetime.fromisoformat(json.loads(body)['observed_at']).timestamp() * 1000)
                    with self.server.clock_lock:
                        self.server.last_observed = max(observed, self.server.last_observed)
                        if self.server.clock_file:
                            self.server.clock_file.write_text(str(self.server.last_observed))
                except (ValueError, KeyError, TypeError, OSError):
                    self.log_error('Could not save the demo event clock; preserve browser storage.')
            self.reply(response.status, response.read(), response.getheader('Content-Type', 'application/json'))
        except (OSError, http.client.HTTPException):
            self.reply(503, {'detail': f'{SERVICES[service]} is unreachable. Check the tunnel and AWS login.'})
        finally:
            connection.close()

    do_GET = dispatch
    do_POST = dispatch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--base-port', type=int, default=18091)
    parser.add_argument('--connect', action='store_true', help='Start five owned kubectl port-forwards.')
    parser.add_argument('--context', default='smarttraffic-demo')
    parser.add_argument('--kubeconfig')
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535 or not 1024 <= args.base_port <= 65531:
        parser.error('Ports must be unprivileged valid TCP ports.')
    targets = {name: args.base_port + i for i, name in enumerate(SERVICES)}
    if args.port in targets.values():
        parser.error('The dashboard port overlaps its service tunnel ports.')
    processes, logs = [], []
    directory = ROOT / '.data' / 'dashboard'
    directory.mkdir(parents=True, exist_ok=True)
    server = Dashboard(('127.0.0.1', args.port), targets, directory / 'event-clock.txt')
    try:
        if args.connect:
            if not shutil.which('kubectl'):
                parser.error('kubectl is required for --connect.')
            # Refuse to reuse unrelated listeners on these dedicated demo ports.
            for port in targets.values():
                with socket.socket() as check:
                    check.bind(('127.0.0.1', port))
            for name, service in SERVICES.items():
                command = ['kubectl', '--context', args.context]
                if args.kubeconfig:
                    command += ['--kubeconfig', args.kubeconfig]
                command += ['port-forward', '-n', 'smarttraffic', 'service/' + service,
                            f'{targets[name]}:8000', '--address', '127.0.0.1']
                log = (directory / f'{name}.log').open('ab')
                logs.append(log)
                processes.append(subprocess.Popen(command, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
                # Serialize credential retrieval; concurrent AWS browser-token refreshes
                # can hit the account's OAuth rate limit.
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    if processes[-1].poll() is not None:
                        raise RuntimeError(f'{service} tunnel failed. See {directory / (name + ".log")}')
                    try:
                        with socket.create_connection(('127.0.0.1', targets[name]), timeout=.3):
                            break
                    except OSError:
                        time.sleep(.25)
                else:
                    raise RuntimeError(f'{service} tunnel did not start within 45 seconds.')
                print(f'Connected: {service}', flush=True)
        print(f'Open http://127.0.0.1:{args.port}', flush=True)
        print('Real cloud data. Signal adjustments are simulated. Ctrl+C stops this dashboard and its tunnels.', flush=True)
        server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:
        print('\nStopping dashboard and owned tunnels.', flush=True)
    finally:
        server.server_close()
        for process in processes:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=4)
                except subprocess.TimeoutExpired:
                    process.kill()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()
