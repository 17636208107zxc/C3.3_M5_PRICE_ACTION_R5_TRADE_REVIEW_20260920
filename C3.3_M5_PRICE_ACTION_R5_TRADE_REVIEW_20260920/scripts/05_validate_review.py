from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
R5 = ROOT.parent / "C3.3_M5_PRICE_ACTION_R5_20260920"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def parse_time(value: str) -> datetime:
    return datetime.strptime(value, "%Y.%m.%d %H:%M:%S")


def check(name: str, condition: bool, detail: object) -> dict:
    return {"check": name, "status": "PASS" if condition else "FAIL", "detail": detail}


def main() -> None:
    index = read_csv(ROOT / "02_TRADE_INDEX/R5_99交易复盘索引.csv")
    sample = read_csv(ROOT / "02_TRADE_INDEX/frozen_20_sample.csv")
    recon = read_csv(ROOT / "05_DETAILS/99笔账本逐笔核对.csv")
    focus = read_csv(ROOT / "05_DETAILS/重点案例3_5_7_8_9_10_12.csv")
    candidates = [row for row in read_csv(R5 / "05_DIAGNOSTICS/route_candidate_timeline.csv") if row["ledger"] == "COMBINED"]
    candidate_map = {(row["month"], row["opportunity_id"]): row for row in candidates}
    sample_ids = {row["opportunity_id"] for row in sample}
    index_ids = {row["opportunity_id"] for row in index}
    results = []
    results.append(check("99笔索引", len(index) == 99, len(index)))
    results.append(check("99个唯一opportunity_id", len(index_ids) == 99, len(index_ids)))
    results.append(check("逐笔账本核对", len(recon) == 99 and all(r["status"] == "PASS" for r in recon), len(recon)))
    results.append(check("20笔冻结样本", len(sample) == 20 and len(sample_ids) == 20 and sample_ids <= index_ids, len(sample_ids)))
    results.append(check("7个重点案例", {r["case_no"] for r in focus} == {"3", "5", "7", "8", "9", "10", "12"}, [r["case_no"] for r in focus]))
    results.append(check("第3/8/9笔保留无2R候选事实", all(r["control_2r_candidates"] == "0" for r in focus if r["case_no"] in {"3", "8", "9"}),
                         {r["case_no"]: r["control_2r_candidates"] for r in focus if r["case_no"] in {"3", "8", "9"}}))
    results.append(check("五条规则机械证据", all(r["five_rule_machine_verdict"] == "5/5 PASS" for r in index),
                         sum(r["five_rule_machine_verdict"] == "5/5 PASS" for r in index)))
    results.append(check("成本限制记录一致", all(float(r["commission"]) == 0 and float(r["slippage"]) == 0 for r in index), "commission=0, slippage=0"))
    results.append(check("真实tick路径", all(r["path_quality"] == "REAL_TICK" for r in index), sorted({r["path_quality"] for r in index})))
    results.append(check("实际TP均至少2R", min(float(r["actual_target_r"]) for r in index) >= 2.0, min(float(r["actual_target_r"]) for r in index)))
    results.append(check("目标/止损退出合计99", sum(r["exit_reason"] == "TARGET" for r in index) == 21 and sum(r["exit_reason"] == "STOP" for r in index) == 78,
                         {"TARGET": sum(r["exit_reason"] == "TARGET" for r in index), "STOP": sum(r["exit_reason"] == "STOP" for r in index)}))

    causal_ok = True
    missing_candidates = []
    for row in index:
        candidate = candidate_map.get((row["month"], row["opportunity_id"]))
        if not candidate:
            missing_candidates.append(row["trade_id"]); causal_ok = False; continue
        times = [parse_time(candidate[key]) for key in ("observe_time", "formed_time", "confirmed_time", "eligible_time")]
        causal_ok &= times[0] <= times[1] <= times[2] < times[3] <= parse_time(row["fill_time"])
    results.append(check("候选因果顺序", causal_ok and not missing_candidates, {"missing": missing_candidates}))

    bars = {}
    for path in (ROOT / "01_BROKER_DATA/TESTER_EXPORT").glob("*_M5.csv"):
        month = path.name.removesuffix("_M5.csv")
        bars[month] = {row["time"] for row in read_csv(path)}
    results.append(check("99根信号K均在原测试器M5数据中", all(r["signal_bar_time"] in bars[r["month"]] for r in index),
                         sum(r["signal_bar_time"] in bars[r["month"]] for r in index)))

    trade_charts = sorted((ROOT / "03_CHARTS/TRADES").glob("*.png"))
    focus_charts = sorted((ROOT / "03_CHARTS/FOCUS").glob("*.png"))
    image_ok = True
    dimensions = {}
    for path in trade_charts + focus_charts:
        with Image.open(path) as image:
            dimensions[path.name] = image.size
            image_ok &= image.width >= 2000 and image.height >= 1000
    results.append(check("20张交易图", len(trade_charts) == 20, len(trade_charts)))
    results.append(check("7张重点图", len(focus_charts) == 7, len(focus_charts)))
    results.append(check("PNG分辨率", image_ok, {"min_width": min(v[0] for v in dimensions.values()), "min_height": min(v[1] for v in dimensions.values())}))

    html_path = ROOT / "04_REPORT/R5_99交易质量复盘.html"
    html_text = html_path.read_text(encoding="utf-8")
    sources = re.findall(r'<img src="([^"]+)"', html_text)
    missing_images = [source for source in sources if not (html_path.parent / source).resolve().exists()]
    results.append(check("HTML图像引用", len(sources) == 27 and not missing_images, {"references": len(sources), "missing": missing_images}))
    results.append(check("HTML人工判断栏", html_text.count("我会在这个位置开仓") == 20 and html_text.count("我实际会选择的信号K") == 20,
                         {"checkbox_groups": html_text.count("我会在这个位置开仓")}))

    frozen_meta = json.loads((ROOT / "02_TRADE_INDEX/frozen_20_sample.json").read_text(encoding="utf-8"))
    results.append(check("冻结样本SHA", frozen_meta["sample_csv_sha256"] == sha(ROOT / "02_TRADE_INDEX/frozen_20_sample.csv"), frozen_meta["sample_csv_sha256"]))
    provenance = json.loads((ROOT / "01_BROKER_DATA/tester_export_provenance.json").read_text(encoding="utf-8"))
    results.append(check("原测试器行情交叉验证", provenance["ordinary_terminal_cross_check"]["match_rate_pct"] == 100.0,
                         provenance["ordinary_terminal_cross_check"]))
    results.append(check("行情导出器编译", provenance["exporter"]["compile_result"] == "0 errors, 0 warnings", provenance["exporter"]["compile_result"]))

    original_manifest = json.loads((R5 / "07_PACKAGE/package_manifest.json").read_text(encoding="utf-8"))
    altered = []
    for item in original_manifest["files"]:
        path = R5 / item["path"]
        if not path.exists() or sha(path) != item["sha256"]:
            altered.append(item["path"])
    results.append(check("R5原交付文件未改动", not altered, {"checked": len(original_manifest["files"]), "altered": altered}))

    status = "PASS" if all(item["status"] == "PASS" for item in results) else "FAIL"
    payload = {"status": status, "checks": results}
    package_dir = ROOT / "06_PACKAGE"
    package_dir.mkdir(exist_ok=True)
    (package_dir / "review_validation.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if status != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
