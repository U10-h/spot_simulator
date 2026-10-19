import unittest
from datetime import date, datetime, timedelta
from spot_simulator.transit import *

class TransitTests(unittest.TestCase):
    def dt(self, value): return japan_datetime('2026-10-20T'+value+':00+09:00')
    def ride(self,a,b,dep,arr,op='op',trip='t'):
        return Ride(a,b,self.dt(dep),self.dt(arr),op,'line',trip)
    def test_timezone_required_and_conversion(self):
        with self.assertRaises(TransitDataError): japan_datetime('2026-10-20T12:00')
        self.assertEqual(japan_datetime('2026-10-20T00:00:00Z').hour,9)
    def test_calendar(self):
        monday=date(2026,10,12)
        self.assertFalse(calendar_matches('odpt.Calendar:Weekday',monday,True))
        self.assertTrue(calendar_matches('odpt.Calendar:SaturdayHoliday',monday,True))
        self.assertFalse(calendar_matches('odpt.Calendar:Unsupported',monday,False))
    def test_midnight(self):
        rows=[{'odpt:departureStation':'a','odpt:departureTime':'23:58'}, {'odpt:arrivalStation':'b','odpt:arrivalTime':'00:07'}]
        stops=stop_offsets(rows)
        self.assertEqual(stops[1][1],86400+7*60)
        self.assertEqual(stop_offsets([{'odpt:departureStation':'x','odpt:departureTime':'00:30'}])[0][1],88200)
    def test_arrive_by_fare_frontier_wait(self):
        rides=[self.ride('a','b','08:30','08:50','cheap','c'),self.ride('a','b','08:45','08:58','fast','f'),self.ride('a','b','08:55','09:01','fast','late')]
        router=ScheduledRouter(rides,{('cheap','a','b'):100,('fast','a','b'):200})
        result=router.arrive_by('a','b',self.dt('09:00'))
        self.assertEqual([(r['duration_minutes'],r['fare_yen']) for r in result],[(15,200),(30,100)])
        self.assertEqual(result[0]['early_wait_minutes'],2)
        self.assertEqual(result[0]['travel_duration_minutes'],13)
    def test_transfer_and_od_fare_not_edge_sum(self):
        rides=[self.ride('a','b','08:00','08:10',trip='one'),self.ride('b','c','08:15','08:25',trip='two')]
        fares={('op','a','b'):100,('op','b','c'):100,('op','a','c'):150}
        result=ScheduledRouter(rides,fares).arrive_by('a','c',self.dt('09:00'))
        self.assertEqual(result[0]['fare_yen'],150)
        self.assertEqual(result[0]['transfer_minutes'],5)
        rides[1]=self.ride('b','c','08:11','08:25',trip='two')
        self.assertEqual(ScheduledRouter(rides,fares).arrive_by('a','c',self.dt('09:00')),[])
    def test_missing_and_cross_operator_fares(self):
        ride=self.ride('a','b','08:00','08:10')
        self.assertIsNone(ScheduledRouter([ride],{}).arrive_by('a','b',self.dt('09:00'))[0]['fare_yen'])
        rides=[ride,self.ride('b','c','08:15','08:25','other','two')]
        result=ScheduledRouter(rides,{('op','a','b'):100,('other','b','c'):100}).arrive_by('a','c',self.dt('09:00'))
        self.assertEqual(result[0]['fare_status'],'cross_operator_unavailable')
    def test_search_limit_not_partial_frontier(self):
        r=ScheduledRouter([self.ride('a','b','08:00','08:10')],{},max_expansions=0)
        with self.assertRaises(SearchLimitError): r.arrive_by('a','b',self.dt('09:00'))
    def test_transfer_links(self):
        rides=[self.ride('a','b','08:00','08:10',trip='one'),self.ride('d','c','08:16','08:25',trip='two')]
        r=ScheduledRouter(rides,{('op','a','c'):200},[Transfer('b','d',300)])
        self.assertEqual(r.arrive_by('a','c',self.dt('09:00'))[0]['transfer_minutes'],6)

