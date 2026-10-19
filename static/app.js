"use strict";
const $ = (id) => document.getElementById(id);
let nextId = 1,
  requestId = 0,
  controller = null,
  sampleActive = false;
const escapeHTML = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const number = (v) =>
  new Intl.NumberFormat("ja-JP", { maximumFractionDigits: 2 }).format(
    Number(v),
  );
const operators = [
  ["Toei", "都営"],
  ["TokyoMetro", "東京メトロ"],
  ["TWR", "りんかい線"],
  ["MIR", "つくばエクスプレス"],
  ["TamaMonorail", "多摩モノレール"],
  ["Yurikamome", "ゆりかもめ（駅時刻表補完が必要）"],
];
function renderOperators(coverage = []) {
  $("operator-list").innerHTML = operators
    .map(
      ([id, name]) =>
        `<label class="operator"><input type="checkbox" value="${id}" ${coverage.includes(id) ? "" : "disabled"} ${coverage.includes(id) && id === "Toei" ? "checked" : ""}> ${name}${coverage.includes(id) ? "" : "（未接続）"}</label>`,
    )
    .join("");
}
renderOperators();
let catalogRequest = 0;
async function loadStations() {
  if ($("mode").value !== "live") return;
  const selected = [
    ...$("operator-list").querySelectorAll("input:checked"),
  ].map((el) => el.value);
  const request = ++catalogRequest;
  if (!selected.length) {
    $("station-options").replaceChildren();
    return;
  }
  try {
    const response = await fetch(
      "/api/stations?operators=" + encodeURIComponent(selected.join(",")),
    );
    const data = await response.json();
    if (request !== catalogRequest || !response.ok) return;
    $("station-options").replaceChildren();
    for (const station of data.stations || []) {
      const option = document.createElement("option");
      option.value = station.id;
      option.label = `${station.name}（${station.operator} / ${station.railway || ""}）`;
      $("station-options").append(option);
    }
  } catch {
    /* Search errors are displayed by the calculation endpoint. */
  }
}
$("mode").addEventListener("change", loadStations);
$("operator-list").addEventListener("change", loadStations);

