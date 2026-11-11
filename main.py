#!/usr/bin/env python3
"""Roblox Up-and-Coming top-10 forecaster for make.fun roblox-up-and-coming-forecast-01.

Horizon-averaged mixture of:
  1) empirical start-rank -> place transition tables built from /input/history.ndjson
  2) soft Gaussian rank-spread around a momentum-adjusted expected rank

Leaves growing unnamed mass for brand-new chart entrants. Standard library only.

Credits:
  - Starts from the official make.fun kit starter (MIT), persistence baseline idea retained
    as a short-horizon component via the soft kernel.
  - Chart history format and archive provenance: Kenny-Dhub/roblox-snapshots (MIT).
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

PLACES = 10
LOOKBACK = 12
HOURS = 72
MAX_START = 50
TOP_CAND = 50
MOM_WEIGHT = 0.35
BEST_WEIGHT = 0.28
PLAY_WEIGHT = 0.14
PRESENCE_BOOST = 1.0
BASE_SIGMA = 2.0
SIGMA_PER_SQRT_H = 0.35  # tightened after practice score: less overspread at long horizons
TEMP = 1.15
EMPIRIC_WEIGHT = 0.45
SOFT_WEIGHT = 0.55
EXTRA_NEW = 0.05  # a bit more unnamed mass for brand-new Up-and-Coming entrants
MAX_NAMED = 0.93
DEEP_RISE_BONUS = 1.0

HORIZON_EDGES = (0, 6, 18, 36, 60, 84)


def parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def rank_map(snap: dict) -> dict[int, int]:
    return {int(r["universe_id"]): int(r["rank"]) for r in snap["up_and_coming"]}


def ids_sorted(snap: dict) -> list[int]:
    rows = sorted(snap["up_and_coming"], key=lambda r: int(r["rank"]))
    return [int(r["universe_id"]) for r in rows]


def playing_map(snap: dict) -> dict[int, int]:
    out: dict[int, int] = {}
    for r in snap["up_and_coming"]:
        out[int(r["universe_id"])] = int(r["playing"] or 0)
    return out


def horizon_bin(hour: float) -> int:
    for i in range(len(HORIZON_EDGES) - 1):
        if hour < HORIZON_EDGES[i + 1]:
            return i
    return len(HORIZON_EDGES) - 2


def build_tables(snaps: list[dict]) -> list[list[list[float]]]:
    times = [parse_ts(s["at"]) for s in snaps]
    rms = [rank_map(s) for s in snaps]
    n_bins = len(HORIZON_EDGES) - 1
    counts = [[[0] * (PLACES + 1) for _ in range(MAX_START + 1)] for _ in range(n_bins)]
    for i in range(len(snaps)):
        for j in range(i + 1, len(snaps)):
            dt = (times[j] - times[i]) / 3600.0
            if dt < 0 or dt >= HORIZON_EDGES[-1]:
                continue
            hb = horizon_bin(dt)
            for uid, sr in rms[i].items():
                if sr < 1 or sr > MAX_START:
                    continue
                er = rms[j].get(uid)
                ep = 0 if (er is None or er > PLACES) else er
                counts[hb][sr][ep] += 1
    tables: list[list[list[float]]] = []
    for hb in range(n_bins):
        tab: list[list[float]] = []
        for sr in range(0, MAX_START + 1):
            row = counts[hb][sr]
            tot = sum(row) + (PLACES + 1)
            tab.append([(c + 1) / tot for c in row])
        tables.append(tab)
    return tables


def build_features(snaps: list[dict]) -> dict[int, dict]:
    recent = snaps[-LOOKBACK:]
    last = snaps[-1]
    prev = snaps[-2] if len(snaps) >= 2 else last
    r_last = rank_map(last)
    p_last = playing_map(last)
    r_prev = rank_map(prev)
    p_prev = playing_map(prev)
    all_ids: set[int] = set()
    for s in recent:
        all_ids |= set(rank_map(s))
    feat: dict[int, dict] = {}
    for uid in all_ids:
        rs: list[int] = []
        for s in recent:
            rm = rank_map(s)
            if uid in rm:
                rs.append(rm[uid])
        on = uid in r_last
        feat[uid] = {
            "rank": r_last.get(uid),
            "playing": p_last.get(uid, 0),
            "best": min(rs) if rs else 999,
            "avg": (sum(rs) / len(rs)) if rs else 999.0,
            "presence": len(rs) / len(recent),
            "rank_delta": r_prev.get(uid, 60) - (r_last[uid] if on else 60),
            "play_delta": p_last.get(uid, 0) - p_prev.get(uid, 0),
            "on_chart": on,
        }
    return feat


def candidates(feat: dict[int, dict], last: dict) -> list[int]:
    cands: set[int] = set()
    for uid, f in feat.items():
        if f["on_chart"] and f["rank"] is not None and f["rank"] <= TOP_CAND:
            cands.add(uid)
        elif f["best"] <= 30 and f["presence"] >= 0.2:
            cands.add(uid)
        elif f["on_chart"] and (f["rank_delta"] >= 4 or f["play_delta"] > 2500):
            cands.add(uid)
    for uid in ids_sorted(last)[:TOP_CAND]:
        cands.add(uid)
    return list(cands)


def effective_rank(f: dict) -> float:
    base = float(f["rank"]) if f["rank"] is not None else min(70.0, float(f["avg"]) + 12.0)
    adj = base - MOM_WEIGHT * float(f["rank_delta"])
    adj = (1.0 - BEST_WEIGHT) * adj + BEST_WEIGHT * min(float(f["best"]), base)
    if f["rank"] and f["rank"] > 12 and f["rank_delta"] > 0:
        adj -= DEEP_RISE_BONUS * min(float(f["rank_delta"]), 25.0)
    if f["play_delta"] > 4000 and f["rank"] and f["rank"] > 8:
        adj -= 4.0
    elif f["play_delta"] > 1500 and f["rank"] and f["rank"] > 15:
        adj -= 2.0
    return max(1.0, adj)


def strength_of(f: dict) -> float:
    s = 1.0 + PLAY_WEIGHT * math.log1p(f["playing"]) + PRESENCE_BOOST * (f["presence"] - 0.5)
    s += 0.05 * max(0.0, float(f["rank_delta"]))
    if f["play_delta"] > 0:
        s += 0.12 * math.log1p(f["play_delta"])
    return s


def forecast(snaps: list[dict], places: int) -> dict:
    tables = build_tables(snaps)
    feat = build_features(snaps)
    last = snaps[-1]
    cands = candidates(feat, last)
    eff = {uid: effective_rank(feat[uid]) for uid in cands}
    strength = {uid: strength_of(feat[uid]) for uid in cands}

    acc: dict[int, dict[int, float]] = {p: defaultdict(float) for p in range(1, places + 1)}
    unnamed_acc = {p: 0.0 for p in range(1, places + 1)}

    for h in range(HOURS):
        hour = h + 0.5
        hb = horizon_bin(hour)
        sigma = BASE_SIGMA + SIGMA_PER_SQRT_H * (hour ** 0.5)
        soft_p: dict[int, dict[int, float]] = {p: {} for p in range(1, places + 1)}
        for place in range(1, places + 1):
            weights: list[tuple[int, float]] = []
            for uid in cands:
                d = (eff[uid] - place) / sigma
                w = math.exp(-0.5 * d * d) * strength[uid]
                if feat[uid]["rank"] == place:
                    w *= 1.0 + 0.4 * math.exp(-hour / 22.0)
                weights.append((uid, w))
            mx = max(w for _, w in weights)
            exps = [
                (u, math.exp((math.log(w + 1e-300) - math.log(mx + 1e-300)) / TEMP))
                for u, w in weights
            ]
            z = sum(e for _, e in exps) or 1.0
            for u, e in exps:
                soft_p[place][u] = e / z

        prior = {
            uid: strength[uid] * math.exp(-max(0.0, eff[uid] - 8.0) / 18.0) for uid in cands
        }
        emp: dict[int, dict[int, float]] = {p: defaultdict(float) for p in range(1, places + 1)}
        for uid in cands:
            sr = min(MAX_START, max(1, int(round(eff[uid]))))
            probs = tables[hb][sr]
            for place in range(1, places + 1):
                emp[place][uid] += prior[uid] * probs[place]

        for place in range(1, places + 1):
            blended = {
                uid: EMPIRIC_WEIGHT * emp[place].get(uid, 0.0)
                + SOFT_WEIGHT * soft_p[place].get(uid, 0.0)
                for uid in cands
            }
            items = sorted(blended.items(), key=lambda x: -x[1])[:45]
            sm = sum(v for _, v in items) or 1.0
            unnamed = min(0.42, EXTRA_NEW + 0.0025 * hour + 0.14 * (1.0 - math.exp(-hour / 45.0)))
            named_mass = min(MAX_NAMED, 1.0 - unnamed)
            for uid, v in items:
                acc[place][uid] += named_mass * (v / sm)
            unnamed_acc[place] += 1.0 - named_mass

    H = float(HOURS)
    probabilities: list[dict] = []
    for place in range(1, places + 1):
        items = sorted(((u, v / H) for u, v in acc[place].items()), key=lambda x: -x[1])
        target_unnamed = unnamed_acc[place] / H
        kept = [(u, p) for u, p in items if p >= 0.001][:55]
        s = sum(p for _, p in kept) or 1.0
        scale = (1.0 - target_unnamed) / s
        rows: list[dict] = []
        for u, p in kept:
            pp = round(p * scale, 6)
            if pp >= 0.0012:
                rows.append({"universe_id": int(u), "place": int(place), "p": pp})
        sm = sum(r["p"] for r in rows)
        if sm > 0.995:
            fac = 0.97 / sm
            for r in rows:
                r["p"] = round(r["p"] * fac, 6)
        probabilities.extend(rows)

    presence: dict[int, float] = defaultdict(float)
    for r in probabilities:
        presence[r["universe_id"]] += r["p"] * (11 - r["place"])
    for uid, f in feat.items():
        presence[uid] += 0.04 * f["presence"] + 0.025 * max(0.0, float(f["rank_delta"]))
        if f["rank"] and f["rank"] <= 12:
            presence[uid] += 0.3 / float(f["rank"])
        if f["play_delta"] > 2500:
            presence[uid] += 0.35
    top10 = [int(u) for u, _ in sorted(presence.items(), key=lambda x: -x[1])[:places]]
    return {"probabilities": probabilities, "top10": top10}


def main() -> None:
    task = json.loads((INPUT_DIR / "task.json").read_text(encoding="utf-8"))
    places = int(task.get("places", PLACES))
    out_name = task.get("output", "forecast.json")
    lines = (INPUT_DIR / "history.ndjson").read_text(encoding="utf-8").splitlines()
    snaps = [json.loads(line) for line in lines if line.strip()]
    if not snaps:
        raise SystemExit("empty history")
    result = forecast(snaps, places)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Stable JSON: compact separators, trailing newline (byte-identical across runs).
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n"
    (OUTPUT_DIR / out_name).write_text(payload, encoding="utf-8")


if __name__ == "__main__":
    main()
