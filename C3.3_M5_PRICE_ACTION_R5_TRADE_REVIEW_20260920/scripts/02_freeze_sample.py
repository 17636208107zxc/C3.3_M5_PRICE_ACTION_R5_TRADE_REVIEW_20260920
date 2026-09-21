from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R5 = ROOT.parent / "C3.3_M5_PRICE_ACTION_R5_20260920"
OUT = ROOT / "02_TRADE_INDEX"
TRADES = R5 / "04_ROUTE_RESULTS/combined_virtual_trades.csv"
CANDIDATES = R5 / "05_DIAGNOSTICS/route_candidate_timeline.csv"
TESTER_BARS = ROOT / "01_BROKER_DATA/TESTER_EXPORT"


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def stable_key(row: dict[str, str]) -> str:
    return hashlib.sha256((row["month"] + "|" + row["opportunity_id"]).encode()).hexdigest()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    trades = read(TRADES)
    combined = [row for row in read(CANDIDATES) if row.get("ledger") == "COMBINED"]
    cmap = {(row["month"], row["opportunity_id"]): row for row in combined}
    closes: dict[tuple[str, str], float] = {}
    for month in {row["month"] for row in trades}:
        for bar in read(TESTER_BARS / f"{month}_M5.csv"):
            closes[(month, bar["time"])] = float(bar["close"])
    if len(trades) != 99 or len({(r["month"], r["opportunity_id"]) for r in trades}) != 99:
        raise AssertionError("combined control ledger is not 99 unique trades")
    enriched = []
    for row in trades:
        candidate = cmap[(row["month"], row["opportunity_id"])]
        item = dict(row)
        item.update({
            "signal_bar_time": candidate["signal_bar_time"],
            "context_class": candidate["class"],
            "pullback_class": candidate["pullback_class"],
            "outcome_group": "WIN" if float(row["net"]) > 0 else "LOSS",
            "signal_to_fill_minutes": int((datetime.strptime(row["fill_time"], "%Y.%m.%d %H:%M:%S") -
                                           datetime.strptime(candidate["signal_bar_time"], "%Y.%m.%d %H:%M:%S")).total_seconds() / 60),
        })
        risk = abs(float(row["fill_price"]) - float(row["sl"]))
        signal_close = closes[(row["month"], candidate["signal_bar_time"])]
        item["entry_extension_r"] = int(row["side"]) * (float(row["fill_price"]) - signal_close) / risk if risk else 0.0
        enriched.append(item)

    selected: dict[tuple[str, str], dict] = {}

    def add(item: dict, reason: str) -> None:
        key = (item["month"], item["opportunity_id"])
        if key not in selected:
            selected[key] = {"row": item, "reasons": []}
        if reason not in selected[key]["reasons"]:
            selected[key]["reasons"].append(reason)

    quotas = {
        ("A_HEALTHY_FIRST_RESUME", "1", "WIN"): 2,
        ("A_HEALTHY_FIRST_RESUME", "1", "LOSS"): 2,
        ("A_HEALTHY_FIRST_RESUME", "-1", "WIN"): 2,
        ("A_HEALTHY_FIRST_RESUME", "-1", "LOSS"): 2,
        ("B_COMPLEX_H2_L2", "1", "WIN"): 2,
        ("B_COMPLEX_H2_L2", "1", "LOSS"): 2,
        ("B_COMPLEX_H2_L2", "-1", "WIN"): 1,
        ("B_COMPLEX_H2_L2", "-1", "LOSS"): 2,
    }
    for stratum, quota in quotas.items():
        pool = [row for row in enriched if (row["route"], row["side"], row["outcome_group"]) == stratum]
        if len(pool) < quota:
            raise AssertionError(f"insufficient stratum {stratum}: {len(pool)}<{quota}")
        for item in sorted(pool, key=stable_key)[:quota]:
            add(item, f"固定分层:{stratum[0]}|{'BUY' if stratum[1]=='1' else 'SELL'}|{stratum[2]}")

    # Include paired A1/A2 trades from the same setup before any chart review.
    setup_counts: dict[str, list[dict]] = {}
    for row in enriched:
        setup_counts.setdefault(row["setup_id"], []).append(row)
    for setup_id in sorted(setup_counts):
        group = setup_counts[setup_id]
        if len(group) > 1:
            for item in sorted(group, key=lambda row: row["fill_time"]):
                add(item, "同一setup多次入场尝试")
            break

    tactical = sorted(
        [row for row in enriched if row["context_class"] == "TACTICAL_LOCAL_TREND" and
         (row["month"], row["opportunity_id"]) not in selected], key=stable_key)
    if tactical and len(selected) < 20:
        add(tactical[0], "M15与M5分歧的战术局部趋势")

    # Add outcome-path and timing edge cases by numeric rules, without viewing charts.
    mfe_stop = sorted(
        [row for row in enriched if row["exit_reason"] == "STOP" and float(row["mfe_r"]) >= 2.0 and
         (row["month"], row["opportunity_id"]) not in selected],
        key=lambda row: (-float(row["mfe_r"]), stable_key(row)))
    if mfe_stop and len(selected) < 20:
        add(mfe_stop[0], "止损前MFE最高且达到2R")

    extended = sorted(
        [row for row in enriched if row["entry_extension_r"] > 0.25 and
         (row["month"], row["opportunity_id"]) not in selected],
        key=lambda row: (-row["entry_extension_r"], stable_key(row)))
    if extended and len(selected) < 20:
        add(extended[0], f"确认后成交延伸较远:{extended[0]['entry_extension_r']:.2f}R")

    delayed = sorted(
        [row for row in enriched if (row["month"], row["opportunity_id"]) not in selected],
        key=lambda row: (-row["signal_to_fill_minutes"], stable_key(row)))
    if delayed and len(selected) < 20:
        add(delayed[0], "信号至成交等待最长")

    for item in sorted(enriched, key=stable_key):
        if len(selected) >= 20:
            break
        add(item, "稳定哈希补足样本")
    if len(selected) != 20:
        raise AssertionError(f"sample size {len(selected)}")

    output = []
    for number, data in enumerate(sorted(selected.values(), key=lambda value: value["row"]["fill_time"]), 1):
        row = data["row"]
        output.append({
            "sample_no": f"S{number:02d}", "month": row["month"], "fill_time": row["fill_time"],
            "route": row["route"], "side": row["side"], "attempt": row["attempt"],
            "outcome_group": row["outcome_group"], "net": row["net"], "mfe_r": row["mfe_r"],
            "setup_id": row["setup_id"], "opportunity_id": row["opportunity_id"],
            "context_class": row["context_class"], "signal_to_fill_minutes": row["signal_to_fill_minutes"],
            "entry_extension_r": f"{row['entry_extension_r']:.4f}",
            "selection_reason": ";".join(data["reasons"]),
        })
    csv_path = OUT / "frozen_20_sample.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output[0]))
        writer.writeheader(); writer.writerows(output)
    metadata = {
        "status": "FROZEN_BEFORE_CHART_OR_MECHANICAL_QUALITY_REVIEW",
        "selection_inputs": ["Route", "BUY/SELL", "A1/A2", "WIN/LOSS", "same setup count", "MFE>=2 then stop", "signal-to-fill delay", "tactical context", "entry extension in R using signal close and actual fill"],
        "excludes_from_selection": ["manual chart judgment", "mechanical signal verdict", "mechanical plan verdict"],
        "source_sha256": {TRADES.name: sha(TRADES), CANDIDATES.name: sha(CANDIDATES)},
        "sample_count": len(output), "sample_csv_sha256": sha(csv_path),
    }
    (OUT / "frozen_20_sample.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
