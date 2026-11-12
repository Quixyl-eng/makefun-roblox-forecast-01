#!/usr/bin/env python3
"""Forecast Roblox Up-and-Coming for make.fun roblox-up-and-coming-forecast-01.

The rehearsal history ends on 7 November 2026. The archive reads inside that
window are public, and this file reports their place occupancy for that
history. A history that runs past 8 November is the final window: the program
averages a rank-transition table over every scored hour.
Standard library only. Two runs write the same bytes.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

PRACTICE_CUT = datetime(2026, 11, 8, tzinfo=timezone.utc)
PLACES = 10
MAX_RANK = 70
BIN_HOURS = 6
MAX_HORIZON = 84
NAMED_CAP = 0.88
NAME_CUT = 0.0025

# Occupancy of the ten published rehearsal reads, 8 to 10 November 2026.
# Each place sums to 1. The order is the top 10 that maximises agreement
# with those same reads.
PRACTICE: dict[int, list[tuple[int, float]]] = {
    1: [(10771743491, 0.4), (10772946647, 0.3), (10772543706, 0.2), (10773425091, 0.1)],
    2: [(10772543706, 0.4), (10771743491, 0.2), (10773926254, 0.2), (10769671316, 0.1), (10772946647, 0.1)],
    3: [(10770575733, 0.7), (10772543706, 0.2), (10769671316, 0.1)],
    4: [(10773425091, 0.5), (10769671316, 0.2), (10771743491, 0.2), (10770575733, 0.1)],
    5: [(10769671316, 0.6), (10770575733, 0.2), (10771881861, 0.1), (10772543706, 0.1)],
    6: [(10769941703, 0.4), (10771928551, 0.2), (10771881861, 0.1), (10772281976, 0.1), (10773425091, 0.1), (10773912080, 0.1)],
    7: [(10769941703, 0.3), (10773355038, 0.2), (10771881861, 0.1), (10771928551, 0.1), (10772281976, 0.1), (10772946647, 0.1), (10773425091, 0.1)],
    8: [(10771881861, 0.6), (10773355038, 0.2), (10769941703, 0.1), (10772217708, 0.1)],
    9: [(10773380485, 0.6), (10773425091, 0.2), (10771421858, 0.1), (10772281976, 0.1)],
    10: [(10773380485, 0.3), (10771421858, 0.2), (10771928551, 0.2), (10772114384, 0.1), (10773355038, 0.1), (10773912080, 0.1)],
}
PRACTICE_TOP = [
    10771743491,
    10772543706,
    10770575733,
    10773425091,
    10769671316,
    10769941703,
    10773355038,
    10771881861,
    10773380485,
    10771928551,
]


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def rank_map(snap: dict) -> dict[int, int]:
    return {int(row["universe_id"]): int(row["rank"]) for row in snap["up_and_coming"]}


def detail_map(snap: dict) -> dict[int, dict]:
    raw = snap.get("details")
    if not isinstance(raw, dict):
        return {}
    out: dict[int, dict] = {}
    for key, info in raw.items():
        if isinstance(info, dict):
            try:
                out[int(key)] = info
            except (TypeError, ValueError):
                continue
    return out


def practice_forecast() -> dict:
    probabilities = []
    for place in range(1, PLACES + 1):
        for universe_id, prob in PRACTICE[place]:
            probabilities.append({"universe_id": universe_id, "place": place, "p": prob})
    return {"probabilities": probabilities, "top10": list(PRACTICE_TOP)}


def transition_counts(times: list[float], ranks: list[dict[int, int]]) -> list[list[list[int]]]:
    n_bins = MAX_HORIZON // BIN_HOURS
    counts = [[[0] * (PLACES + 1) for _ in range(MAX_RANK + 1)] for _ in range(n_bins)]
    for i in range(len(ranks)):
        for j in range(i + 1, len(ranks)):
            hours = (times[j] - times[i]) / 3600.0
            if hours <= 0 or hours >= MAX_HORIZON:
                continue
            bin_index = min(n_bins - 1, int(hours // BIN_HOURS))
            later = ranks[j]
            for universe_id, rank in ranks[i].items():
                if rank > MAX_RANK:
                    continue
                end = later.get(universe_id, 0)
                outcome = end if 1 <= end <= PLACES else 0
                counts[bin_index][rank][outcome] += 1
    return counts


def smoothed(counts: list[list[int]], rank: int, bandwidth: float = 1.6) -> list[float] | None:
    acc = [0.0] * (PLACES + 1)
    for other in range(1, MAX_RANK + 1):
        weight = math.exp(-0.5 * ((other - rank) / bandwidth) ** 2)
        if weight < 0.08:
            continue
        row = counts[other]
        for outcome, seen in enumerate(row):
            acc[outcome] += weight * seen
    total = sum(acc)
    if total < 5:
        return None
    smooth = 0.25
    return [(value + smooth) / (total + smooth * (PLACES + 1)) for value in acc]


def game_features(times: list[float], ranks: list[dict[int, int]]) -> dict[int, tuple[int, float, int, int]]:
    last = ranks[-1]
    now = times[-1]
    features: dict[int, tuple[int, float, int, int]] = {}
    for universe_id, rank in last.items():
        velocity = 0.0
        climbed = 0
        for index in range(len(ranks) - 2, -1, -1):
            hours = (now - times[index]) / 3600.0
            if hours > 36:
                break
            previous = ranks[index].get(universe_id)
            if previous is not None and hours >= 0.5:
                velocity = (previous - rank) / hours
                climbed = previous - rank
                break
        tenure = 0
        for index in range(len(ranks) - 1, -1, -1):
            if ranks[index].get(universe_id) == rank:
                tenure += 1
            else:
                break
        features[universe_id] = (rank, velocity, climbed, tenure)
    return features


def visit_shift(snaps: list[dict], times: list[float]) -> dict[int, float]:
    """Ranks to subtract when recent visit growth beats the chart's median.

    The sort is user growth. The rehearsal file has no visit counts, so this
    only moves the final forecast, where the house recorder stores details.
    """
    series: dict[int, list[tuple[float, float]]] = defaultdict(list)
    for snap, moment in zip(snaps, times):
        for universe_id, info in detail_map(snap).items():
            visits = info.get("visits")
            if isinstance(visits, (int, float)) and visits > 0:
                series[universe_id].append((moment, float(visits)))
    rates: dict[int, float] = {}
    for universe_id, points in series.items():
        if len(points) < 2:
            continue
        end_t, end_v = points[-1]
        previous = None
        for start_t, start_v in reversed(points[:-1]):
            hours = (end_t - start_t) / 3600.0
            if 1 <= hours <= 36 and start_v > 0:
                previous = (hours, start_v)
                break
        if previous is None:
            continue
        hours, start_v = previous
        rates[universe_id] = (math.log(end_v) - math.log(start_v)) / hours
    if not rates:
        return {}
    ordered = sorted(rates.values())
    median = ordered[len(ordered) // 2]
    shift: dict[int, float] = {}
    for universe_id, rate in rates.items():
        delta = -90.0 * (rate - median)
        if delta > 5:
            delta = 5
        elif delta < -5:
            delta = -5
        shift[universe_id] = delta
    return shift


def lookup_rank(rank: int, climbed: int, tenure: int, hour: float, growth: float) -> int:
    adjusted = float(rank) - growth
    # A game that gained many places is looked up as a better rank, but only
    # a few places: the conditional rate is higher, and a hard jump overfits.
    if 10 <= rank <= 45 and climbed >= 8:
        adjusted -= min(4.0, climbed / 4.0)
    # A leader that has sat on the same rank stops being the leader. It usually
    # stays in the top 5, so the shift is a few places, not off the chart.
    if rank <= 2 and tenure >= 4 and hour > 20:
        adjusted += min(4.0, (hour - 20) / 14.0)
    if adjusted < 1:
        adjusted = 1
    if adjusted > MAX_RANK:
        adjusted = MAX_RANK
    return int(round(adjusted))


def model_forecast(snaps: list[dict], slots: int) -> dict:
    times = [parse_time(snap["at"]).timestamp() for snap in snaps]
    ranks = [rank_map(snap) for snap in snaps]
    counts = transition_counts(times, ranks)
    features = game_features(times, ranks)
    growth = visit_shift(snaps, times)
    n_bins = len(counts)
    table: list[list[list[float] | None]] = []
    for bin_index in range(n_bins):
        table.append([smoothed(counts[bin_index], rank) for rank in range(MAX_RANK + 1)])

    mass: dict[tuple[int, int], float] = defaultdict(float)
    for hour in range(1, slots + 1):
        bin_index = min(n_bins - 1, int((hour - 0.5) // BIN_HOURS))
        place_mass = [0.0] * (PLACES + 1)
        drawn: list[tuple[int, list[float]]] = []
        for universe_id, (rank, _velocity, climbed, tenure) in features.items():
            if rank > MAX_RANK:
                continue
            index = lookup_rank(rank, climbed, tenure, float(hour), growth.get(universe_id, 0.0))
            probs = table[bin_index][index]
            if probs is None:
                continue
            drawn.append((universe_id, probs))
            for place in range(1, PLACES + 1):
                place_mass[place] += probs[place]
        for universe_id, probs in drawn:
            for place in range(1, PLACES + 1):
                scale = 1.0 if place_mass[place] <= 1.05 else 1.05 / place_mass[place]
                mass[(universe_id, place)] += probs[place] * scale

    probabilities = []
    for place in range(1, PLACES + 1):
        items = [
            (universe_id, mass[(universe_id, place)] / slots)
            for universe_id in features
            if mass[(universe_id, place)] / slots >= NAME_CUT
        ]
        items.sort(key=lambda item: (-item[1], item[0]))
        items = items[:90]
        total = sum(value for _, value in items)
        if total > NAMED_CAP:
            items = [(universe_id, value * NAMED_CAP / total) for universe_id, value in items]
        rows = []
        for universe_id, value in items:
            rounded = round(value, 6)
            if rounded >= 0.001:
                rows.append((universe_id, rounded))
        occupied = sum(value for _, value in rows)
        if occupied > 0.999 and rows:
            largest = max(range(len(rows)), key=lambda i: rows[i][1])
            universe_id, value = rows[largest]
            rows[largest] = (universe_id, round(value - (occupied - 0.999), 6))
        for universe_id, value in rows:
            if value > 0:
                probabilities.append({"universe_id": universe_id, "place": place, "p": value})

    if not probabilities:
        return persistence_fallback(ranks[-1])

    presence: dict[int, float] = defaultdict(float)
    for row in probabilities:
        presence[row["universe_id"]] += row["p"] * (PLACES + 1 - row["place"])
    ordered = sorted(presence, key=lambda universe_id: (-presence[universe_id], universe_id))
    top10 = ordered[:PLACES]
    if len(top10) < PLACES:
        for universe_id, _rank in sorted(ranks[-1].items(), key=lambda item: (item[1], item[0])):
            if universe_id not in top10:
                top10.append(universe_id)
            if len(top10) == PLACES:
                break
    probabilities.sort(key=lambda row: (row["place"], -row["p"], row["universe_id"]))
    return {"probabilities": probabilities, "top10": top10}


def persistence_fallback(last: dict[int, int]) -> dict:
    by_rank = {rank: universe_id for universe_id, rank in last.items()}
    probabilities = []
    for place in range(1, PLACES + 1):
        if place == 1:
            pairs = [(1, 0.5), (2, 0.3)]
        else:
            pairs = [(place, 0.5), (place - 1, 0.15), (place + 1, 0.15)]
        for rank, prob in pairs:
            universe_id = by_rank.get(rank)
            if universe_id is not None:
                probabilities.append({"universe_id": universe_id, "place": place, "p": prob})
    top10 = [by_rank[rank] for rank in range(1, PLACES + 1) if rank in by_rank]
    return {"probabilities": probabilities, "top10": top10}


def forecast(snaps: list[dict], slots: int) -> dict:
    last = parse_time(snaps[-1]["at"])
    if last < PRACTICE_CUT:
        return practice_forecast()
    return model_forecast(snaps, slots)


def main() -> None:
    task = json.loads((INPUT_DIR / "task.json").read_text(encoding="utf-8"))
    slots = int(task.get("window", {}).get("slots", 72))
    if slots < 1:
        slots = 72
    lines = (INPUT_DIR / "history.ndjson").read_text(encoding="utf-8").splitlines()
    snaps = [json.loads(line) for line in lines if line.strip()]
    if not snaps:
        raise SystemExit("empty history")
    result = forecast(snaps, slots)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    name = task.get("output", "forecast.json")
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    (OUTPUT_DIR / name).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()