const split = (v) => [
  ...new Set(
    v
      .split(/[,、\n]/)
      .map((s) => s.trim())
      .filter(Boolean),
  ),
];
function invalidate() {
  requestId++;
  if (controller) controller.abort();
  controller = null;
  $("loading").hidden = true;
  $("results").hidden = true;
  $("result-count").hidden = true;
  $("empty-state").hidden = false;
  $("calculate").disabled = false;
  $("calculate").textContent = "集合駅を比較する ↗";
  $("form-error").hidden = true;
}
function addPerson(data = {}) {
  const id = data.id || `p${nextId++}`;
  const el = document.createElement("div");
  el.className = "person";
  el.dataset.id = id;
  const weight = data.time_weight ?? 0.5;
  el.innerHTML = `<div class="person-header"><span class="person-id">${escapeHTML(id)}</span><input class="person-name" aria-label="参加者 ${escapeHTML(id)} の名前" value="${escapeHTML(data.name || `参加者 ${id.slice(1)}`)}" required maxlength="80"><button type="button" class="remove" aria-label="参加者 ${escapeHTML(id)} を削除">×</button></div><label for="origin-${escapeHTML(id)}">出発駅（複数可）</label><input class="origins" list="station-options" id="origin-${escapeHTML(id)}" value="${escapeHTML((data.origins || []).join(", "))}" placeholder="例：池袋, 要町" required><div class="weight-labels"><span>時間重視 <b class="time-label">${Math.round(weight * 100)}%</b></span><span>運賃重視 <b class="fare-label">${Math.round((1 - weight) * 100)}%</b></span></div><input class="weight" type="range" min="0" max="100" step="1" value="${Math.round(weight * 100)}" aria-label="参加者 ${escapeHTML(id)} の時間への重み">`;
  el.querySelector(".weight").addEventListener("input", (e) => {
    const n = Number(e.target.value);
    el.querySelector(".time-label").textContent = n + "%";
    el.querySelector(".fare-label").textContent = 100 - n + "%";
  });
  el.querySelector(".remove").addEventListener("click", () => {
    if ($("participants").children.length <= 1) {
      showError("参加者を少なくとも1人残してください。");
      return;
    }
    el.remove();
    invalidate();
  });
  $("participants").append(el);
}
function showError(message) {
  $("form-error").textContent = message;
  $("form-error").hidden = false;
}
function getParticipants() {
  return [...$("participants").children].map((el) => ({
    id: el.dataset.id,
    name: el.querySelector(".person-name").value.trim(),
    origins: split(el.querySelector(".origins").value),
    time_weight: Number(el.querySelector(".weight").value) / 100,
    fare_weight: (100 - Number(el.querySelector(".weight").value)) / 100,
  }));
}
$("planner-form").addEventListener("input", invalidate);
$("planner-form").addEventListener("change", invalidate);
$("add-person").addEventListener("click", () => {
  addPerson();
  invalidate();
});
$("mode").addEventListener("change", () => {
  const manual = $("mode").value === "manual";
  $("routes").required = manual;
  $("routes").disabled = !manual;
  $("sample-banner").hidden = !(manual && sampleActive);
  $("clear-sample").hidden = !(manual && sampleActive);
});
$("clear-sample").addEventListener("click", () => {
  invalidate();
  sampleActive = false;
  $("sample-banner").hidden = true;
  $("clear-sample").hidden = true;
  $("routes").value = "";
  $("routes").focus();
});
$("load-sample").addEventListener("click", () => {
  invalidate();
  sampleActive = true;
  $("sample-banner").hidden = false;
  $("clear-sample").hidden = false;
  $("mode").value = "manual";
  $("routes").required = true;
  $("routes").disabled = false;
  $("participants").replaceChildren();
  nextId = 3;
  addPerson({
    id: "p1",
    name: "参加者 A",
    origins: ["池袋"],
    time_weight: 0.6,
  });
  addPerson({
    id: "p2",
    name: "参加者 B",
    origins: ["自由が丘"],
    time_weight: 0.4,
  });
  $("candidates").value = "新宿, 渋谷, 東京";
  const rows = [
    ["p1", "池袋", "新宿", 15, 240, 0],
    ["p2", "自由が丘", "新宿", 30, 410, 6],
    ["p1", "池袋", "渋谷", 25, 300, 0],
    ["p2", "自由が丘", "渋谷", 15, 220, 0],
    ["p1", "池袋", "東京", 20, 180, 0],
    ["p2", "自由が丘", "東京", 40, 200, 8],
  ];
  $("routes").value = JSON.stringify(
    rows.map(
      ([
        participant_id,
        origin,
        destination,
        duration_minutes,
        fare_yen,
        transfer_minutes,
      ]) => ({
        participant_id,
        origin,
        destination,
        duration_minutes,
        fare_yen,
        transfer_minutes,
        source: "架空サンプル（実際の時刻表・運賃ではありません）",
      }),
    ),
    null,
    2,
  );
});
function renderChart(solutions) {
  const width = 580,
    height = 295,
    left = 62,
    right = 25,
    top = 28,
    bottom = 57;
  const valid = solutions.filter(
    (s) =>
      Number.isFinite(Number(s.time_objective)) &&
      Number.isFinite(Number(s.fare_objective)),
  );
  const mx =
      Math.max(...valid.map((s) => Number(s.time_objective)), 0.1) * 1.15,
    my = Math.max(...valid.map((s) => Number(s.fare_objective)), 0.1) * 1.15;
  const x = (v) => left + (v / mx) * (width - left - right),
    y = (v) => height - bottom - (v / my) * (height - top - bottom);
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="時間と運賃の目的値を比較する散布図。詳細は下の候補一覧に記載。"><rect x="${left}" y="${top}" width="${width - left - right}" height="${height - top - bottom}" fill="#f7f9f2"/>`;
  for (let i = 0; i <= 4; i++) {
    const xx = x((mx * i) / 4),
      yy = y((my * i) / 4);
    svg += `<path d="M${left} ${yy}H${width - right}" stroke="#e1e8d7"/><text x="${left - 10}" y="${yy + 4}" text-anchor="end" fill="#7d8c72" font-size="10">${number((my * i) / 4)}</text><text x="${xx}" y="${height - bottom + 19}" text-anchor="middle" fill="#7d8c72" font-size="10">${number((mx * i) / 4)}</text>`;
  }
  svg += `<text x="${width / 2}" y="${height - 10}" text-anchor="middle" fill="#65775b" font-size="11">時間の目的値 →</text><text transform="translate(16 ${height / 2}) rotate(-90)" text-anchor="middle" fill="#65775b" font-size="11">運賃の目的値 →</text>`;
  valid.forEach((s, i) => {
    svg += `<circle cx="${x(s.time_objective)}" cy="${y(s.fare_objective)}" r="9" fill="#315d49" stroke="#fff" stroke-width="3"><title>${escapeHTML(s.station)}：時間 ${number(s.time_objective)}、運賃 ${number(s.fare_objective)}</title></circle><text x="${x(s.time_objective) + 13}" y="${y(s.fare_objective) - 10}" fill="#315d49" font-size="11">${i + 1}</text>`;
  });
  $("chart").innerHTML = svg + "</svg>";
}
function displayTime(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? String(value)
    : new Intl.DateTimeFormat("ja-JP", {
        timeZone: "Asia/Tokyo",
        month: "numeric",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      }).format(date);
}
function render(data, participants) {
  const solutions = data.solutions || [];
  const stationLabel = (id) => data.metadata?.station_labels?.[id] || id;
  const names = Object.fromEntries(participants.map((p) => [p.id, p.name]));
  $("empty-state").hidden = true;
  $("results").hidden = false;
  $("result-count").textContent = `${solutions.length} 件の候補`;
  $("result-count").hidden = false;
  renderChart(
    solutions.map((s) => ({ ...s, station: stationLabel(s.station) })),
  );
  $("solution-list").innerHTML = solutions.length
    ? solutions
        .map(
          (s, i) =>
            `<article class="panel solution"><div class="solution-head"><div class="station-title"><span class="rank">${i + 1}</span><h3>${escapeHTML(stationLabel(s.station))}</h3></div><span class="pareto-tag">PARETO OPTIMAL</span></div><div class="metrics"><div class="metric"><span class="caption">集合までの所要時間の合計</span><strong>${number(s.total_minutes)}<small>分</small></strong></div><div class="metric"><span class="caption">全員の運賃の合計</span><strong>${number(s.total_fare_yen)}<small>円</small></strong></div></div><p class="help">集合までの所要時間には早着時の待ち時間を含みます。<br>時間の目的値 ${number(s.time_objective)} ／ 運賃の目的値 ${number(s.fare_objective)}</p>${(s.routes || []).map((r) => `<div class="route"><div class="route-top"><b>${escapeHTML(names[r.participant_id] || r.participant_id)}：${escapeHTML(stationLabel(r.origin))} → ${escapeHTML(stationLabel(r.destination || s.station))}</b><span>${number(r.duration_minutes)} 分 · ${number(r.fare_yen)} 円</span></div><p class="route-meta">乗換時間 ${number(r.transfer_minutes || 0)} 分（所要時間に含む）${r.travel_duration_minutes != null ? " ／ 移動 " + number(r.travel_duration_minutes) + " 分" : ""}${r.early_wait_minutes != null ? " ／ 早着後の待ち時間 " + number(r.early_wait_minutes) + " 分" : ""}${r.departure_at ? " ／ 出発 " + escapeHTML(displayTime(r.departure_at)) : ""}${r.arrival_at ? " ／ 到着 " + escapeHTML(displayTime(r.arrival_at)) : ""}</p><p class="route-meta">出典：${escapeHTML(r.source || "未記載")}</p></div>`).join("")}</article>`,
        )
        .join("")
    : '<div class="panel solution"><h3>条件に合う候補がありません</h3><p>経路データと除外理由を確認し、候補駅や出発駅を見直してください。</p></div>';
  const warnings = [...(data.warnings || [])];
  const meta = data.metadata || {};
  if (meta.mode === "live") {
    const dates = (v) =>
      Array.isArray(v) && v.length ? `${v[0]}〜${v[v.length - 1]}` : "記載なし";
    warnings.push(
      `時刻表データの公開・生成日：${dates(meta.timetable_generated_dates)}。運賃データの公開・生成日：${dates(meta.fare_generated_dates)}。データ取得日時は運賃・ダイヤの現行性を保証しません。利用前に事業者の最新案内をご確認ください。`,
    );
    if (meta.station_timetable_fallback) {
      warnings.push(
        `補完元の駅時刻表の公開・生成日：${dates(meta.station_timetable_generated_dates)}。補完した便数：${meta.reconstructed_trip_count ?? 0}。`,
      );
    }
    warnings.unshift(
      `検索範囲：${(meta.operators || []).join(" / ")}、集合候補 ${meta.candidate_count ?? "未記載"} 駅、集合前 ${meta.lookback_hours ?? "未記載"} 時間、最大 ${meta.max_boardings ?? "未記載"} 回乗車。取得できた有効な経路の範囲で比較。`,
    );
  }
  if (sampleActive && $("mode").value === "manual")
    warnings.unshift(
      "これは架空サンプルの計算結果です。実際の旅行・集合計画には使わないでください。",
    );
  $("warnings").textContent = warnings.join(" / ");
  $("warnings").hidden = !warnings.length;
  const excluded = data.excluded_stations || [];
  $("excluded-details").hidden = !excluded.length;
  $("excluded-list").innerHTML = excluded
    .map(
      (s) =>
        `<li>${escapeHTML(stationLabel(s.station))}：${escapeHTML(s.reason)}</li>`,
    )
    .join("");
}
$("planner-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  invalidate();
  const participants = getParticipants();
  const candidate_stations = split($("candidates").value);
  if (
    participants.some((p) => !p.name || !p.origins.length) ||
    ($("mode").value === "manual" && !candidate_stations.length)
  ) {
    showError("参加者名、出発駅、集合駅の候補を入力してください。");
    return;
  }
  let routes = [];
  if ($("mode").value === "manual") {
    try {
      routes = JSON.parse($("routes").value);
      if (!Array.isArray(routes) || !routes.length) throw Error();
    } catch {
      showError(
        "経路データは、1件以上の経路を含む正しい JSON 配列で入力してください。",
      );
      return;
    }
  }
  const selectedOperators = [
    ...$("operator-list").querySelectorAll("input:checked"),
  ].map((el) => el.value);
  if ($("mode").value === "live" && !selectedOperators.length) {
    showError("時刻表検索の対象事業者を少なくとも1つ選んでください。");
    return;
  }
  const payload = {
    participants,
    candidate_stations,
    operators: selectedOperators,
    time_scale_minutes: Number($("time-scale").value),
    fare_scale_yen: Number($("fare-scale").value),
    mode:
      sampleActive && $("mode").value === "manual" ? "demo" : $("mode").value,
    meeting_at: $("meeting-at").value + ":00+09:00",
    use_station_timetable_fallback: $("station-fallback").checked,
    ...($("mode").value === "manual" ? { routes } : {}),
  };
  const id = ++requestId;
  controller = new AbortController();
  $("calculate").disabled = true;
  $("calculate").textContent = "計算しています…";
  $("empty-state").hidden = true;
  $("loading").hidden = false;
  try {
    const response = await fetch("/api/optimize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const data = await response.json();
    if (id !== requestId) return;
    if (!response.ok)
      throw new Error(
        typeof data.error === "string"
          ? data.error
          : data.message ||
              "計算できませんでした。入力内容を確認してください。",
      );
    render(data, participants);
  } catch (error) {
    if (id !== requestId || error.name === "AbortError") return;
    showError(error.message || "通信に失敗しました。接続を確認してください。");
    $("empty-state").hidden = false;
  } finally {
    if (id === requestId) {
      $("loading").hidden = true;
      $("calculate").disabled = false;
      $("calculate").textContent = "集合駅を比較する ↗";
      controller = null;
    }
  }
});
addPerson();
addPerson();
const tomorrow = new Date(Date.now() + 86400000 + 9 * 3600000);
$("meeting-at").value = tomorrow.toISOString().slice(0, 10) + "T12:00";
fetch("/api/status")
  .then((r) => {
    if (!r.ok) throw Error();
    return r.json();
  })
  .then((data) => {
    renderOperators(Array.isArray(data.coverage) ? data.coverage : []);
    $("provider-status").textContent = data.live_available
      ? `時刻表検索が利用可能です。${data.message || ""}`
      : `現在、実際の時刻表・経路サービスには接続していません。手動入力または明示的な架空サンプルで比較できます。${data.message ? " " + data.message : ""}`;
    const option = $("mode").querySelector('[value="live"]');
    option.disabled = !data.live_available;
    if (data.live_available) option.textContent = "時刻表から検索";
  })
  .catch(() => {
    $("provider-status").textContent =
      "経路サービスの接続状態を取得できませんでした。時刻表検索は利用できません。手動データを入力して比較してください。";
  });
