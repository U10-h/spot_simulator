"""Brute-force comparison guards epsilon enumeration and numerical extremes."""
import itertools
import random
import unittest
from spot_simulator.optimizer import optimize


def compare(points, weights):
    p={'participants':[dict(id=str(i),name=str(i),origins=['o'],time_weight=w/1000,fare_weight=(1000-w)/1000) for i,w in enumerate(weights)],'candidate_stations':['s'],'routes':[dict(participant_id=str(i),origin='o',destination='s',duration_minutes=t/60,fare_yen=f,transfer_minutes=0,source='synthetic fixture') for i,pts in enumerate(points) for t,f in pts]}
    allpoints={(sum(weights[i]*r[0] for i,r in enumerate(combo)),sum((1000-weights[i])*r[1] for i,r in enumerate(combo))) for combo in itertools.product(*points)}
    expected={p for p in allpoints if not any(q[0]<=p[0] and q[1]<=p[1] and q!=p for q in allpoints)}
    result=optimize(p)
    actual={(sum(weights[int(r['participant_id'])]*round(r['duration_minutes']*60) for r in s['routes']),sum((1000-weights[int(r['participant_id'])])*r['fare_yen'] for r in s['routes'])) for s in result['solutions']}
    return actual,expected


class ExactnessTests(unittest.TestCase):
    def test_extreme_integrality_regression(self):
        points=[[(172798,99998),(0,100000),(172798,99998),(172800,0)],[(172798,0),(172799,1),(172798,99998),(172799,0)],[(172798,1),(0,99998),(0,100000),(172800,0)]]
        self.assertEqual(*compare(points,[1,999,999]))

    def test_random_against_cartesian_enumeration(self):
        rng=random.Random(82)
        for _ in range(50):
            weights=[rng.choice([0,1,100,500,999,1000]) for _ in range(3)]
            points=[[(rng.randrange(100),rng.randrange(1000)) for _ in range(4)] for _ in weights]
            self.assertEqual(*compare(points,weights))

if __name__=='__main__': unittest.main()
