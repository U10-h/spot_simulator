"""Server-side ODPT timetable adapter; no real-time data and no paid APIs.

Raw Basic License responses stay in process memory and are never served or saved.
Public source: https://api-public.odpt.org/api/v4 (Toei, CC BY 4.0).
Registered source: https://api.odpt.org/api/v4 (ODPT_API_KEY environment only).
"""
from datetime import datetime, timedelta, time
from functools import lru_cache
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from .transit import (JST, Ride, Transfer, ScheduledRouter, TransitDataError,
                      japan_datetime, calendar_matches, stop_offsets)

OPERATORS = {'Toei':'東京都交通局', 'TokyoMetro':'東京メトロ', 'TWR':'東京臨海高速鉄道',
             'MIR':'首都圏新都市鉄道（つくばエクスプレス）', 'TamaMonorail':'多摩都市モノレール','Yurikamome':'ゆりかもめ（駅時刻表補完・要APIキー）'}
FETCHED_AT = {}
ALLOWED_TYPES = {'Station','TrainTimetable','RailwayFare','Railway','Calendar','StationTimetable'}


def provider_status():
    key = bool(os.environ.get('ODPT_API_KEY'))
    return dict(live_available=True,provider='ODPT timetable-only',
        message='都営の公開時刻表APIを利用します。登録APIキーがある場合は対応事業者を追加できます。実データの取得成功・対象日を確認してから計算します。',
        coverage=['Toei'] if not key else list(OPERATORS),
        api_key_configured=key, realtime=False, attribution='東京都交通局・公共交通オープンデータ協議会',
        license_url='https://creativecommons.org/licenses/by/4.0/')


def _download(kind, operator):
    if kind not in ALLOWED_TYPES or operator not in OPERATORS:
        raise TransitDataError('未対応のODPTデータ種別または事業者です。')
    key = os.environ.get('ODPT_API_KEY')
    if operator != 'Toei' and not key:
        raise TransitDataError('この事業者にはサーバー側 ODPT_API_KEY が必要です。')
    public = operator == 'Toei'
    base = 'https://api-public.odpt.org/api/v4/' if public else 'https://api.odpt.org/api/v4/'
    query = {} if kind == 'Calendar' else {'odpt:operator':'odpt.Operator:'+operator}
    if not public: query['acl:consumerKey'] = key
    req = Request(base+'odpt:'+kind+'.json?'+urlencode(query),headers={'Accept':'application/json','User-Agent':'spot-simulator-timetable/1.0'})
    try:
        with urlopen(req,timeout=30) as response:
            raw = response.read(50_000_001)
            if len(raw)>50_000_000: raise TransitDataError('ODPTレスポンスがサイズ上限を超えました。')
            values = json.loads(raw)
    except (HTTPError,URLError,TimeoutError,json.JSONDecodeError):
        # Never expose request URLs: private API URLs contain consumer keys.
        raise TransitDataError('ODPTデータを取得できませんでした。接続・API利用権限を確認してください。') from None
    if not isinstance(values,list): raise TransitDataError('ODPTレスポンス形式が不正です。')
    FETCHED_AT[(kind,operator)] = datetime.now(JST).isoformat()
    return values if kind == 'Calendar' else [row for row in values if row.get('odpt:operator') == 'odpt.Operator:'+operator]


@lru_cache(maxsize=20)
def _cached_download(kind, operator, hour_bucket):
    return _download(kind,operator)


