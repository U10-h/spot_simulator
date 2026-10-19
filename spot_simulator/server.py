"""Local web server. No paid services, keys in browser, or implicit demo fallback."""
import argparse
import json
from urllib.parse import parse_qs, urlsplit
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from .optimizer import optimize, validate, ValidationError, OptimizationLimitError
from .transit import TransitDataError, SearchLimitError


def load_provider():
    from . import providers
    return providers

STATIC = Path(__file__).resolve().parent.parent / 'static'
BUSY = BoundedSemaphore(2)
MAX_BODY = 2_000_000


def status():
    try:
        return load_provider().provider_status()
    except ImportError:
        return {'live_available': False, 'provider': 'unconfigured', 'message': '実経路データは未接続です。手入力データ、または明示的に選んだ架空サンプルで最適化できます。'}


def calculate(payload):
    mode = payload.get('mode', 'manual') if isinstance(payload, dict) else None
    if mode == 'live':
        # Validate preferences before fetching potentially expensive provider data.
        validate({**payload, 'routes': [], 'candidate_stations': payload.get('candidate_stations') or ['__automatic__']})
        try:
            payload = load_provider().build_route_matrix(payload)
        except ImportError:
            raise ValidationError('実経路データの接続設定がありません。') from None
    elif mode not in ('manual', 'demo'):
        raise ValidationError('実経路データが未接続です。手入力モードを選んでください。')
    result = optimize(payload)
    result['metadata']['mode'] = mode
    result['metadata']['provider'] = {'manual': 'user-supplied', 'demo': 'synthetic-demo', 'live': 'odpt-timetable'}[mode]
    result['metadata'].update(payload.get('provider_metadata', {}))
    result['warnings'].extend(payload.get('provider_warnings', []))
    if mode == 'demo':
        result['warnings'].insert(0, '架空の検証用データです。実際の所要時間・運賃ではありません。')
    return result


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, mime='application/json; charset=utf-8'):
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if isinstance(body, (dict, list)) else body
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split('?', 1)[0]
        if path == '/api/status':
            return self.send(200, status())
        if path == '/api/stations':
            operators = parse_qs(urlsplit(self.path).query).get('operators', ['Toei'])[0].split(',')
            try:
                return self.send(200, {'stations': load_provider().station_catalog(operators)})
            except (TransitDataError, ImportError) as e:
                return self.send(400, {'error': str(e)})
        files = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
        if path not in files:
            return self.send(404, {'error': 'ページが見つかりません。'})
        name, mime = files[path]
        try:
            self.send(200, (STATIC / name).read_bytes(), mime)
        except FileNotFoundError:
            self.send(503, {'error': '画面ファイルがありません。'})

    def do_POST(self):
        if self.path != '/api/optimize':
            return self.send(404, {'error': 'APIが見つかりません。'})
        # Reject cross-site requests; same-origin fetch works without CORS.
        origin = self.headers.get('Origin')
        host = self.headers.get('Host', '')
        if origin and origin not in ('http://' + host, 'https://' + host):
            return self.send(403, {'error': '異なるサイトからのリクエストは許可されていません。'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'application/jsonが必要です。'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            return self.send(400, {'error': 'Content-Lengthが不正です。'})
        if not 0 < length <= MAX_BODY:
            return self.send(413, {'error': '入力サイズの上限は2 MBです。'})
        if not BUSY.acquire(blocking=False):
            return self.send(429, {'error': '計算中です。少し待って再試行してください。'})
        try:
            payload = json.loads(self.rfile.read(length))
            self.send(200, calculate(payload))
        except SearchLimitError as e:
            self.send(422, {'error': str(e)})
        except (ValidationError, TransitDataError, json.JSONDecodeError, UnicodeDecodeError) as e:
            self.send(400, {'error': str(e)})
        except OptimizationLimitError as e:
            self.send(422, {'error': str(e)})
        except Exception:
            # Do not return secrets, raw provider bodies, or stack traces.
            self.send(500, {'error': '計算に失敗しました。入力とサーバー設定を確認してください。'})
        finally:
            BUSY.release()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Open http://{args.host}:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
