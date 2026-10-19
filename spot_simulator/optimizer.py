"""Exact epsilon-constraint MILP over a finite, supplied route matrix.

Integer objective coefficients avoid a weighted-sum approximation of the frontier.
Each participant chooses one origin/route to a common meeting station. An origin
is an alternative departure station, not an additional traveller.
"""
import math
import warnings
from time import monotonic
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp


class ValidationError(ValueError):
    pass


class OptimizationLimitError(RuntimeError):
    pass


def number(value, name, low, high):
    if isinstance(value, bool):
        raise ValidationError(f'{name}: 数値を指定してください。')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError(f'{name}: 数値を指定してください。') from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValidationError(f'{name}: {low}〜{high}で指定してください。')
    return result


def text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValidationError(f'{name}: 1〜200文字の文字列が必要です。')
    return value.strip()


def names(value, name, maximum):
    if not isinstance(value, list) or not 1 <= len(value) <= maximum:
        raise ValidationError(f'{name}: 1〜{maximum}件で指定してください。')
    items = [text(x, name) for x in value]
    if len(set(items)) != len(items):
        raise ValidationError(f'{name}: 重複を取り除いてください。')
    return items


def weight(value):
    n = number(value, '重み', 0, 1)
    if abs(n * 1000 - round(n * 1000)) > 1e-7:
        raise ValidationError('重みは小数点以下3桁までです。')
    return round(n * 1000)


def validate(payload):
    if not isinstance(payload, dict):
        raise ValidationError('JSONオブジェクトを指定してください。')
    people = payload.get('participants')
    if not isinstance(people, list) or not 1 <= len(people) <= 12:
        raise ValidationError('参加者は1〜12人です。')
    participants = []
    for p in people:
        if not isinstance(p, dict):
            raise ValidationError('参加者の形式が不正です。')
        tw, fw = weight(p.get('time_weight')), weight(p.get('fare_weight'))
        if tw + fw != 1000:
            raise ValidationError('各参加者の時間・運賃の重みの合計を1にしてください。')
        participants.append(dict(id=text(p.get('id'), '参加者ID'), name=text(p.get('name'), '名前'), origins=names(p.get('origins'), '出発駅', 10), tw=tw, fw=fw))
    by_id = {p['id']: p for p in participants}
    if len(by_id) != len(participants):
        raise ValidationError('参加者IDは一意である必要があります。')
    stations = names(payload.get('candidate_stations'), '集合候補駅', 500)
    routes = payload.get('routes')
    if not isinstance(routes, list) or len(routes) > 10000:
        raise ValidationError('routesは最大10,000件の配列で指定してください。')
    valid = []
    for r in routes:
        if not isinstance(r, dict):
            raise ValidationError('経路の形式が不正です。')
        participant_id = text(r.get('participant_id'), '経路の参加者ID')
        p = by_id.get(participant_id)
        if p is None or r.get('origin') not in p['origins'] or r.get('destination') not in stations:
            raise ValidationError('経路の参加者・出発駅・集合駅が入力と一致しません。')
        minutes = number(r.get('duration_minutes'), '所要時間', 0, 2880)
        seconds = round(minutes * 60)
        if abs(minutes * 60 - seconds) > 1e-6:
            raise ValidationError('所要時間は1秒単位で指定してください。')
        fare = number(r.get('fare_yen'), '運賃', 0, 100000)
        if not fare.is_integer():
            raise ValidationError('運賃は整数円で指定してください。')
        transfer = number(r.get('transfer_minutes'), '乗換時間', 0, minutes)
        source = text(r.get('source'), '経路の出典')
        valid.append({**r, 'duration_minutes': minutes, 'fare_yen': int(fare), 'transfer_minutes': transfer, 'source': source, '_time': p['tw'] * seconds, '_fare': p['fw'] * int(fare)})
    ts = number(payload.get('time_scale_minutes', 60), '時間の正規化基準', 1, 2880)
    fs = number(payload.get('fare_scale_yen', 1000), '運賃の正規化基準', 1, 100000)
    return participants, stations, valid, ts, fs


