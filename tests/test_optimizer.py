import copy
import unittest
from spot_simulator.optimizer import optimize, ValidationError, OptimizationLimitError
from spot_simulator.server import calculate
from unittest.mock import patch
from spot_simulator.transit import TransitDataError


def payload(points):
    return {'mode':'manual', 'participants':[{'id':'p1','name':'A','origins':['origin','alternative'],'time_weight':0.5,'fare_weight':0.5}], 'candidate_stations':[f's{i}' for i in range(len(points))], 'routes':[{'participant_id':'p1','origin':'origin','destination':f's{i}','duration_minutes':t,'fare_yen':f,'transfer_minutes':0,'source':'synthetic test fixture'} for i,(t,f) in enumerate(points)]}


class OptimizerTests(unittest.TestCase):
    def test_unsupported_frontier_point(self):
        result = optimize(payload([(0,400),(2,300),(4,0),(5,500)]))
        self.assertEqual([x['station'] for x in result['solutions']], ['s0','s1','s2'])

    def test_equal_objectives_keep_station_ties(self):
        self.assertEqual(len(optimize(payload([(1,2),(1,2)]))['solutions']), 2)

    def test_missing_fare_rejected(self):
        p=payload([(1,2)]); p['routes'][0]['fare_yen']=None
        with self.assertRaises(ValidationError): optimize(p)

    def test_missing_participant_excludes_station(self):
        p=payload([(1,2)]); p['participants'].append({'id':'p2','name':'B','origins':['other'],'time_weight':1,'fare_weight':0})
        r=optimize(p); self.assertEqual(r['solutions'],[]); self.assertEqual(len(r['excluded_stations']),1)

    def test_two_routes_same_station_retained(self):
        p=payload([(1,500)]); p['routes'].append({**p['routes'][0], 'origin':'alternative','duration_minutes':5,'fare_yen':100})
        r=optimize(p); self.assertEqual(len(r['solutions']),2)
        self.assertTrue(all(len(x['routes'])==1 for x in r['solutions']))

    def test_zero_time_weight(self):
        p=payload([(1,500),(5,100)]); p['participants'][0].update(time_weight=0,fare_weight=1)
        self.assertEqual(optimize(p)['solutions'][0]['station'],'s1')

    def test_invalid_weights(self):
        p=payload([(1,2)]); p['participants'][0]['fare_weight']=0.6
        with self.assertRaises(ValidationError): optimize(p)

    def test_nonfinite(self):
        for invalid in [float('nan'),float('inf'), True,-1]:
            p=payload([(1,2)]); p['routes'][0]['duration_minutes']=invalid
            with self.assertRaises(ValidationError): optimize(p)

    def test_normalization_preserves_front(self):
        p=payload([(1,500),(5,100)])
        a=optimize(p); p.update(time_scale_minutes=5,fare_scale_yen=100)
        self.assertEqual([x['station'] for x in a['solutions']],[x['station'] for x in optimize(p)['solutions']])

    def test_no_silent_partial_result(self):
        with self.assertRaises(OptimizationLimitError): optimize(payload([(1,5),(2,4)]),max_points=1)

    def test_demo_explicit(self):
        p=payload([(1,2)]); p['mode']='demo'
        self.assertEqual(calculate(p)['metadata']['provider'],'synthetic-demo')

    def test_live_provider_metadata_and_auto_candidates(self):
        p=payload([(1,2)]); p['mode']='live'
        returned={**p,'provider_metadata':{'candidate_count':1},'provider_warnings':['provider note']}
        p['candidate_stations']=[]
        with patch('spot_simulator.providers.build_route_matrix', return_value=returned):
            result=calculate(p)
        self.assertEqual(result['metadata']['mode'],'live')
        self.assertEqual(result['metadata']['candidate_count'],1)
        self.assertIn('provider note',result['warnings'])

    def test_live_never_falls_back(self):
        p=payload([(1,2)]); p['mode']='live'
        with patch('spot_simulator.providers.build_route_matrix', side_effect=TransitDataError('unavailable')):
            with self.assertRaises(TransitDataError): calculate(p)

if __name__ == '__main__': unittest.main()
