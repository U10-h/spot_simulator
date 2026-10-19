"""Bounded, timetable-only arrive-by search. No live train endpoints.

The frontier is exact only over supplied trips, a lookback window, and the
stated maximum number of train boardings. Generic search uses simple paths.
Single-operator mode uses latest labels per station/boarding count, because the
authoritative origin-destination fare is constant for that operator. Cycles
cannot improve the latest departure time; cross-operator journeys are excluded.
"""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo
from collections import defaultdict
import heapq
import itertools

JST = ZoneInfo('Asia/Tokyo')

class TransitDataError(ValueError):
    pass

class SearchLimitError(TransitDataError):
    pass


def japan_datetime(value):
    try:
        dt = datetime.fromisoformat(value) if isinstance(value, str) else value
        if not isinstance(dt, datetime) or dt.tzinfo is None:
            raise ValueError()
        return dt.astimezone(JST)
    except (ValueError, TypeError):
        raise TransitDataError('日時にはタイムゾーンを含めてください（例: 2026-10-20T18:00:00+09:00）。') from None


def calendar_matches(calendar, day, holiday=None):
    if holiday is None:
        try:
            import jpholiday
        except ImportError:
            raise TransitDataError('日本の祝日判定には jpholiday のインストールが必要です。') from None
        holiday = bool(jpholiday.is_holiday(day))
    kind = calendar.split(':')[-1]
    if kind == 'Weekday': return day.weekday() < 5 and not holiday
    if kind == 'SaturdayHoliday': return day.weekday() >= 5 or holiday
    if kind == 'Saturday': return day.weekday() == 5 and not holiday
    if kind == 'SundayHoliday': return day.weekday() == 6 or holiday
    if kind == 'Holiday': return bool(holiday) or day.weekday() == 6
    if kind == 'Sunday': return day.weekday() == 6 and not holiday
    # Unknown/special calendars MUST NOT be interpreted as daily services.
    try: return date.fromisoformat(kind) == day
    except ValueError: return False


def stop_offsets(objects, service_day_start_hour=3):
    """ODPT HH:mm wraps at midnight. Early morning belongs to previous service day.

    Missing arrival at an intermediate stop uses published departure time as a
    conservative arrival upper bound; callers expose this approximation.
    """
    result, previous = [], None
    for obj in objects:
        station = obj.get('odpt:departureStation') or obj.get('odpt:arrivalStation')
        a, d = obj.get('odpt:arrivalTime'), obj.get('odpt:departureTime')
        if not station or not (a or d):
            raise TransitDataError('列車時刻表に駅または時刻がありません。')
        vals = []
        for raw in (a or d, d or a):
            try:
                h, m = map(int, raw.split(':'))
                if not 0 <= h <= 47 or not 0 <= m <= 59: raise ValueError()
            except (ValueError, AttributeError):
                raise TransitDataError('不正な時刻表時刻です。') from None
            v = h * 3600 + m * 60
            if previous is None and h < service_day_start_hour: v += 86400
            while previous is not None and v < previous: v += 86400
            if previous is not None and v - previous > 12 * 3600:
                raise TransitDataError('時刻表の並びまたは日付またぎが不正です。')
            previous = v
            vals.append(v)
        result.append((station, vals[0], vals[1], a is None))
    return result


@dataclass(frozen=True)
class Ride:
    origin: str
    destination: str
    departure: datetime
    arrival: datetime
    operator: str
    railway: str
    trip: str
    arrival_estimated: bool = False
    station_timetable_proxy: bool = False


@dataclass(frozen=True)
class Transfer:
    origin: str
    destination: str
    seconds: int = 300
    estimated: bool = True