if __name__=='__main__': unittest.main()

class ProviderTests(unittest.TestCase):
    def test_tokyo_scope(self):
        from spot_simulator.providers import tokyo_station
        def s(op,name): return {'odpt:operator':'odpt.Operator:'+op,'dc:title':name}
        self.assertFalse(tokyo_station(s('Toei','本八幡')))
        self.assertFalse(tokyo_station(s('TokyoMetro','和光市')))
        self.assertFalse(tokyo_station(s('TokyoMetro','妙典')))
        self.assertTrue(tokyo_station(s('MIR','六町')))
        self.assertFalse(tokyo_station(s('MIR','八潮')))
    def test_mock_adapter(self):
        from unittest.mock import patch
        from spot_simulator.providers import build_route_matrix
        station=lambda x: {'owl:sameAs':x,'dc:title':x,'odpt:operator':'odpt.Operator:Toei'}
        trip={'owl:sameAs':'synthetic','odpt:operator':'odpt.Operator:Toei','odpt:railway':'synthetic','odpt:trainType':'odpt.TrainType:Toei.Local','odpt:calendar':'odpt.Calendar:Weekday','odpt:trainTimetableObject':[{'odpt:departureStation':'a','odpt:departureTime':'08:00'},{'odpt:arrivalStation':'b','odpt:arrivalTime':'08:20'}]}
        fare={'odpt:operator':'odpt.Operator:Toei','odpt:fromStation':'a','odpt:toStation':'b','odpt:ticketFare':200}
        data={'Station':[station('a'),station('b')],'TrainTimetable':[trip],'RailwayFare':[fare],'Calendar':[]}
        with patch('spot_simulator.providers._get',side_effect=lambda kind,op:data[kind]):
            out=build_route_matrix({'participants':[{'id':'p','origins':['a']}],'candidate_stations':['b'],'meeting_at':'2026-10-20T09:00:00+09:00'})
        self.assertEqual(out['routes'][0]['duration_minutes'],60)
        self.assertEqual(out['routes'][0]['fare_yen'],200)
        self.assertFalse(out['provider_metadata']['realtime'])

class DominanceRegression(unittest.TestCase):
    dt = TransitTests.dt
    ride = TransitTests.ride
    def test_adjacent_trip_state_is_not_pruned(self):
        rides=[self.ride('a','b','08:00','08:10',trip='x'),self.ride('b','d','09:00','09:10',trip='x'),self.ride('b','d','08:50','09:05',trip='y')]
        result=ScheduledRouter(rides,{('op','a','d'):100}).arrive_by('a','d',self.dt('09:30'))
        self.assertEqual(len(result),1)

class BulkRoutingTests(unittest.TestCase):
    dt = TransitTests.dt
    ride = TransitTests.ride
    def test_bulk_origins_keep_separate_frontiers(self):
        rides=[self.ride('a','d','08:00','08:30',trip='a'),self.ride('b','d','08:40','08:55',trip='b')]
        router=ScheduledRouter(rides,{('op','a','d'):100,('op','b','d'):200},single_operator_only=True)
        found=router.arrive_by({'a','b','d'},'d',self.dt('09:00'))
        self.assertEqual({r['origin'] for r in found},{'a','b','d'})
        self.assertEqual({r['origin']:r['duration_minutes'] for r in found},{'a':60,'b':20,'d':0})
    def test_single_operator_label_can_continue_same_trip(self):
        rides=[self.ride('a','b','08:00','08:10',trip='x'),self.ride('b','d','08:20','08:30',trip='x')]
        router=ScheduledRouter(rides,{('op','a','d'):100},single_operator_only=True)
        self.assertEqual(len(router.arrive_by('a','d',self.dt('09:00'))),1)

