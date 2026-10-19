import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import patch
from spot_simulator.server import Handler


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def request(self,path,data=None,headers=None):
        req=Request(self.url+path,data=data,headers=headers or {})
        try: return urlopen(req)
        except HTTPError as e: return e

    def test_status(self):
        with self.request('/api/status') as r:
            self.assertEqual(r.status,200)
            self.assertIn('live_available',json.load(r))

    def test_station_catalog(self):
        with patch('spot_simulator.providers.station_catalog', return_value=[{'id':'test.id','name':'架空駅'}]) as catalog:
            with self.request('/api/stations?operators=Toei') as r:
                self.assertEqual(r.status,200)
                self.assertEqual(json.load(r)['stations'][0]['name'],'架空駅')
            catalog.assert_called_once_with(['Toei'])

    def test_successful_optimization_over_http(self):
        p={'mode':'manual','participants':[dict(id='p',name='p',origins=['o'],time_weight=.5,fare_weight=.5)],'candidate_stations':['s'],'routes':[dict(participant_id='p',origin='o',destination='s',duration_minutes=10,fare_yen=100,transfer_minutes=0,source='synthetic')]}
        with self.request('/api/optimize',json.dumps(p).encode(),{'Content-Type':'application/json'}) as r:
            self.assertEqual(r.status,200)
            self.assertEqual(len(json.load(r)['solutions']),1)

    def test_bad_json(self):
        with self.request('/api/optimize',b'{',{'Content-Type':'application/json'}) as r:
            self.assertEqual(r.status,400)

    def test_non_json_rejected(self):
        with self.request('/api/optimize',b'{}') as r:
            self.assertEqual(r.status,415)

    def test_cross_site_rejected(self):
        with self.request('/api/optimize',b'{}',{'Content-Type':'application/json','Origin':'https://evil.example'}) as r:
            self.assertEqual(r.status,403)

    def test_path_traversal(self):
        with self.request('/../requirements.txt') as r:
            self.assertEqual(r.status,404)

    def test_validation(self):
        with self.request('/api/optimize',b'{}',{'Content-Type':'application/json'}) as r:
            self.assertEqual(r.status,400)

if __name__ == '__main__': unittest.main()
