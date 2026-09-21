from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import MetaTrader5 as mt5

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "01_BROKER_DATA"
TERMINAL = r"C:\MT5\EAAI_V3103_Tester_20260828\Doo Technology MetaTrader 5\terminal64.exe"
SYMBOL = "XAUUSD.s"
PERIODS = [
    (datetime(2025, 3, 1, tzinfo=timezone.utc), datetime(2025, 4, 1, tzinfo=timezone.utc)),
    (datetime(2025, 4, 1, tzinfo=timezone.utc), datetime(2025, 5, 1, tzinfo=timezone.utc)),
    (datetime(2025, 9, 1, tzinfo=timezone.utc), datetime(2025, 10, 1, tzinfo=timezone.utc)),
    (datetime(2026, 3, 1, tzinfo=timezone.utc), datetime(2026, 4, 1, tzinfo=timezone.utc)),
    (datetime(2026, 5, 1, tzinfo=timezone.utc), datetime(2026, 6, 1, tzinfo=timezone.utc)),
    (datetime(2026, 8, 1, tzinfo=timezone.utc), datetime(2026, 9, 1, tzinfo=timezone.utc)),
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def export_timeframe(name: str, timeframe: int) -> tuple[Path, int, str, str]:
    records: dict[int, dict] = {}
    for start, end in PERIODS:
        rates = mt5.copy_rates_range(SYMBOL, timeframe, start - timedelta(days=3), end + timedelta(days=3))
        if rates is None:
            raise RuntimeError(f"copy_rates_range {name} failed: {mt5.last_error()}")
        for item in rates:
            records[int(item["time"])] = {
                "time_epoch": int(item["time"]),
                "time": datetime.fromtimestamp(int(item["time"]), timezone.utc).strftime("%Y.%m.%d %H:%M:%S"),
                "open": float(item["open"]), "high": float(item["high"]),
                "low": float(item["low"]), "close": float(item["close"]),
                "tick_volume": int(item["tick_volume"]), "spread_points": int(item["spread"]),
                "real_volume": int(item["real_volume"]),
            }
    ordered = [records[key] for key in sorted(records)]
    if not ordered:
        raise RuntimeError(f"no {name} bars")
    path = DATA / f"XAUUSD_s_{name}_DooTechnology.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ordered[0]))
        writer.writeheader(); writer.writerows(ordered)
    return path, len(ordered), ordered[0]["time"], ordered[-1]["time"]


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    if not mt5.initialize(path=TERMINAL, portable=True):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        terminal = mt5.terminal_info()
        account = mt5.account_info()
        if terminal is None or account is None:
            raise RuntimeError(f"terminal/account unavailable: {mt5.last_error()}")
        if not mt5.symbol_select(SYMBOL, True):
            raise RuntimeError(f"symbol_select failed: {mt5.last_error()}")
        m5 = export_timeframe("M5", mt5.TIMEFRAME_M5)
        m15 = export_timeframe("M15", mt5.TIMEFRAME_M15)
        metadata = {
            "source": "MetaTrader5 copy_rates_range",
            "terminal_company": terminal.company,
            "terminal_name": terminal.name,
            "server": account.server,
            "symbol": SYMBOL,
            "time_interpretation": "MT5 epoch rendered as UTC; matches tester TimeToString bar labels",
            "terminal_path": terminal.path,
            "exported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "periods_with_three_day_buffer": [
                {"from": (start - timedelta(days=3)).isoformat(), "to": (end + timedelta(days=3)).isoformat()}
                for start, end in PERIODS
            ],
            "files": {
                m5[0].name: {"bars": m5[1], "first": m5[2], "last": m5[3], "sha256": sha256(m5[0])},
                m15[0].name: {"bars": m15[1], "first": m15[2], "last": m15[3], "sha256": sha256(m15[0])},
            },
        }
        (DATA / "broker_data_provenance.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(metadata, ensure_ascii=False, indent=2))
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