class StationIdentityTests(unittest.TestCase):
    def test_auto_candidates_preserve_canonical_identity(self):
        from unittest.mock import patch
        from spot_simulator.providers import build_route_matrix
        stations=[{'owl:sameAs':sid,'dc:title':'同名','odpt:operator':'odpt.Operator:Toei'} for sid in ['id-one','id-two']]
        data={'Station':stations,'TrainTimetable':[],'RailwayFare':[],'Calendar':[]}
        p={'participants':[{'id':'p','origins':['id-one']}],'meeting_at':'2026-10-20T09:00:00+09:00'}
        with patch('spot_simulator.providers._get',side_effect=lambda kind,op:data[kind]):
            result=build_route_matrix(p)
            self.assertEqual(result['candidate_stations'],['id-one','id-two'])
            self.assertEqual(len(result['routes']),1)
            with self.assertRaises(TransitDataError): build_route_matrix({**p,'participants':[{'id':'p','origins':['同名']}]})

class LatestLabelEquivalenceTests(unittest.TestCase):
    def test_single_operator_matches_bounded_bruteforce(self):
        import random
        base=japan_datetime('2026-10-20T08:00:00+09:00')
        for seed in range(20):
            rng=random.Random(seed); rides=[]
            for i in range(25):
                a,b=rng.sample(['a','b','c','d'],2)
                departure=base+timedelta(minutes=rng.randrange(100))
                rides.append(Ride(a,b,departure,departure+timedelta(minutes=rng.randrange(3,15)),'op','line',str(i)))
            meeting=base+timedelta(hours=2)
            departures=[r.departure for r in rides if r.origin=='a' and r.destination=='d' and r.arrival<=meeting]
            departures += [a.departure for a in rides for b in rides if a.origin=='a' and a.destination==b.origin and b.destination=='d' and a.arrival+timedelta(minutes=3)<=b.departure and b.arrival<=meeting]
            result=ScheduledRouter(rides,{('op','a','d'):100},max_boardings=2,single_operator_only=True).arrive_by('a','d',meeting)
            self.assertEqual(bool(result),bool(departures))
            if departures: self.assertEqual(result[0]['departure_at'],max(departures).isoformat())

class FallbackIntegrationTests(unittest.TestCase):
    def test_opt_in_reconstruction_marks_proxy_routes(self):
        from unittest.mock import patch
        from spot_simulator.providers import build_route_matrix
        line='odpt.Railway:Toei.Synthetic';op='odpt.Operator:Toei'
        stations=[{'owl:sameAs':s,'dc:title':s,'odpt:operator':op} for s in ['a','b']]
        tables=[{'owl:sameAs':'table-'+s,'dc:date':'2026-10-01T00:00:00+09:00','odpt:operator':op,'odpt:railway':line,'odpt:calendar':'odpt.Calendar:Weekday','odpt:station':s,'odpt:stationTimetableObject':[{'odpt:train':'odpt.Train:Toei.Synthetic.1','odpt:trainType':'odpt.TrainType:Toei.Local','odpt:departureTime':t,'odpt:destinationStation':['c']}]} for s,t in [('a','08:00'),('b','08:20')]]
        data={'Station':stations,'TrainTimetable':[],'RailwayFare':[{'odpt:operator':op,'odpt:fromStation':'a','odpt:toStation':'b','odpt:ticketFare':200}],'Calendar':[],'StationTimetable':tables,'Railway':[{'owl:sameAs':line,'odpt:stationOrder':[{'odpt:station':'a','odpt:index':0},{'odpt:station':'b','odpt:index':1},{'odpt:station':'c','odpt:index':2}]}]}
        p={'participants':[{'id':'p','origins':['a']}],'candidate_stations':['b'],'meeting_at':'2026-10-20T09:00:00+09:00','use_station_timetable_fallback':True}
        with patch('spot_simulator.providers._get',side_effect=lambda kind,op:data[kind]): out=build_route_matrix(p)
        self.assertEqual(out['provider_metadata']['reconstructed_trip_count'],1)
        self.assertTrue(out['routes'][0]['legs'][0]['station_timetable_proxy'])
        self.assertTrue(out['routes'][0]['legs'][0]['arrival_estimated'])