def _get(kind, operator):
    return _cached_download(kind,operator,int(datetime.now().timestamp()//3600))


def _valid(record, day):
    """Reject records outside their published validity; absent expiry is reported."""
    for key, lower in [('dct:issued',True),('dct:valid',False)]:
        value = record.get(key)
        if not value: continue
        try: boundary = datetime.fromisoformat(value.replace('Z','+00:00')).date() if 'T' in value else datetime.strptime(value[:10],'%Y-%m-%d').date()
        except (ValueError,TypeError): return False
        if (lower and day < boundary) or (not lower and day > boundary): return False
    return True


def tokyo_station(s):
    op = s.get('odpt:operator','').split(':')[-1]
    name = (s.get('odpt:stationTitle') or {}).get('ja') or s.get('dc:title')
    if op == 'Toei': return name != '本八幡'
    if op == 'TokyoMetro': return name not in {'和光市','浦安','南行徳','行徳','妙典','原木中山','西船橋'}
    if op == 'MIR': return name in {'秋葉原','新御徒町','浅草','南千住','北千住','青井','六町'}
    return op in {'TWR','TamaMonorail','Yurikamome'}

def station_catalog(operators=None):
    operators = operators or ['Toei']
    stations = {}
    for op in operators:
        for row in _get('Station',op):
            if not tokyo_station(row): continue
            sid = row.get('owl:sameAs')
            if not sid: continue
            title = row.get('odpt:stationTitle') or {}
            stations[sid] = dict(id=sid,name=title.get('ja') or row.get('dc:title') or sid,
                operator=op,railway=row.get('odpt:railway'),latitude=row.get('geo:lat'),longitude=row.get('geo:long'))
    return list(stations.values())


def build_route_matrix(payload):
    if not isinstance(payload,dict): raise TransitDataError('入力形式が不正です。')
    meeting = japan_datetime(payload.get('meeting_at'))
    operators = payload.get('operators',['Toei'])
    if not isinstance(operators,list) or not operators or any(op not in OPERATORS for op in operators):
        raise TransitDataError('未対応の事業者です。Toei, TokyoMetro, TWR, MIR, TamaMonorail を指定できます。')
    if (meeting.month == 12 and meeting.day >= 29) or (meeting.month == 1 and meeting.day <= 3):
        raise TransitDataError('年末年始の特別運行日を確定できないため、この期間は未対応です。')
    lookback = payload.get('lookback_hours',6)
    boardings = payload.get('max_boardings',2)
    if isinstance(lookback,bool) or not isinstance(lookback,(float,int)) or not 0 < lookback <= 24: raise TransitDataError('探索時間は0時間超〜24時間です。')
    if isinstance(boardings,bool) or not isinstance(boardings,int) or not 1 <= boardings <= 3: raise TransitDataError('最大乗車回数は1〜3です。')
    people,candidates = payload.get('participants'),payload.get('candidate_stations') or []
    automatic = not candidates
    use_fallback = payload.get('use_station_timetable_fallback',False)
    if 'Yurikamome' in operators and not use_fallback: raise TransitDataError('ゆりかもめは駅時刻表補完を有効にした場合のみ対応します。列車IDの確認結果によっては経路を作成できません。')
    if not isinstance(use_fallback,bool): raise TransitDataError('駅時刻表補完の指定が不正です。')
    if not isinstance(people,list) or not 1 <= len(people) <= 12 or not isinstance(candidates,list) or not 0 <= len(candidates) <= 500:
        raise TransitDataError('参加者1〜12人、候補駅は最大500駅を指定してください。')
    if not all(isinstance(v,str) for v in candidates): raise TransitDataError('候補駅は文字列で指定してください。')
    requested = set(candidates)
    for p in people:
        if not isinstance(p,dict) or not isinstance(p.get('origins'),list) or not 1 <= len(p['origins']) <= 10: raise TransitDataError('出発駅を1〜10駅指定してください。')
        if not all(isinstance(v,str) for v in p['origins']): raise TransitDataError('出発駅は文字列で指定してください。')
        requested.update(p['origins'])
    if not all(isinstance(v,str) for v in requested): raise TransitDataError('駅はODPT駅IDで指定してください。')
    stations, timetables, fares_raw = [], [], []
    from concurrent.futures import ThreadPoolExecutor
    requests = [(kind,op) for op in dict.fromkeys(operators) for kind in (['Station','TrainTimetable','RailwayFare']+(['StationTimetable','Railway'] if use_fallback else []))]+[('Calendar','Toei')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = dict(zip(requests,pool.map(lambda item:_get(*item),requests)))
    for op in dict.fromkeys(operators):
        stations += fetched['Station',op]
        timetables += fetched['TrainTimetable',op]
        fares_raw += fetched['RailwayFare',op]
    reconstruction_warnings = []
    reconstruction_count = 0
    if use_fallback:
        from .station_timetable import reconstruct_station_timetables
        for op in dict.fromkeys(operators):
            reconstructed, notices = reconstruct_station_timetables(fetched['StationTimetable',op],fetched['Railway',op])
            reconstruction_warnings.extend(notices)
            native_keys = {(r.get('odpt:operator'),r.get('odpt:railway'),str(r.get('odpt:calendar')),r.get('odpt:train')) for r in timetables}
            for row in reconstructed:
                key=(row.get('odpt:operator'),row.get('odpt:railway'),str(row.get('odpt:calendar')),row.get('odpt:train'))
                if key not in native_keys:
                    row={**row,'x:stationTimetableProxy':True}
                    timetables.append(row)
                    reconstruction_count+=1
    ids = {s.get('owl:sameAs') for s in stations}
    tokyo_ids = {s.get('owl:sameAs') for s in stations if tokyo_station(s)}
    aliases = {sid: [sid] for sid in tokyo_ids if sid}
    for s in stations:
        label = (s.get('odpt:stationTitle') or {}).get('ja') or s.get('dc:title')
        if label and s['owl:sameAs'] in tokyo_ids and s['owl:sameAs'] not in aliases.get(label,[]): aliases.setdefault(label, []).append(s['owl:sameAs'])
    if automatic:
        candidates = sorted(tokyo_ids - {None})
        if len(candidates)>500: raise TransitDataError('自動検出した集合候補駅が500駅を超えました。事業者を絞ってください。')
    if requested - aliases.keys(): raise TransitDataError('駅名・IDが対応事業者の公開駅データにありません: '+', '.join(sorted(requested-aliases.keys())))
    for value in requested:
        if len(aliases[value]) > 1:
            raise TransitDataError('同名の駅・路線があります。駅IDで選択してください: '+value+' → '+', '.join(aliases[value]))
    station_labels = {s['owl:sameAs']: ((s.get('odpt:stationTitle') or {}).get('ja') or s.get('dc:title') or s['owl:sameAs'])+'（'+str(s.get('odpt:railway','')).split(':')[-1]+'）' for s in stations if s.get('owl:sameAs') in tokyo_ids}
    calendar_records = {r.get('owl:sameAs'):r for r in fetched['Calendar','Toei']}
    def matches(calendar, day):
        record = calendar_records.get(calendar,{})
        if 'odpt:day' in record: return day.isoformat() in record['odpt:day']
        return calendar_matches(calendar,day)
    start = meeting-timedelta(hours=lookback)
    days = [start.date()-timedelta(days=1)+timedelta(days=i) for i in range((meeting.date()-start.date()).days+2)]
    rides, missing_calendar, missing_expiry, rejected = [], 0, 0, 0
    for row in timetables:
        train_type = str(row.get('odpt:trainType','')).split('.')[-1]
        if train_type not in {'Local','Rapid','Express','RapidExpress','CommuterRapid','CommuterExpress','SemiExpress','AirportRapid','AccessExpress','LimitedExpress','AirportLimitedExpress'}:
            rejected += 1; continue
        if train_type in {'LimitedExpress','AirportLimitedExpress'} and row.get('odpt:operator') != 'odpt.Operator:Toei':
            rejected += 1; continue
        if not row.get('dct:valid'): missing_expiry += 1
        calendar = row.get('odpt:calendar')
        if not calendar: missing_calendar += 1; continue
        if isinstance(calendar,list): calendars=calendar
        else: calendars=[calendar]
        try: stops = stop_offsets(row.get('odpt:trainTimetableObject',[]))
        except TransitDataError: rejected += 1; continue
        for day in days:
            if not _valid(row,day) or not any(matches(c,day) for c in calendars): continue
            midnight = datetime.combine(day,time(),JST)
            for i, (origin,_,departure,_) in enumerate(stops[:-1]):
                depart = midnight+timedelta(seconds=departure)
                if not start <= depart <= meeting: continue
                for destination, arrival, _, estimate in stops[i+1:]:
                    arrive = midnight+timedelta(seconds=arrival)
                    if arrive>meeting: break
                    expiry = row.get('dct:valid')
                    if expiry and 'T' in expiry:
                        try:
                            if arrive > japan_datetime(expiry): continue
                        except TransitDataError: continue
                    if origin==destination: continue
                    rides.append(Ride(origin,destination,depart,arrive,row.get('odpt:operator',''),row.get('odpt:railway',''),str(row.get('owl:sameAs') or row.get('@id'))+'@'+str(day),estimate,bool(row.get('x:stationTimetableProxy'))))
    fares={}
    for row in fares_raw:
        if not _valid(row,meeting.date()): continue
        if row.get('dct:valid') and 'T' in row['dct:valid']:
            try:
                if meeting > japan_datetime(row['dct:valid']): continue
            except TransitDataError: continue
        # Ordinary adult cash fare, not IC: never silently mix fare products.
        fare=row.get('odpt:ticketFare')
        if isinstance(fare,int) and not isinstance(fare,bool) and fare>=0:
            key=(row.get('odpt:operator'),row.get('odpt:fromStation'),row.get('odpt:toStation'))
            if key in fares and fares[key]!=fare: raise TransitDataError('同じ区間に複数の運賃があります。対象条件の確認が必要です。')
            fares[key]=fare
    transfers=[]
    for station in stations:
        origin=station.get('owl:sameAs')
        for target in station.get('odpt:connectingStation',[]):
            if target in ids: transfers.append(Transfer(origin,target,300,True))
    router=ScheduledRouter(rides,fares,transfers,max_boardings=boardings,single_operator_only=True)
    routes,warnings=[],[
        '時刻表のみを使用。遅延・運休などのリアルタイム情報は取得していません。',
        '時間目的は集合日時−出発日時です。到着後の待ち時間も含み、移動時間と分けて表示します。',
        '特別料金が必要な列車・列車種別未確認の列車は対象外です。',
        '運賃は大人普通運賃（現金）。事業者をまたぐ運賃・割引・追加料金は未対応のため最適化から除外します。',
        '乗換は同一駅3分・接続駅5分の仮定です。時刻表に到着時刻がない駅は発車時刻を到着の上限として使用します。',
        '起終点は指定駅のホームです。起終点での接続駅間徒歩は含めません。',
        '深夜0〜3時の始発便は前日の運行日として解釈します。運行日境界は仮定です。',
        '対象は取得できた事業者・時刻表・候補駅のみです。東京全駅や全国の網羅性は保証しません。',
        '東京都交通局・公共交通オープンデータ協議会（都営データ: CC BY 4.0）。その他のデータはODPT基本ライセンス。']
    warnings.extend(reconstruction_warnings)
    if use_fallback: warnings.append(f'駅時刻表補完: 安定した列車IDと路線の駅順で確認できた{reconstruction_count}便のみ利用。発車時刻を到着時刻の代用にし、未掲載の終着駅は補いません。')
    unknown=0
    import time as clock
    deadline = clock.monotonic()+90
    all_origins = {oid for person in people for origin in person['origins'] for oid in aliases[origin]}
    for destination in candidates:
        for destination_id in aliases[destination]:
            if clock.monotonic()>deadline: raise TransitDataError('時刻表検索の全体時間上限に達しました。探索時間・乗車回数・事業者を減らしてください。部分結果は返していません。')
            found = router.arrive_by(all_origins,destination_id,meeting,lookback)
            for route in found:
                if route['fare_yen'] is None: unknown+=1; continue
                for person in people:
                    for origin in person['origins']:
                        if route['origin'] in aliases[origin]:
                            routes.append({**route,'participant_id':person['id'],'origin':origin,'destination':destination,'origin_id':route['origin'],'destination_id':destination_id})
    if unknown: warnings.append(f'運賃未確定の経路を除外しました（{unknown}件）。')
    if any(not r.get('dct:valid') for r in fares_raw): warnings.append('一部運賃に有効期限がありません。運賃改定が反映されているか保証できません。')
    if missing_expiry: warnings.append('一部時刻表に有効期限がありません。指定日のダイヤ変更を保証できません。')
    if missing_calendar or rejected: warnings.append(f'適用日不明または不正な時刻表を除外しました（{missing_calendar+rejected}件）。')
    if not rides: warnings.append('指定日時に利用可能な列車時刻表がありません。')
    return {**payload,'candidate_stations':candidates,'routes':routes,'provider_warnings':warnings,'provider_metadata':dict(provider='ODPT scheduled',realtime=False,operators=operators,station_timetable_fallback=use_fallback,reconstructed_trip_count=reconstruction_count,station_labels=station_labels,candidate_count=len(candidates),candidate_discovery='auto' if automatic else 'manual',lookback_hours=lookback,max_boardings=boardings,single_operator_only=True,tokyo_endpoints_only=True,computed_at=datetime.now(JST).isoformat(),fetched_at={f'{kind}:{op}':FETCHED_AT.get((kind,op)) for op in operators for kind in (['Station','TrainTimetable','RailwayFare']+(['StationTimetable','Railway'] if use_fallback else []))},station_timetable_generated_dates=sorted({str(d) for r in timetables for d in r.get('source_generated_dates',[])}),timetable_generated_dates=sorted({str(r.get('dc:date')) for r in timetables if r.get('dc:date')}),timetable_revision_dates=sorted({str(r.get('dct:issued')) for r in timetables if r.get('dct:issued')}),timetable_expiry_missing=missing_expiry,fare_generated_dates=sorted({str(r.get('dc:date')) for r in fares_raw if r.get('dc:date')}),fare_revision_dates=sorted({str(r.get('dct:issued')) for r in fares_raw if r.get('dct:issued')}),fare_expiry_missing=sum(not r.get('dct:valid') for r in fares_raw),fare_product='adult_cash',time_objective='meeting_at - departure_at',raw_data_redistributed=False)}
