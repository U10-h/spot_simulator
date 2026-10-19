# 集合駅シミュレーター

実装と起動手順は [`feature/pareto-meeting-stations`](https://github.com/U10-h/spot_simulator/tree/feature/pareto-meeting-stations) ブランチにあります。

```sh
git clone --branch feature/pareto-meeting-stations https://github.com/U10-h/spot_simulator.git
cd spot_simulator
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m spot_simulator.server
```

東京都内の対応駅を対象に、時刻表・運賃と参加者の重みからパレート集合駅を比較します。利用可能な路線・データの条件と注意事項は実装ブランチの README を確認してください。
