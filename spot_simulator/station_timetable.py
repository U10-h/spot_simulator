"""Conservative, opt-in reconstruction from identified station departures.

No nearest-departure matching. Missing terminal arrivals stay missing. Only simple,
monotonic portions of a published railway order are supported; ambiguous groups
(including loops, reused IDs and conflicting timetable versions) are discarded.
"""
from collections import defaultdict, Counter
import re


def _minute(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{2}:\d{2}', value):
        raise ValueError('invalid time')
    hour, minute = map(int, value.split(':'))
    if hour > 26 or minute > 59:
        raise ValueError('invalid time')
    # Match the router's Japanese service-day convention.
    if hour < 3:
        hour += 24
    return hour * 60 + minute


def reconstruct_station_timetables(records, railways=None):
    """Return (ODPT-shaped departure-only trips, human-readable warnings).

    ``railways`` is an iterable of ODPT Railway records. Station order is required;
    a train ID is required on every usable departure. Train numbers alone are not
    identity. A change of direction label does not break an otherwise valid trip.
    This deliberately trades coverage for avoiding invented journeys.
    """
    orders = {}
    for railway in railways or []:
        line = railway.get('owl:sameAs')
        entries = railway.get('odpt:stationOrder') or []
        try:
            indices = {entry['odpt:station']: int(entry['odpt:index']) for entry in entries}
            if (not line or len(indices) != len(entries)
                    or len(set(indices.values())) != len(entries)):
                continue
            orders[line] = indices
        except (KeyError, TypeError, ValueError):
            continue
    groups = defaultdict(list)
    rejected = Counter()
    for row in records:
        op, line, calendar, station = (row.get(k) for k in
            ('odpt:operator', 'odpt:railway', 'odpt:calendar', 'odpt:station'))
        if not all(isinstance(v, str) and v for v in (op, line, calendar, station)):
            rejected['駅時刻表の事業者・路線・運行日・駅が不明'] += 1
            continue
        for event in row.get('odpt:stationTimetableObject', []):
            train = event.get('odpt:train')
            if not isinstance(train, str) or not train.startswith('odpt.Train:'):
                rejected['列車IDがない発車記録'] += 1
                continue
            groups[(op, line, calendar, train)].append((row, event))
    result = []
    for (op, line, calendar, train), events in groups.items():
        try:
            order = orders.get(line)
            if not order:
                raise ValueError('路線の駅順を確認できない列車')
            points = []
            metadata = set()
            for row, event in events:
                station = row['odpt:station']
                if station not in order:
                    raise ValueError('駅順に存在しない停車駅')
                departure = event.get('odpt:departureTime')
                minute = _minute(departure)
                destination = event.get('odpt:destinationStation')
                if not isinstance(destination, list) or not destination or not all(isinstance(v, str) and v for v in destination):
                    raise ValueError('行先情報が不明な列車')
                metadata.add((event.get('odpt:trainType'), tuple(destination),
                              row.get('dct:issued'), row.get('dct:valid')))
                points.append((minute, station, departure))
            if len(metadata) != 1:
                raise ValueError('種別・行先・有効期間が競合する列車')
            if len(points) < 2:
                raise ValueError('発車記録が2駅未満の列車')
            if len({p[1] for p in points}) != len(points):
                raise ValueError('同じ駅で列車IDが重複する列車')
            points.sort()
            if len({p[0] for p in points}) != len(points):
                raise ValueError('複数駅で時刻が重複する列車')
            # Huge gaps may join separate uses of a train ID. This is a
            # conservative coverage limit, not an estimated running time.
            if points[-1][0] - points[0][0] > 240 or any(
                    b[0] - a[0] > 60 for a, b in zip(points, points[1:])):
                raise ValueError('列車IDの連続性を確認できない列車')
            positions = [order[p[1]] for p in points]
            diffs = [b-a for a,b in zip(positions, positions[1:])]
            if not (all(d > 0 for d in diffs) or all(d < 0 for d in diffs)):
                raise ValueError('駅順が循環・逆転する列車')
            train_type, destinations, issued, valid = next(iter(metadata))
            direction = 1 if diffs[0] > 0 else -1
            # The destination need not have a departure record, but a known
            # same-line destination must lie beyond the last observed stop.
            # Off-line destinations cannot be validated by this line's order;
            # do not add an inferred continuation to them.
            if any(destination in order and
                   (order[destination] - positions[-1]) * direction <= 0
                   for destination in destinations):
                raise ValueError('行先が停車順と整合しない列車')
            if not isinstance(train_type, str) or not train_type:
                raise ValueError('列車種別が不明な列車')
            trip = {'owl:sameAs': 'station-derived:' + '|'.join((op,line,calendar,train)),
                    'odpt:operator': op, 'odpt:railway': line,
                    'odpt:calendar': calendar, 'odpt:train': train,
                    'odpt:trainType': train_type,
                    'odpt:destinationStation': list(destinations),
                    'odpt:trainTimetableObject': [
                        {'odpt:departureStation': station, 'odpt:departureTime': departure}
                        for _, station, departure in points],
                    'x:stationTimetableProxy': True,
                    'source_generated_dates': sorted({row['dc:date'] for row, _ in events
                        if isinstance(row.get('dc:date'), str) and row['dc:date']}),
                    'source_timetable_ids': sorted({row['owl:sameAs'] for row, _ in events
                        if isinstance(row.get('owl:sameAs'), str) and row['owl:sameAs']}),
                    'spot:source': 'station_timetable_departure_proxy'}
            if issued: trip['dct:issued'] = issued
            if valid: trip['dct:valid'] = valid
            result.append(trip)
        except (ValueError, TypeError) as exc:
            rejected[str(exc)] += 1
    warnings = []
    if result:
        warnings.append(f'駅時刻表から列車IDを照合した{len(result)}列車は、発車時刻を到着時刻の代用にしています。終着駅の到着時刻は補完していません。')
    warnings.extend(f'駅時刻表から除外: {reason}（{count}件）' for reason,count in sorted(rejected.items()))
    return result, warnings