def optimize(payload, max_points=500, timeout_seconds=20):
    people, stations, routes, ts, fs = validate(payload)
    deadline = monotonic() + timeout_seconds
    candidates, excluded = [], []
    solve_count = 0
    for station in stations:
        choices = [r for r in routes if r['destination'] == station]
        missing = [p['name'] for p in people if not any(r['participant_id'] == p['id'] for r in choices)]
        if missing:
            excluded.append({'station': station, 'reason': '経路データ不足: ' + '、'.join(missing)})
            continue
        n = len(choices)
        a = np.array([[float(r['participant_id'] == p['id']) for r in choices] for p in people])
        t, f = np.array([r['_time'] for r in choices]), np.array([r['_fare'] for r in choices])
        base = LinearConstraint(a, np.ones(len(people)), np.ones(len(people)))

        def solve(objective, extra):
            nonlocal solve_count
            remaining = deadline - monotonic()
            if remaining <= 0 or solve_count >= max_points * 3 + len(stations):
                raise OptimizationLimitError('探索上限に達しました。候補駅・経路数を減らしてください。完全な結果は返していません。')
            solve_count += 1
            # Large integer coefficients need tighter integrality tolerance than HiGHS defaults.
            # SciPy forwards this documented HiGHS option with a wrapper warning.
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='Unrecognized options detected:.*', category=RuntimeWarning)
                result = milp(c=objective.astype(float), integrality=np.ones(n), bounds=Bounds(np.zeros(n), np.ones(n)), constraints=[base, *extra], options={'time_limit': remaining, 'mip_rel_gap': 0, 'mip_feasibility_tolerance': 1e-10})
            if result.status == 2:
                return None
            if result.status != 0:
                raise OptimizationLimitError('最適性を確認できませんでした。候補を減らして再実行してください。')
            selected = np.rint(result.x).astype(int)
            if not np.allclose(a @ selected, 1) or np.any((selected != 0) & (selected != 1)):
                raise OptimizationLimitError('整数解の検証に失敗しました。')
            for constraint in extra:
                value = np.asarray(constraint.A) @ selected
                if np.any(value < constraint.lb) or np.any(value > constraint.ub):
                    raise OptimizationLimitError('整数解の目的制約の検証に失敗しました。')
            return selected

        fare_bound = None
        while True:
            extra = [] if fare_bound is None else [LinearConstraint(f, -np.inf, fare_bound)]
            x = solve(t, extra)
            if x is None:
                break
            best_t = int(t @ x)
            x = solve(f, [*extra, LinearConstraint(t, -np.inf, best_t)])
            if x is None:
                raise OptimizationLimitError('辞書式最適化の検証に失敗しました。')
            ti, fi = int(t @ x), int(f @ x)
            if ti > best_t or (fare_bound is not None and fi > fare_bound):
                raise OptimizationLimitError('目的関数の数値検証に失敗しました。')
            selected = [{k: v for k, v in r.items() if not k.startswith('_')} for r, yes in zip(choices, x) if yes]
            candidates.append({'station': station, 'time_objective': ti / (1000 * 60 * ts), 'fare_objective': fi / (1000 * fs), 'total_minutes': sum(r['duration_minutes'] for r in selected), 'total_fare_yen': sum(r['fare_yen'] for r in selected), 'routes': selected, '_t': ti, '_f': fi})
            if len(candidates) > max_points:
                raise OptimizationLimitError('パレート点の上限に達しました。候補・経路を減らしてください。')
            fare_bound = fi - 1
            if fi == 0:
                break
    frontier = [s for s in candidates if not any(o['_t'] <= s['_t'] and o['_f'] <= s['_f'] and (o['_t'] < s['_t'] or o['_f'] < s['_f']) for o in candidates)]
    frontier.sort(key=lambda s: (s['_t'], s['_f'], s['station']))
    return {'solutions': [{k: v for k, v in s.items() if not k.startswith('_')} for s in frontier], 'excluded_stations': excluded, 'warnings': ['入力された候補駅・経路の範囲内のパレート解です。日本全国の最適性は保証しません。', '同じ駅・同じ目的値の経路組合せは代表1件を表示します。'], 'metadata': {'algorithm': 'binary MILP / lexicographic epsilon-constraint', 'complete': True, 'solver_calls': solve_count, 'time_scale_minutes': ts, 'fare_scale_yen': fs, 'transfer_minutes_included_in_duration': True}}
