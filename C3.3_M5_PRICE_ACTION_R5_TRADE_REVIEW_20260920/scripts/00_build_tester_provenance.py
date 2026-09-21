from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "01_BROKER_DATA"
TESTER = DATA / "TESTER_EXPORT"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def describe(path: Path) -> dict:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    return {
        "bars": len(rows),
        "first": rows[0]["time"] if rows else None,
        "last": rows[-1]["time"] if rows else None,
        "sha256": sha256(path),
    }


def load_ohlc(path: Path) -> dict[str, tuple[float, float, float, float]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return {row["time"]: tuple(float(row[key]) for key in ("open", "high", "low", "close"))
                for row in csv.DictReader(handle)}


def main() -> None:
    files = {path.name: describe(path) for path in sorted(TESTER.glob("*.csv"))}
    ordinary_m5 = load_ohlc(DATA / "XAUUSD_s_M5_DooTechnology.csv")
    overlap_total = overlap_match = 0
    for path in sorted(TESTER.glob("*_M5.csv")):
        exact = load_ohlc(path)
        for when in set(exact).intersection(ordinary_m5):
            overlap_total += 1
            overlap_match += exact[when] == ordinary_m5[when]
    compile_log = (DATA / "EXPORTER/compile.log").read_text(encoding="utf-16", errors="ignore")
    compile_ok = "0 errors, 0 warnings" in compile_log
    exporter_source = DATA / "EXPORTER/R5ReviewBarExporter.mq5"
    payload = {
        "source": "MT5 Strategy Tester CopyRates export from the same portable terminal and symbol as R5",
        "terminal_company": "Doo Technology Singapore Pte. Ltd.",
        "terminal_name": "Doo Technology MetaTrader 5",
        "server": "DooTechnology-Demo",
        "symbol": "XAUUSD.s",
        "terminal_executable": r"C:\MT5\EAAI_V3103_Tester_20260828\Doo Technology MetaTrader 5\terminal64.exe",
        "time_interpretation": "Tester server bar labels; exported with TimeToString and matched to R5 logs",
        "exporter": {
            "source_file": str(exporter_source),
            "source_sha256": sha256(exporter_source),
            "compile_result": "0 errors, 0 warnings" if compile_ok else "compile result not verified",
            "trade_api": "none; exporter only calls CopyRates/FileWrite and returns INIT_FAILED after export",
        },
        "files": files,
        "ordinary_terminal_cross_check": {
            "purpose": "cross-check only; not used for charts because its M5 history starts at 2025-04-23",
            "overlapping_m5_bars": overlap_total,
            "identical_ohlc_bars": overlap_match,
            "match_rate_pct": round(100 * overlap_match / overlap_total, 6) if overlap_total else None,
        },
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    (DATA / "tester_export_provenance.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