class ScheduledRouter:
    def __init__(self, rides, fares, transfers=(), minimum_transfer_seconds=180,
                 max_boardings=3, max_expansions=1000000, single_operator_only=False):
        self.single_operator_only = single_operator_only
        self.incoming = defaultdict(list)
        for ride in rides:
            if ride.arrival < ride.departure: raise TransitDataError('到着時刻が出発より前です。')
            self.incoming[ride.destination].append(ride)
        for values in self.incoming.values(): values.sort(key=lambda r: r.departure, reverse=True)
        self.fares = fares
        self.transfers = defaultdict(list)
        for link in transfers:
            if link.seconds <= 0: raise TransitDataError('乗換時間は正数が必要です。')
            self.transfers[link.destination].append(link)
        self.minimum_transfer_seconds = minimum_transfer_seconds
        self.max_boardings = max_boardings
        self.max_expansions = max_expansions

    def quote_fare(self, rides):
        if not rides: return 0, 'known'
        groups = []
        for ride in rides:
            if groups and groups[-1][-1].operator == ride.operator:
                groups[-1].append(ride)
            else: groups.append([ride])
        amounts = []
        for group in groups:
            value = self.fares.get((group[0].operator, group[0].origin, group[-1].destination))
            if value is None: return None, 'unavailable'
            amounts.append(value)
        # Separate operator tickets may not capture discounts/through fares.
        if len(groups) > 1: return None, 'cross_operator_unavailable'
        return sum(amounts), 'known'

    def arrive_by(self, origin, destination, meeting_at, lookback_hours=6):
        meeting = japan_datetime(meeting_at)
        if not 0 < lookback_hours <= 24: raise TransitDataError('探索時間は0時間超〜24時間です。')
        start = meeting - timedelta(hours=lookback_hours)
        origins = {origin} if isinstance(origin,str) else set(origin)
        if origin == destination:
            return [dict(origin=origin,destination=destination,duration_minutes=0,
                         travel_duration_minutes=0,early_wait_minutes=0,transfer_minutes=0,
                         fare_yen=0,fare_status='known',departure_at=meeting.isoformat(),
                         arrival_at=meeting.isoformat(),legs=[],source='same_station')]
        results, expansions = [], 0
        best_routes = {}
        def record_route(route):
            if self.single_operator_only:
                key=(route['origin'],route['legs'][0]['operator'])
                if key not in best_routes or route['duration_minutes'] < best_routes[key]['duration_minutes']:
                    best_routes[key]=route
            else: results.append(route)
        best_latest = {}
        queue, sequence = [], itertools.count()
        pending_latest = {}
        def enqueue(station,latest,reverse_rides,visited,links,change_seconds):
            if len(reverse_rides)>=self.max_boardings or latest < start: return
            key = (station,len(reverse_rides),reverse_rides[-1].operator if reverse_rides else None) if self.single_operator_only else (station,len(reverse_rides),tuple(r.operator for r in reverse_rides),frozenset(visited),reverse_rides[-1].trip if reverse_rides else None)
            if latest <= pending_latest.get(key,start-timedelta(seconds=1)): return
            pending_latest[key] = latest
            heapq.heappush(queue,(-latest.timestamp(),next(sequence),(station,latest,reverse_rides,visited,links,change_seconds)))

        def visit(station, latest, reverse_rides, visited, links, change_seconds):
            nonlocal expansions
            state = (station,len(reverse_rides),reverse_rides[-1].operator if reverse_rides else None) if self.single_operator_only else (station, len(reverse_rides), tuple(r.operator for r in reverse_rides), frozenset(visited), reverse_rides[-1].trip if reverse_rides else None)
            if latest <= best_latest.get(state, start-timedelta(seconds=1)): return
            best_latest[state] = latest
            expansions += 1
            if expansions > self.max_expansions: raise SearchLimitError('時刻表探索上限に達しました。候補・探索時間・乗車回数を減らしてください。')
            if len(reverse_rides) >= self.max_boardings: return
            for ride in self.incoming.get(station, ()):
                expansions += 1
                if expansions > self.max_expansions: raise SearchLimitError('時刻表探索上限に達しました。探索時間・乗車回数を減らしてください。')
                if not start <= ride.departure or ride.arrival > latest or (not self.single_operator_only and ride.origin in visited): continue
                if reverse_rides and self.single_operator_only and ride.operator != reverse_rides[-1].operator: continue
                if not self.single_operator_only and reverse_rides and ride.trip == reverse_rides[-1].trip: continue
                chain = reverse_rides + [ride]
                if ride.origin in origins:
                    ordered = list(reversed(chain))
                    fare, status = self.quote_fare(ordered)
                    arrival, departure = ordered[-1].arrival, ordered[0].departure
                    transfer_time = sum((b.departure-a.arrival).total_seconds() for a,b in zip(ordered,ordered[1:]))
                    record_route(dict(origin=ride.origin,destination=destination,
                        duration_minutes=(meeting-departure).total_seconds()/60,
                        travel_duration_minutes=(arrival-departure).total_seconds()/60,
                        early_wait_minutes=(meeting-arrival).total_seconds()/60,
                        transfer_minutes=transfer_time/60,fare_yen=fare,fare_status=status,
                        departure_at=departure.isoformat(),arrival_at=arrival.isoformat(),
                        legs=[dict(origin=r.origin,destination=r.destination,departure_at=r.departure.isoformat(),arrival_at=r.arrival.isoformat(),operator=r.operator,railway=r.railway,trip=r.trip,arrival_estimated=r.arrival_estimated,station_timetable_proxy=r.station_timetable_proxy) for r in ordered],
                        transfer_time_estimated=bool(links) or len(ordered)>1,
                        source='ODPT StationTimetable reconstructed (departure-time arrival proxy) + RailwayFare' if any(r.station_timetable_proxy for r in ordered) else 'ODPT scheduled TrainTimetable + RailwayFare'))
                seen = visited | {ride.origin}
                enqueue(ride.origin, ride.departure-timedelta(seconds=self.minimum_transfer_seconds), chain, seen, links, change_seconds)
                for link in self.transfers.get(ride.origin, ()):
                    if self.single_operator_only or link.origin not in seen:
                        enqueue(link.origin,ride.departure-timedelta(seconds=link.seconds),chain,seen|{link.origin},links+[link],change_seconds+link.seconds)
        enqueue(destination,meeting,[],{destination},[],0)
        while queue:
            _,_,state = heapq.heappop(queue)
            visit(*state)
        if self.single_operator_only: results = list(best_routes.values())
        known = [r for r in results if r['fare_yen'] is not None]
        frontier = [r for r in known if not any(o['origin'] == r['origin'] and (o['duration_minutes'] <= r['duration_minutes'] and o['fare_yen'] <= r['fare_yen']) and (o['duration_minutes'] < r['duration_minutes'] or o['fare_yen'] < r['fare_yen']) for o in known)]
        # Keep unknown fares separately, never treat them as zero-cost routes.
        unknown = [r for r in results if r['fare_yen'] is None]
        for oid in origins:
            choices = [r for r in unknown if r['origin']==oid]
            if choices: frontier.append(min(choices,key=lambda r:r['duration_minutes']))
        if destination in origins and not isinstance(origin,str):
            frontier.extend(self.arrive_by(destination,destination,meeting,lookback_hours))
        unique = {}
        for route in frontier:
            key = (route['origin'],route['duration_minutes'],route['fare_yen'],route['fare_status'])
            unique.setdefault(key,route)
        return sorted(unique.values(),key=lambda r:(r['duration_minutes'],r['fare_yen'] if r['fare_yen'] is not None else float('inf')))
