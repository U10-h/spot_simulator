import unittest
from spot_simulator.station_timetable import reconstruct_station_timetables
from spot_simulator.transit import stop_offsets


class StationReconstructionTests(unittest.TestCase):
    def railway(self):
        return [{'owl:sameAs':'line', 'odpt:stationOrder':[
            {'odpt:station':s,'odpt:index':i} for i,s in enumerate('abcd')]}]

    def row(self, station, time, train='odpt.Train:Example.1', direction='up'):
        return {'odpt:operator':'op','odpt:railway':'line',
                'odpt:calendar':'weekday','odpt:station':station,
                'odpt:railDirection':direction,'dct:issued':'2026-01-01',
                'odpt:stationTimetableObject':[{'odpt:train':train,
                'odpt:departureTime':time,'odpt:trainType':'Local',
                'odpt:destinationStation':['d']}]}

    def run_rows(self, rows):
        return reconstruct_station_timetables(rows,self.railway())

    def test_identified_departures_not_direction_and_missing_terminal(self):
        rows=[self.row('b','08:05',direction='changed'),self.row('a','08:00')]
        trips,warnings=self.run_rows(rows)
        self.assertEqual(len(trips),1)
        stops=trips[0]['odpt:trainTimetableObject']
        self.assertEqual([s['odpt:departureStation'] for s in stops],['a','b'])
        self.assertNotIn('odpt:arrivalTime',stops[1])
        self.assertTrue(stop_offsets(stops)[1][3])
        self.assertTrue(warnings)

    def test_missing_id_no_guess_by_number_or_next_departure(self):
        rows=[self.row('a','08:00',train=None),self.row('b','08:05',train=None)]
        for r in rows:r['odpt:stationTimetableObject'][0]['odpt:trainNumber']='123'
        self.assertFalse(self.run_rows(rows)[0])

    def test_no_topology_no_reconstruction(self):
        self.assertFalse(reconstruct_station_timetables([self.row('a','08:00'),self.row('b','08:05')])[0])

    def test_duplicate_station_reused_id_rejected(self):
        self.assertFalse(self.run_rows([self.row('a','08:00'),self.row('b','08:05'),self.row('a','09:00')])[0])

    def test_reversal_and_equal_time_rejected(self):
        self.assertFalse(self.run_rows([self.row('a','08:00'),self.row('c','08:05'),self.row('b','08:10')])[0])
        self.assertFalse(self.run_rows([self.row('a','08:00'),self.row('b','08:00')])[0])

    def test_midnight_service_day(self):
        trips,_=self.run_rows([self.row('a','23:58'),self.row('b','00:03')])
        self.assertEqual(len(trips),1)
        self.assertEqual(stop_offsets(trips[0]['odpt:trainTimetableObject'])[1][1],86400+180)

    def test_reverse_direction_and_express_skipped_stop(self):
        rows=[self.row('d','08:00'),self.row('b','08:05')]
        for row in rows: row['odpt:stationTimetableObject'][0]['odpt:destinationStation']=['a']
        trips,_=self.run_rows(rows)
        self.assertEqual(len(trips),1)
        self.assertEqual(len(trips[0]['odpt:trainTimetableObject']),2)

    def test_no_join_across_calendar_or_id(self):
        rows=[self.row('a','08:00'),self.row('b','08:05')]
        rows[1]['odpt:calendar']='holiday'
        self.assertFalse(self.run_rows(rows)[0])
        rows[1]['odpt:calendar']='weekday'
        rows[1]['odpt:stationTimetableObject'][0]['odpt:train']='odpt.Train:Example.2'
        self.assertFalse(self.run_rows(rows)[0])

    def test_conflicting_version_or_destination_rejected(self):
        rows=[self.row('a','08:00'),self.row('b','08:05')]
        rows[1]['dct:issued']='2026-02-01'
        self.assertFalse(self.run_rows(rows)[0])
        rows[1]['dct:issued']='2026-01-01'
        rows[1]['odpt:stationTimetableObject'][0]['odpt:destinationStation']=['c']
        self.assertFalse(self.run_rows(rows)[0])

    def test_destination_must_be_nonempty_and_ahead(self):
        for destination in ([], ['a'], ['b']):
            rows=[self.row('a','08:00'),self.row('b','08:05')]
            for row in rows:
                row['odpt:stationTimetableObject'][0]['odpt:destinationStation']=destination
            self.assertFalse(self.run_rows(rows)[0])
        rows=[self.row('b','09:00'),self.row('c','09:10')]
        for row in rows:row['odpt:stationTimetableObject'][0]['odpt:destinationStation']=['a']
        self.assertFalse(self.run_rows(rows)[0])

    def test_preserves_all_source_provenance(self):
        rows=[self.row('a','08:00'),self.row('b','08:05')]
        for i,row in enumerate(rows):
            row['dc:date']=f'2026-01-0{i+1}T12:00:00+09:00'
            row['owl:sameAs']=f'odpt.StationTimetable:Example.{i}'
        trips,_=self.run_rows(rows)
        self.assertEqual(trips[0]['source_generated_dates'],[r['dc:date'] for r in rows])
        self.assertEqual(trips[0]['source_timetable_ids'],[r['owl:sameAs'] for r in rows])

    def test_invalid_and_large_gap_rejected(self):
        for time in ['bad','08:99','27:00','12:00']:
            self.assertFalse(self.run_rows([self.row('a','08:00'),self.row('b',time)])[0])

if __name__=='__main__':unittest.main()
