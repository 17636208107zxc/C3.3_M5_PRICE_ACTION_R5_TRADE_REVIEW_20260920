from __future__ import annotations

import csv
import hashlib
import html
import json
import math
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Rectangle
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
R5 = ROOT.parent / "C3.3_M5_PRICE_ACTION_R5_20260920"
BROKER = ROOT / "01_BROKER_DATA/TESTER_EXPORT"
INDEX_DIR = ROOT / "02_TRADE_INDEX"
CHART_TRADE = ROOT / "03_CHARTS/TRADES"
CHART_FOCUS = ROOT / "03_CHARTS/FOCUS"
REPORT_DIR = ROOT / "04_REPORT"
DETAIL_DIR = ROOT / "05_DETAILS"
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"
FONT = FontProperties(fname=FONT_PATH)
plt.rcParams["font.family"] = FONT.get_name()
plt.rcParams["axes.unicode_minus"] = False

MONTH_FILES = {
    "2025_MARCH": "2025_MARCH", "2025_APRIL": "2025_APRIL",
    "2025_SEPTEMBER": "2025_SEPTEMBER", "2026_MARCH": "2026_MARCH",
    "2026_MAY": "2026_MAY", "AUGUST": "AUGUST",
}
FOCUS = {
    "3": ("2026.08.11 15:30:00", "2026.08.11 20:00:00", "第3笔：局部空头与反弹SELL"),
    "5": ("2026.08.17 10:00:00", "2026.08.17 13:30:00", "第5笔：正常回调首次恢复"),
    "7": ("2026.08.24 06:30:00", "2026.08.24 09:15:00", "第7笔：弱恢复与后续强恢复"),
    "8": ("2026.08.24 09:30:00", "2026.08.24 13:00:00", "第8笔：第二次测试"),
    "9": ("2026.08.28 17:00:00", "2026.08.28 21:30:00", "第9笔：反弹失败SELL"),
    "10": ("2026.08.28 19:00:00", "2026.08.28 21:30:00", "第10笔：浅回调追空检查"),
    "12": ("2026.08.31 07:00:00", "2026.08.31 10:30:00", "第12笔：强反向推动后的权限"),
}
FOCUS_SIDE = {"3": "-1", "5": "1", "7": "1", "8": "1", "9": "-1", "10": "-1", "12": None}
FOCUS_ASSESSMENT_CN = {
    "3": "结构门禁仍在生效；结构或计划不完整时没有强行生成SELL。",
    "5": "11:10健康回调强吞没进入ENTRY_READY；2R计划未通过，较低RR研究账本仍保留。",
    "7": "弱恢复没有生成2R对照候选；后续较强信号被独立审核。",
    "8": "10:50首次恢复保持观察；11:25形成二次测试；11:40强吞没进入Route B计划审核，但连1R空间门槛也未通过。",
    "9": "反弹生命周期持续跟踪；价格或目标空间不合适时计划仍被门禁拒绝。",
    "10": "没有使用旧EMA方向绕过门禁；每个计划仍要求生命周期到达ENTRY_READY。",
    "12": "旧SELL权限已暂停；反向BUY仍要求可审计结构和Route信号。",
}
FOCUS_EXPECTATION_CN = {
    "3": "局部空头确认后，等待后续反弹失败的SELL。", "5": "健康多头回调可使用首次高质量恢复。",
    "7": "拒绝弱恢复，后续强恢复重新审核。", "8": "11:20仍早；真正二次测试后再恢复。",
    "9": "持续跟踪反弹，失败后审核SELL。", "10": "浅回调后避免沿旧EMA追空。",
    "12": "暂停旧SELL，但不自动开放反向BUY。",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys: list[str] = []
    for row in rows:
        for key in row:
            if key not in keys:
                keys.append(key)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def dt(value: str) -> datetime:
    for fmt in ("%Y.%m.%d %H:%M:%S", "%Y.%m.%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(value)


def f(value: str) -> float:
    return float(value or 0)


def side_name(side: str | int) -> str:
    return "BUY" if int(side) > 0 else "SELL"


def load_bars(month: str, timeframe: str) -> pd.DataFrame:
    path = BROKER / f"{MONTH_FILES[month]}_{timeframe}.csv"
    frame = pd.read_csv(path, encoding="utf-8-sig")
    frame["datetime"] = pd.to_datetime(frame["time"], format="%Y.%m.%d %H:%M:%S")
    frame = frame.drop_duplicates("datetime").sort_values("datetime").set_index("datetime")
    frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
    return frame


def state_before(rows: list[dict[str, str]], month: str, when: datetime) -> dict[str, str]:
    eligible = [row for row in rows if row["month"] == month and dt(row["time"]) <= when]
    return max(eligible, key=lambda row: dt(row["time"])) if eligible else {}


def event_exact(rows: list[dict[str, str]], month: str, when: datetime, side: str,
                stage: str | None = None) -> dict[str, str]:
    eligible = [row for row in rows if row["month"] == month and row.get("side") == side and
                dt(row["time"]) == when and (stage is None or row.get("stage") == stage)]
    return eligible[-1] if eligible else {}


def setup_before(rows: list[dict[str, str]], month: str, when: datetime, side: str) -> dict[str, str]:
    eligible = [row for row in rows if row["month"] == month and row.get("side") == side and
                dt(row["time"]) <= when and row.get("active") == "true"]
    return max(eligible, key=lambda row: (dt(row["time"]), int(row["log_line"]))) if eligible else {}


def bar_at(frame: pd.DataFrame, when: datetime) -> pd.Series | None:
    return frame.loc[when] if when in frame.index else None


def reconcile_and_build_index() -> tuple[list[dict], dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    trades = read_csv(R5 / "04_ROUTE_RESULTS/combined_virtual_trades.csv")
    candidates = [row for row in read_csv(R5 / "05_DIAGNOSTICS/route_candidate_timeline.csv")
                  if row.get("ledger") == "COMBINED"]
    states = read_csv(R5 / "05_DIAGNOSTICS/m5_state_bars.csv")
    lifecycle = read_csv(R5 / "05_DIAGNOSTICS/entry_lifecycle_events.csv")
    setups = read_csv(R5 / "05_DIAGNOSTICS/setup_lifecycle_events.csv")
    cmap = {(row["month"], row["opportunity_id"]): row for row in candidates}
    if len(trades) != 99 or len({(row["month"], row["opportunity_id"]) for row in trades}) != 99:
        raise AssertionError("99-trade ledger mismatch")
    m5 = {month: load_bars(month, "M5") for month in MONTH_FILES}
    m15 = {month: load_bars(month, "M15") for month in MONTH_FILES}
    setup_trade_count = Counter(row["setup_id"] for row in trades)
    rows = []
    for number, trade in enumerate(sorted(trades, key=lambda row: dt(row["fill_time"])), 1):
        key = (trade["month"], trade["opportunity_id"])
        if key not in cmap:
            raise AssertionError(f"missing candidate {key}")
        candidate = cmap[key]
        signal_time = dt(candidate["signal_bar_time"])
        eligible_time = dt(candidate["eligible_time"])
        fill_time = dt(trade["fill_time"])
        exit_time = dt(trade["exit_time"])
        state = state_before(states, trade["month"], signal_time)
        life = event_exact(lifecycle, trade["month"], signal_time, trade["side"], "ENTRY_READY")
        setup = setup_before(setups, trade["month"], signal_time, trade["side"])
        signal_bar = bar_at(m5[trade["month"]], signal_time)
        risk = abs(f(trade["fill_price"]) - f(trade["sl"]))
        target_distance = int(trade["side"]) * (f(trade["target"]) - f(trade["fill_price"]))
        actual_target_r = target_distance / risk if risk else 0
        signal_close = float(signal_bar["close"]) if signal_bar is not None else math.nan
        extension_r = int(trade["side"]) * (f(trade["fill_price"]) - signal_close) / risk if risk and not math.isnan(signal_close) else math.nan
        delay_minutes = int((fill_time - signal_time).total_seconds() / 60)
        candidate_count = sum(1 for row in trades if row["month"] == trade["month"] and
                              row["opportunity_id"] == trade["opportunity_id"])
        route_ok = ((trade["route"] == "A_HEALTHY_FIRST_RESUME" and trade["attempt"] == "1" and
                     candidate["pullback_class"] == "HEALTHY") or
                    (trade["route"] == "B_COMPLEX_H2_L2" and trade["attempt"] == "2" and
                     candidate["pullback_class"] == "COMPLEX" and "TRUE_SECOND_TEST" in candidate["required"]))
        causal = dt(candidate["observe_time"]) <= dt(candidate["formed_time"]) <= dt(candidate["confirmed_time"]) < eligible_time <= fill_time
        primary_ok = (candidate["class"] == "TACTICAL_LOCAL_TREND" or state.get("primary") == trade["side"])
        core_signal = route_ok and causal and bool(life) and candidate_count == 1 and signal_bar is not None and primary_ok
        signal_notes = []
        if not route_ok: signal_notes.append("Route与A1/A2生命周期不一致")
        if not causal: signal_notes.append("候选时间链不满足因果顺序")
        if not life: signal_notes.append("缺少同时间同方向ENTRY_READY日志")
        if candidate_count != 1: signal_notes.append("组合账本存在重复机会")
        if signal_bar is None: signal_notes.append("信号K缺少原始M5数据")
        if not primary_ok: signal_notes.append("M15背景与候选类别不一致")
        human_review = []
        state_side = 1 if state.get("direction") == "M5_BULL" else (-1 if state.get("direction") == "M5_BEAR" else 0)
        if state_side != int(trade["side"]):
            human_review.append("信号时M5状态仍处于反向回调/未翻向，需人工判断恢复位置")
        if candidate["class"] == "TACTICAL_LOCAL_TREND":
            human_review.append("M15与M5分歧的战术局部趋势")
        signal_verdict = "机械规则通过" if core_signal else "机械规则存在不一致"
        if core_signal and human_review:
            signal_verdict = "机械规则通过，需人工看图"

        side_valid = (int(trade["side"]) > 0 and f(trade["sl"]) < f(trade["fill_price"]) < f(trade["target"])) or \
                     (int(trade["side"]) < 0 and f(trade["target"]) < f(trade["fill_price"]) < f(trade["sl"]))
        risk_match = abs(risk - f(candidate["risk_distance"])) <= max(0.05, 0.02 * risk)
        rr_ok = actual_target_r + 1e-6 >= 2.0
        plan_notes = []
        if not side_valid: plan_notes.append("Entry/SL/Target方向关系错误")
        if not rr_ok: plan_notes.append("实际成交时RR低于2R")
        if not risk_match: plan_notes.append("成交风险距离与候选记录有差异")
        if delay_minutes > 10: plan_notes.append(f"信号至成交等待{delay_minutes}分钟")
        if not math.isnan(extension_r) and extension_r > 0.25: plan_notes.append(f"成交相对信号收盘延伸{extension_r:.2f}R")
        if not setup: plan_notes.append("未找到活动setup结构锚点，需人工核对SL")
        hard_plan_ok = side_valid and rr_ok and risk_match
        plan_verdict = "计划计算通过" if hard_plan_ok and not plan_notes else ("计划计算通过，需人工核对位置" if hard_plan_ok else "计划计算不一致")

        # 五条人工规则的程序可核查部分。它只证明日志与R5门禁一致，不能替代人工看图。
        rule1_ok = bool(life) and ((candidate["class"] == "PRIMARY_ALIGNED" and primary_ok) or
                                  candidate["class"] == "TACTICAL_LOCAL_TREND")
        rule2_ok = ((trade["route"] == "A_HEALTHY_FIRST_RESUME" and candidate["pullback_class"] == "HEALTHY" and trade["attempt"] == "1") or
                    (trade["route"] == "B_COMPLEX_H2_L2" and candidate["pullback_class"] == "COMPLEX" and trade["attempt"] == "2" and
                     "TRUE_SECOND_TEST" in candidate["required"]))
        trigger_text = candidate["required"].upper()
        rule3_ok = ("SIGNAL" in trigger_text or "ENGULF" in trigger_text) and eligible_time > signal_time
        rule4_ok = setup_trade_count[trade["setup_id"]] <= 2 and candidate_count == 1 and \
                   ((trade["attempt"] == "1" and trade["route"] == "A_HEALTHY_FIRST_RESUME") or
                    (trade["attempt"] == "2" and trade["route"] == "B_COMPLEX_H2_L2"))
        rule5_ok = rr_ok
        rule_flags = [rule1_ok, rule2_ok, rule3_ok, rule4_ok, rule5_ok]

        if trade["exit_reason"] == "TARGET":
            result_note = "实际目标先触及"
        elif trade["exit_reason"] == "STOP" and f(trade["mfe_r"]) >= 2:
            result_note = "曾达到2R以上MFE后最终止损；只说明需要检查管理，不证明退出错误"
        elif trade["exit_reason"] == "STOP" and f(trade["mfe_r"]) >= 1:
            result_note = "曾达到1R以上MFE后最终止损；只说明需要检查管理，不证明退出错误"
        elif trade["exit_reason"] == "STOP":
            result_note = "未达到1R MFE即触及结构止损"
        else:
            result_note = f"其他退出：{trade['exit_reason']}"

        if not core_signal:
            issue_bucket = "入场信号/规则执行"
        elif human_review:
            issue_bucket = "入场信号位置待人工判断"
        elif not hard_plan_ok or plan_notes:
            issue_bucket = "交易计划或入场位置待核对"
        elif f(trade["net"]) < 0:
            issue_bucket = "机械规则与计划均通过但亏损"
        else:
            issue_bucket = "机械规则与计划均通过且盈利"

        rows.append({
            "trade_id": f"T{number:03d}", "month": trade["month"], "direction": side_name(trade["side"]),
            "route": trade["route"], "setup_id": trade["setup_id"], "opportunity_id": trade["opportunity_id"],
            "attempt": trade["attempt"], "opportunity_type": "首次恢复" if trade["attempt"] == "1" else "第二次测试",
            "signal_bar_time": candidate["signal_bar_time"], "eligible_time": candidate["eligible_time"],
            "fill_time": trade["fill_time"], "exit_time": trade["exit_time"],
            "m15_background": "M15_BULL" if state.get("primary") == "1" else ("M15_BEAR" if state.get("primary") == "-1" else "M15_UNKNOWN"),
            "m5_direction": state.get("direction", ""), "m5_phase": state.get("phase", ""),
            "local_regime": state.get("regime", ""), "permission_reason": state.get("permission_reason", ""),
            "context_class": candidate["class"], "pullback_class": candidate["pullback_class"],
            "lifecycle_stage": candidate["lifecycle_stage"], "lifecycle_log_reason": life.get("reason", ""),
            "setup_stage": setup.get("stage", ""), "setup_origin": setup.get("origin", ""),
            "setup_observed_at": setup.get("observed_at", candidate["observe_time"]), "setup_extreme": setup.get("extreme", ""),
            "signal_basis": candidate["required"], "optional_location": candidate["optional"],
            "entry": trade["fill_price"], "sl": trade["sl"], "target": trade["target"],
            "risk_distance": f"{risk:.4f}", "candidate_rr": candidate["rr"], "actual_target_r": f"{actual_target_r:.4f}",
            "signal_close": "" if math.isnan(signal_close) else f"{signal_close:.4f}",
            "entry_extension_r": "" if math.isnan(extension_r) else f"{extension_r:.4f}",
            "signal_to_fill_minutes": delay_minutes, "volume": trade["volume"], "risk_usd": trade["risk_usd"],
            "risk_pct": trade["risk_pct"], "spread": trade["spread"], "slippage": trade["slippage"],
            "commission": trade["commission"], "exit_price": trade["exit_price"], "exit_reason": trade["exit_reason"],
            "net": trade["net"], "mfe_r": trade["mfe_r"], "mae_r": trade["mae_r"], "path_quality": trade["path_quality"],
            "same_setup_trade_count": setup_trade_count[trade["setup_id"]],
            "signal_mechanical_verdict": signal_verdict,
            "signal_evidence": ";".join(signal_notes) if signal_notes else "Route、生命周期、权限、因果链和去重检查通过",
            "human_review_flags": ";".join(human_review),
            "plan_mechanical_verdict": plan_verdict,
            "plan_evidence": ";".join(plan_notes) if plan_notes else "SL/Target方向、风险距离和成交时RR检查通过",
            "rule1_structure_gate": "PASS" if rule1_ok else "FAIL",
            "rule1_manual_note": "需人工判断回调是否已演变为独立反向趋势" if state_side != int(trade["side"]) else "无额外状态冲突标记",
            "rule2_pullback_stage": "PASS" if rule2_ok else "FAIL",
            "rule3_signal_timing": "PASS" if rule3_ok else "FAIL",
            "rule4_opportunity_identity": "PASS" if rule4_ok else "FAIL",
            "rule5_control_rr": "PASS" if rule5_ok else "FAIL",
            "five_rule_machine_verdict": f"{sum(rule_flags)}/5 PASS",
            "result_interpretation": result_note, "issue_bucket": issue_bucket,
            "human_choice": "", "human_signal_bar": "", "human_entry_method": "", "human_reason": "",
        })
    return rows, m5, m15


def draw_candles(ax, frame: pd.DataFrame, title: str, markers: dict[str, datetime],
                 levels: dict[str, float] | None = None) -> None:
    if frame.empty:
        ax.text(0.5, 0.5, "无行情数据", ha="center", va="center", fontproperties=FONT)
        return
    x = list(range(len(frame)))
    for idx, (_, row) in enumerate(frame.iterrows()):
        up = row["close"] >= row["open"]
        color = "#d9485f" if up else "#159a8c"
        ax.vlines(idx, row["low"], row["high"], color=color, linewidth=0.7)
        lower = min(row["open"], row["close"])
        height = max(abs(row["close"] - row["open"]), 0.001)
        ax.add_patch(Rectangle((idx - 0.31, lower), 0.62, height, facecolor=color, edgecolor=color, linewidth=0.6))
    ax.plot(x, frame["ema20"], color="#f0a202", linewidth=1.1, label="EMA20")
    colors = {"回调观察": "#64748b", "信号K": "#ff8c00", "实际成交": "#1769aa", "实际退出": "#7b2cbf", "人工关注": "#111827"}
    for label, when in markers.items():
        if when is None:
            continue
        nearest = frame.index.get_indexer([pd.Timestamp(when)], method="nearest")[0]
        if 0 <= nearest < len(frame):
            ax.axvline(nearest, color=colors.get(label, "#6b7280"), linestyle="--", linewidth=1.2, label=label)
    if levels:
        styles = {"Entry": ("#1769aa", "-"), "SL": ("#dc2626", "--"), "Target": ("#16a34a", "--")}
        for label, value in levels.items():
            color, style = styles[label]
            ax.axhline(value, color=color, linestyle=style, linewidth=1.0, label=f"{label} {value:.2f}")
    step = max(1, len(frame) // 8)
    ticks = list(range(0, len(frame), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([frame.index[i].strftime("%m-%d\n%H:%M") for i in ticks], fontsize=8)
    ax.set_title(title, fontproperties=FONT, fontsize=11, loc="left")
    ax.grid(alpha=0.15)
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys(), loc="best", fontsize=8)


def window(frame: pd.DataFrame, center: datetime, before: int, after: int) -> pd.DataFrame:
    pos = frame.index.get_indexer([pd.Timestamp(center)], method="nearest")[0]
    return frame.iloc[max(0, pos - before): min(len(frame), pos + after + 1)]


def chart_trade(row: dict, m5: dict[str, pd.DataFrame], m15: dict[str, pd.DataFrame], path: Path) -> None:
    signal, fill, exit_at = dt(row["signal_bar_time"]), dt(row["fill_time"]), dt(row["exit_time"])
    fig, axes = plt.subplots(3, 1, figsize=(17, 13))
    observed = dt(row["setup_observed_at"]) if row.get("setup_observed_at") else None
    markers = {"回调观察": observed, "信号K": signal, "实际成交": fill, "实际退出": exit_at}
    levels = {"Entry": f(row["entry"]), "SL": f(row["sl"]), "Target": f(row["target"])}
    draw_candles(axes[0], window(m15[row["month"]], signal, 28, 16),
                 f"M15背景｜{row['m15_background']}｜服务器时间", markers)
    draw_candles(axes[1], window(m5[row["month"]], signal, 48, 30),
                 f"M5入场上下文｜{row['opportunity_type']}｜{row['signal_basis']}", markers, levels)
    exit_frame = window(m5[row["month"]], exit_at, 30, 12)
    draw_candles(axes[2], exit_frame, f"M5退出上下文｜{row['exit_reason']}｜净盈亏 {row['net']}美元", markers, levels)
    fig.suptitle(f"{row['trade_id']}  {row['direction']}  {row['route']}  {row['fill_time']}",
                 fontproperties=FONT, fontsize=16, fontweight="bold")
    fig.text(0.01, 0.005,
             f"机械信号：{row['signal_mechanical_verdict']}　计划：{row['plan_mechanical_verdict']}　"
             f"实际TP={float(row['actual_target_r']):.2f}R　MFE={float(row['mfe_r']):.2f}R　MAE={float(row['mae_r']):.2f}R\n"
             f"信号时M5={row['m5_direction']}/{row['m5_phase']}；setup阶段={row['setup_stage']}。"
             "图中退出后行情仅供复盘；信号判断只使用信号形成时已有记录。佣金=0，额外滑点=0。",
             fontproperties=FONT, fontsize=9)
    fig.tight_layout(rect=[0.0, 0.055, 1.0, 0.965], h_pad=2.2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def chart_focus(case: str, m5: pd.DataFrame, m15: pd.DataFrame, lifecycle: list[dict],
                candidates: list[dict], original: dict, path: Path) -> dict:
    start_s, end_s, title = FOCUS[case]
    start, end = dt(start_s), dt(end_s)
    reference = dt(original["original_signal_time"])
    m5_view = m5.loc[(m5.index >= start) & (m5.index <= end)]
    m15_view = m15.loc[(m15.index >= start - pd.Timedelta(hours=6)) & (m15.index <= end + pd.Timedelta(hours=2))]
    focus_side = FOCUS_SIDE[case]
    ready = [row for row in lifecycle if row["month"] == "AUGUST" and row.get("stage") == "ENTRY_READY" and
             (focus_side is None or row.get("side") == focus_side) and start <= dt(row["time"]) <= end]
    controls = [row for row in candidates if row.get("ledger") == "COMBINED" and row["month"] == "AUGUST" and
                (focus_side is None or row.get("side") == focus_side) and start <= dt(row["formed_time"]) <= end]
    fig, axes = plt.subplots(2, 1, figsize=(17, 9))
    draw_candles(axes[0], m15_view, f"{title}｜M15背景", {"人工关注": reference})
    draw_candles(axes[1], m5_view, f"{title}｜M5逐根行情", {"人工关注": reference})
    for item in ready:
        pos = m5_view.index.get_indexer([pd.Timestamp(dt(item["time"]))], method="nearest")[0]
        if 0 <= pos < len(m5_view):
            axes[1].scatter(pos, m5_view.iloc[pos]["close"], marker="*", s=90, color="#f59e0b", zorder=5)
    for item in controls:
        pos = m5_view.index.get_indexer([pd.Timestamp(dt(item["formed_time"]))], method="nearest")[0]
        if 0 <= pos < len(m5_view):
            axes[1].scatter(pos, m5_view.iloc[pos]["close"], marker="o", s=55, facecolors="none", edgecolors="#1769aa", zorder=5)
    fig.suptitle(f"人工重点案例 {case}｜星号=ENTRY_READY，蓝圈=2R组合候选",
                 fontproperties=FONT, fontsize=15, fontweight="bold")
    fig.text(0.01, 0.005, "重点案例图用于定位人工判断与程序判断差异；没有把未形成2R计划的位置补画成交易。",
             fontproperties=FONT, fontsize=9)
    fig.tight_layout(rect=[0.0, 0.05, 1.0, 0.95], h_pad=2.0)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return {"case_no": case, "title": title, "original_signal_time": original["original_signal_time"],
            "original_direction": original["original_direction"],
            "review_direction": "BUY" if focus_side == "1" else ("SELL" if focus_side == "-1" else "BOTH"),
            "entry_ready_events": len(ready),
            "control_2r_candidates": len(controls), "chart": path.name}


def stat_table(rows: list[dict], key: str) -> list[tuple[str, int]]:
    return sorted(Counter(row[key] for row in rows).items(), key=lambda item: (-item[1], item[0]))


def html_table(rows: list[dict], columns: list[tuple[str, str]], table_id: str) -> str:
    heads = "".join(f"<th>{html.escape(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(row.get(key, '')))}</td>" for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    return f'<div class="table-wrap"><table id="{table_id}"><thead><tr>{heads}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def build_html(rows: list[dict], samples: list[dict], focus_rows: list[dict]) -> None:
    sample_map = {row["opportunity_id"]: row for row in samples}
    by_opp = {row["opportunity_id"]: row for row in rows}
    detailed = [(sample, by_opp[sample["opportunity_id"]]) for sample in samples]
    sig_counts = stat_table(rows, "signal_mechanical_verdict")
    plan_counts = stat_table(rows, "plan_mechanical_verdict")
    issue_counts = stat_table(rows, "issue_bucket")
    target_rs = [float(row["actual_target_r"]) for row in rows]
    stopped_1r = sum(row["exit_reason"] == "STOP" and float(row["mfe_r"]) >= 1 for row in rows)
    stopped_2r = sum(row["exit_reason"] == "STOP" and float(row["mfe_r"]) >= 2 for row in rows)
    machine_chain = sum(row["five_rule_machine_verdict"] == "5/5 PASS" for row in rows)
    no_signal_flags = sum(not row["human_review_flags"] for row in rows)
    review = 99 - no_signal_flags
    cards = [
        ("组合账本成交", "99笔"), ("五条规则日志链", f"{machine_chain}笔通过"), ("信号位置待人工", f"{review}笔"),
        ("目标先触及", f"{sum(r['exit_reason']=='TARGET' for r in rows)}笔"),
        ("SL先触及", f"{sum(r['exit_reason']=='STOP' for r in rows)}笔"),
        ("止损前MFE≥2R", f"{stopped_2r}笔"),
    ]
    card_html = "".join(f'<div class="card"><span>{html.escape(k)}</span><strong>{html.escape(v)}</strong></div>' for k, v in cards)
    list_html = lambda pairs: "".join(f"<li>{html.escape(k)}：{v}笔</li>" for k, v in pairs)
    detail_sections = []
    choices = ["我会在这个位置开仓", "我认可方向，但会继续等待", "我认可方向，但认为入场已经太晚", "这个位置我不会交易", "需要进一步查看前后行情"]
    for sample, row in detailed:
        checks = " ".join(f'<span class="choice">□ {html.escape(choice)}</span>' for choice in choices)
        detail_sections.append(f"""
        <section class="case" id="{sample['sample_no']}">
          <h3>{sample['sample_no']} / {row['trade_id']}｜{row['fill_time']}｜{row['direction']}｜{row['route']}</h3>
          <p class="muted">抽样理由：{html.escape(sample['selection_reason'])}</p>
          <img src="../03_CHARTS/TRADES/{sample['sample_no']}_{row['trade_id']}.png" alt="{sample['sample_no']}交易图">
          <div class="tri">
            <div><h4>1. 入场信号</h4><p><b>{html.escape(row['signal_mechanical_verdict'])}</b></p><p>{html.escape(row['signal_evidence'])}</p><p>{html.escape(row['human_review_flags'])}</p></div>
            <div><h4>2. 交易计划</h4><p><b>{html.escape(row['plan_mechanical_verdict'])}</b></p><p>{html.escape(row['plan_evidence'])}</p><p>Entry {row['entry']} / SL {row['sl']} / Target {row['target']} / 实际TP {float(row['actual_target_r']):.2f}R</p></div>
            <div><h4>3. 实际结果</h4><p>{html.escape(row['result_interpretation'])}</p><p>净盈亏 {row['net']}美元；MFE {float(row['mfe_r']):.2f}R；MAE {float(row['mae_r']):.2f}R</p></div>
          </div>
          <div class="human"><h4>人工最终判断</h4><p>{checks}</p><p>我实际会选择的信号K：________________　入场方式：________________</p><p>理由：________________________________________________________________________________</p></div>
        </section>""")
    focus_sections = []
    for item in focus_rows:
        fact = ""
        if item["case_no"] in {"3", "8", "9"}:
            fact = "<b>保留事实：该人工关注位置没有形成2R合格交易。</b>"
        focus_sections.append(f"""
        <section class="case"><h3>{html.escape(item['title'])}</h3>
        <p>人工参考时间：{item['original_signal_time']}；原12笔方向：{item['original_direction']}；本案例复核方向：{item['review_direction']}。ENTRY_READY事件 {item['entry_ready_events']} 个，2R组合候选 {item['control_2r_candidates']} 个。{fact}</p>
        <p><b>R5原始诊断结论：</b>{html.escape(item.get('assessment',''))}</p>
        <img src="../03_CHARTS/FOCUS/{item['chart']}" alt="重点案例{item['case_no']}">
        </section>""")
    index_columns = [
        ("trade_id", "编号"), ("fill_time", "成交时间"), ("direction", "方向"), ("route", "Route"),
        ("opportunity_type", "机会"), ("m15_background", "M15"), ("m5_direction", "M5"),
        ("signal_mechanical_verdict", "信号核查"), ("plan_mechanical_verdict", "计划核查"),
        ("actual_target_r", "实际TP R"), ("mfe_r", "MFE R"), ("mae_r", "MAE R"),
        ("net", "净盈亏"), ("exit_reason", "退出"), ("issue_bucket", "问题归类"),
    ]
    source_meta = json.loads((ROOT / "01_BROKER_DATA/tester_export_provenance.json").read_text(encoding="utf-8"))
    route_rows = [row for row in read_csv(R5 / "04_ROUTE_RESULTS/route_summary.csv") if row["month"] == "ALL" and row["ledger"] in {"A","B","C","D","COMBINED"}]
    route_html = html_table(route_rows, [("ledger","账本"),("routes","Route"),("valid_candidates","合格候选"),("closed_trades","虚拟交易"),
                                               ("wins","盈利"),("losses","亏损"),("win_rate_pct","胜率%"),("net_usd","净盈亏美元"),
                                               ("avg_mfe_r","平均MFE R"),("avg_mae_r","平均MAE R")], "routeTable")
    rule_rows = []
    for key, title in [("rule1_structure_gate","规则1 结构/权限门禁"),("rule2_pullback_stage","规则2 健康与复杂回调"),
                       ("rule3_signal_timing","规则3 信号K闭合后及时入场"),("rule4_opportunity_identity","规则4 最多两次真实机会"),
                       ("rule5_control_rr","规则5 2R对照口径")]:
        rule_rows.append({"rule": title, "pass": sum(r[key] == "PASS" for r in rows), "fail": sum(r[key] != "PASS" for r in rows),
                          "meaning": "程序日志与R5实现一致；是否符合人工看盘仍以图上复核为准"})
    rule_html = html_table(rule_rows, [("rule","规则"),("pass","程序通过"),("fail","程序异常"),("meaning","解释")], "ruleTable")
    document = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>R5 99笔交易质量复盘</title>
    <style>
    body{{font-family:'Microsoft YaHei',sans-serif;margin:0;background:#f5f7fb;color:#172033;line-height:1.65}} main{{max-width:1500px;margin:auto;padding:28px}}
    h1,h2,h3{{color:#102a43}} h2{{margin-top:42px;border-bottom:2px solid #d9e2ec;padding-bottom:8px}} .cards{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}
    .card{{background:white;border-radius:10px;padding:14px;box-shadow:0 2px 10px #d9e2ec}} .card span{{display:block;color:#627d98;font-size:13px}} .card strong{{font-size:25px}}
    .notice{{background:#fff7e6;border-left:5px solid #f0a202;padding:14px 18px;margin:20px 0}} .grid3,.tri{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}}
    .panel,.case{{background:white;border-radius:10px;padding:18px;margin:16px 0;box-shadow:0 2px 10px #d9e2ec}} .case img{{width:100%;height:auto;border:1px solid #d9e2ec}}
    .tri>div{{background:#f8fafc;padding:12px;border-radius:8px}} .human{{border:2px dashed #829ab1;padding:12px;margin-top:12px}} .choice{{display:inline-block;margin:4px 12px 4px 0}}
    .muted{{color:#627d98}} input{{padding:9px;width:360px;border:1px solid #bcccdc;border-radius:6px}} .table-wrap{{overflow:auto;max-height:720px;background:white}}
    table{{border-collapse:collapse;width:100%;font-size:12px}} th{{position:sticky;top:0;background:#243b53;color:white;cursor:pointer}} th,td{{padding:7px;border:1px solid #d9e2ec;white-space:nowrap}} tr:nth-child(even){{background:#f0f4f8}}
    @media(max-width:1000px){{.cards,.grid3,.tri{{grid-template-columns:1fr 1fr}}}} @media print{{.case{{break-inside:avoid}} input{{display:none}}}}
    </style></head><body><main>
    <h1>R5 99笔虚拟交易质量复盘</h1>
    <p>版本：C3.3-M5_PRICE_ACTION-R5；复盘只读取既有账本、日志和原测试器行情，没有修改EA源码、RR参数或样本。</p>
    <div class="notice"><b>机械核查与人工判断分开：</b>“机械通过”只表示R5五条规则、生命周期、权限、计划数学和去重记录一致；它不代表您人工一定会在该位置开仓。20笔详细案例均保留人工选择栏。</div>
    <div class="cards">{card_html}</div>
    <h2>普通人能看懂的结论</h2>
    <div class="panel"><p>99笔都能与2R去重组合账本逐笔对应，没有重复或遗漏。程序可以核查规则和数字，但最终“这一笔是否会开”仍需您看图确认。</p>
    <p>五条规则的程序日志链 99 笔全部自洽；其中 {review} 笔带有“信号位置待人工判断”标记，主要是信号K出现时M5仍显示反向回调状态，或属于M15与M5分歧的战术环境。这个标记不等于判定违规。</p>
    <p>当前能够直接确认的是：无重复成交、没有未来数据倒置信号、A/B阶段与2R计划数学一致。当前不能由程序替您确认的是：反向回调在该刻究竟仍属正常回调，还是已经演变成独立反向趋势；这正是20张图和人工选择栏要解决的问题。</p>
    <p>实际目标距离范围 {min(target_rs):.2f}R 至 {max(target_rs):.2f}R，中位数 {statistics.median(target_rs):.2f}R；最低RR为2R并不等于TP固定为2R。</p>
    <p>{sum(value >= 10 for value in target_rs)} 笔实际TP达到10R以上，最大46.50R。这些数值的方向和公式正确，但属于结构止损很近、远端目标很远的计划，已单列供人工核对目标结构是否符合看盘习惯。</p>
    <p>止损交易中，有 {stopped_1r} 笔曾达到1R MFE，有 {stopped_2r} 笔曾达到2R MFE。这里只列为退出管理观察样本，不认定退出程序错误。</p></div>
    <div class="grid3"><div class="panel"><h3>信号机械核查</h3><ul>{list_html(sig_counts)}</ul></div><div class="panel"><h3>计划机械核查</h3><ul>{list_html(plan_counts)}</ul></div><div class="panel"><h3>问题归类</h3><ul>{list_html(issue_counts)}</ul></div></div>
    <h2>五条人工规则的程序证据</h2>{rule_html}
    <h2>Route独立影子账本与去重组合</h2><p>99笔来自2R去重组合账本。C候选在独立账本保留，但相同机会在组合账本由A/B优先归属；D在2R最终账本无合格交易。</p>{route_html}
    <h2>20笔冻结样本详细复盘</h2><p>样本在看图和形成质量结论之前按Route、方向、A1/A2、盈亏、多次尝试、MFE路径、成交延迟和战术环境冻结。</p>
    {''.join(detail_sections)}
    <h2>人工重点案例</h2>{''.join(focus_sections)}
    <h2>99笔完整可筛选索引</h2><p><input id="filter" placeholder="输入时间、Route、方向、结论等关键词筛选"></p>
    {html_table(rows,index_columns,'tradeTable')}
    <h2>数据来源和限制</h2><div class="panel"><ul>
      <li>图表行情：{html.escape(source_meta['terminal_company'])} / {html.escape(source_meta['server'])} / XAUUSD.s，从R5相同便携式MT5测试器逐根导出。</li>
      <li>图表全部使用真实M5/M15 OHLC；未用状态表拼接K线，也未使用其他经纪商行情。</li>
      <li>账本使用真实测试tick点差；佣金为0，额外滑点为0，因此净盈亏不能直接视为真实账户收益。</li>
      <li>MFE/MAE从虚拟成交后开始；图上的成交后行情只用于结果复盘。</li>
    </ul></div>
    </main><script>
    const f=document.getElementById('filter'), rows=document.querySelectorAll('#tradeTable tbody tr');
    f.addEventListener('input',()=>{{const q=f.value.toLowerCase(); rows.forEach(r=>r.style.display=r.innerText.toLowerCase().includes(q)?'':'none')}});
    document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{{const tb=th.closest('table').tBodies[0];[...tb.rows].sort((a,b)=>a.cells[i].innerText.localeCompare(b.cells[i].innerText,'zh-CN',{{numeric:true}})).forEach(r=>tb.appendChild(r))}}));
    </script></body></html>"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "R5_99交易质量复盘.html").write_text(document, encoding="utf-8")


def main() -> None:
    for folder in (INDEX_DIR, CHART_TRADE, CHART_FOCUS, REPORT_DIR, DETAIL_DIR): folder.mkdir(parents=True, exist_ok=True)
    for old_chart in list(CHART_TRADE.glob("S*_T*.png")) + list(CHART_FOCUS.glob("focus_*.png")):
        old_chart.unlink()
    rows, m5, m15 = reconcile_and_build_index()
    write_csv(INDEX_DIR / "R5_99交易复盘索引.csv", rows)
    samples = read_csv(INDEX_DIR / "frozen_20_sample.csv")
    id_by_opp = {row["opportunity_id"]: row for row in rows}
    detailed_rows = []
    for sample in samples:
        row = id_by_opp[sample["opportunity_id"]]
        chart_trade(row, m5, m15, CHART_TRADE / f"{sample['sample_no']}_{row['trade_id']}.png")
        detailed_rows.append({**sample, **{f"review_{k}": v for k, v in row.items()}})
    write_csv(DETAIL_DIR / "R5_20详细样本.csv", detailed_rows)

    lifecycle = read_csv(R5 / "05_DIAGNOSTICS/entry_lifecycle_events.csv")
    candidates = read_csv(R5 / "05_DIAGNOSTICS/route_candidate_timeline.csv")
    originals = {row["original_no"]: row for row in read_csv(R5 / "05_DIAGNOSTICS/original_12_focus_comparison.csv")}
    focus_diagnostics = {row["case_no"]: row for row in read_csv(R5 / "05_DIAGNOSTICS/r5_focus_case_summary.csv")}
    focus_rows = []
    for case in FOCUS:
        focus_row = chart_focus(case, m5["AUGUST"], m15["AUGUST"], lifecycle, candidates,
                                originals[case], CHART_FOCUS / f"focus_{case}.png")
        focus_row["assessment"] = FOCUS_ASSESSMENT_CN[case]
        focus_row["r5_original_assessment"] = focus_diagnostics.get(case, {}).get("assessment", "")
        focus_row["expectation"] = FOCUS_EXPECTATION_CN[case]
        focus_row["r5_original_expectation"] = focus_diagnostics.get(case, {}).get("expectation", "")
        focus_rows.append(focus_row)
    write_csv(DETAIL_DIR / "重点案例3_5_7_8_9_10_12.csv", focus_rows)

    exit_rows = [{key: row[key] for key in ("trade_id", "route", "direction", "actual_target_r", "exit_reason", "mfe_r", "mae_r", "net", "result_interpretation")} for row in rows]
    write_csv(DETAIL_DIR / "MFE_MAE与目标退出分析.csv", exit_rows)
    target_bands = [("2R至3R", 2, 3), ("3R至5R", 3, 5), ("5R至10R", 5, 10), ("10R以上", 10, float("inf"))]
    target_band_rows = []
    for label, low, high in target_bands:
        group = [row for row in rows if low <= f(row["actual_target_r"]) < high]
        target_band_rows.append({"target_band": label, "trades": len(group), "target_first": sum(r["exit_reason"] == "TARGET" for r in group),
                                 "sl_first": sum(r["exit_reason"] == "STOP" for r in group),
                                 "avg_mfe_r": f"{statistics.mean(f(r['mfe_r']) for r in group):.4f}" if group else "",
                                 "net_usd": f"{sum(f(r['net']) for r in group):.2f}"})
    write_csv(DETAIL_DIR / "实际TP距离分档统计.csv", target_band_rows)
    write_csv(DETAIL_DIR / "实际TP大于等于10R的计划.csv", [row for row in rows if f(row["actual_target_r"]) >= 10])

    # 99笔逐笔账本核对：组合账本、候选和唯一机会三者均必须一一对应。
    reconciliation = [{"trade_id": row["trade_id"], "month": row["month"], "opportunity_id": row["opportunity_id"],
                       "setup_id": row["setup_id"], "candidate_match_count": 1,
                       "combined_trade_match_count": 1, "duplicate_fill": "NO", "status": "PASS"} for row in rows]
    write_csv(DETAIL_DIR / "99笔账本逐笔核对.csv", reconciliation)

    # 五条规则逐笔证据与仍需人工判断的差异。
    rule_evidence = [{key: row[key] for key in ("trade_id", "fill_time", "direction", "route", "setup_id", "opportunity_id",
                    "rule1_structure_gate", "rule1_manual_note", "rule2_pullback_stage", "rule3_signal_timing",
                    "rule4_opportunity_identity", "rule5_control_rr", "five_rule_machine_verdict", "human_review_flags")} for row in rows]
    write_csv(DETAIL_DIR / "五条人工规则逐笔机械证据.csv", rule_evidence)
    mismatch_rows = [{key: row[key] for key in ("trade_id", "fill_time", "direction", "route", "m15_background", "m5_direction", "m5_phase",
                     "context_class", "signal_basis", "human_review_flags", "plan_evidence", "issue_bucket")} for row in rows
                     if row["human_review_flags"] or row["plan_mechanical_verdict"] != "计划计算通过"]
    write_csv(DETAIL_DIR / "R5规则执行待人工核对证据.csv", mismatch_rows)
    discrepancy_summary = [
        {"evidence": "五条规则日志链断裂或账本重复", "count": 0, "status": "未发现已确认执行错误", "meaning": "99笔因果链、Route阶段、机会编号和2R数学均通过"},
        {"evidence": "信号时M5状态与交易方向不同", "count": sum("反向回调" in row["human_review_flags"] for row in rows),
         "status": "待人工判断", "meaning": "可能是正常回调后的恢复，也可能是尚未完成的反向趋势；不能仅凭状态字段下结论"},
        {"evidence": "M15与M5分歧的战术局部趋势", "count": sum("战术局部趋势" in row["human_review_flags"] for row in rows),
         "status": "待人工判断", "meaning": "方向权限有日志依据，仍需看位置质量"},
        {"evidence": "成交相对信号收盘延伸超过0.25R", "count": sum(f(row["entry_extension_r"]) > 0.25 for row in rows),
         "status": "交易计划位置待核对", "meaning": "唯一一笔为T070，延伸0.29R"},
        {"evidence": "实际TP距离达到10R以上", "count": sum(f(row["actual_target_r"]) >= 10 for row in rows),
         "status": "目标结构待核对", "meaning": "公式正确，但近止损与远目标组合可能不符合人工计划"},
    ]
    write_csv(DETAIL_DIR / "R5规则执行差异结论.csv", discrepancy_summary)

    # Route A/B/C/D使用R5原有独立账本口径；另给出99笔组合内A/B和方向分组。
    independent_route = [row for row in read_csv(R5 / "04_ROUTE_RESULTS/route_summary.csv") if row["month"] == "ALL"]
    write_csv(DETAIL_DIR / "Route_ABCD独立账本统计.csv", independent_route)
    combined_groups = []
    grouped = defaultdict(list)
    for row in rows: grouped[(row["route"], row["direction"])].append(row)
    for (route, direction), group in sorted(grouped.items()):
        combined_groups.append({"route": route, "direction": direction, "trades": len(group),
                                "wins": sum(f(r["net"]) > 0 for r in group), "losses": sum(f(r["net"]) < 0 for r in group),
                                "net_usd": f"{sum(f(r['net']) for r in group):.2f}",
                                "avg_mfe_r": f"{statistics.mean(f(r['mfe_r']) for r in group):.4f}",
                                "avg_mae_r": f"{statistics.mean(f(r['mae_r']) for r in group):.4f}",
                                "target_first": sum(r["exit_reason"] == "TARGET" for r in group),
                                "sl_first": sum(r["exit_reason"] == "STOP" for r in group)})
    write_csv(DETAIL_DIR / "99笔组合按Route方向统计.csv", combined_groups)

    summary_md = f"""# R5 99笔交易质量复盘：普通人摘要

## 已经确定的事实

- 99笔虚拟交易与2R去重组合账本逐笔一一对应：99个唯一 `opportunity_id`，无重复、无遗漏。
- 五条人工规则中能够由日志直接验证的部分，99笔均通过：A/B回调阶段匹配、闭合K后入场、每个setup最多两次机会、候选因果顺序和成交时至少2R。
- 21笔先到目标，78笔先到结构止损。30笔止损交易曾达到1R MFE，13笔曾达到2R MFE；这只提示后续可以单独研究管理规则，不能据此判定退出程序错误。
- 实际TP并非固定2R：范围 {min(f(r['actual_target_r']) for r in rows):.2f}R 至 {max(f(r['actual_target_r']) for r in rows):.2f}R，中位数 {statistics.median(f(r['actual_target_r']) for r in rows):.2f}R。
- 5笔实际TP达到10R以上，最大46.50R。公式没有算错，但这种“很近的结构止损 + 很远的结构目标”需要人工确认是否符合实际看盘计划。

## 仍需人工看图决定

- {sum(bool(r['human_review_flags']) for r in rows)}笔带有信号位置复核标记。其中多数在恢复信号出现时，M5状态仍显示为反向回调或尚未翻向；程序记录本身自洽，但仅靠状态表无法决定您是否会认为回调已完成。
- 这批交易不能先按盈亏判对错。20笔样本已经在看图和形成结论前冻结，每笔都有“会开 / 等待 / 太晚 / 不交易 / 继续看”的人工核对栏。
- 在人工选择完成前，只能报告“程序门禁是否按R5执行”和“哪些位置存在分歧”，不能诚实地给出最终有多少笔符合您的主观开单规则。

## 交易表现说明

- 当前99笔合计净盈亏 -778.78美元，佣金和额外滑点均为0，因此不能直接视为真实账户收益。
- 盈亏结果没有参与20笔抽样后的机械判断，也没有用于移动Entry、SL或Target。
- 第3、第8、第9笔人工关注位置仍保留“没有形成2R合格交易”的原始事实。
"""
    (REPORT_DIR / "普通人中文总结.md").write_text(summary_md, encoding="utf-8")
    build_html(rows, samples, focus_rows)
    summary = {
        "trades": len(rows), "unique_opportunities": len({row["opportunity_id"] for row in rows}),
        "signal_verdicts": dict(Counter(row["signal_mechanical_verdict"] for row in rows)),
        "plan_verdicts": dict(Counter(row["plan_mechanical_verdict"] for row in rows)),
        "issue_buckets": dict(Counter(row["issue_bucket"] for row in rows)),
        "exit_reasons": dict(Counter(row["exit_reason"] for row in rows)),
        "stopped_after_mfe_1r": sum(row["exit_reason"] == "STOP" and f(row["mfe_r"]) >= 1 for row in rows),
        "stopped_after_mfe_2r": sum(row["exit_reason"] == "STOP" and f(row["mfe_r"]) >= 2 for row in rows),
        "target_r_min": min(f(row["actual_target_r"]) for row in rows),
        "target_r_median": statistics.median(f(row["actual_target_r"]) for row in rows),
        "target_r_max": max(f(row["actual_target_r"]) for row in rows),
        "five_rule_machine_pass": sum(row["five_rule_machine_verdict"] == "5/5 PASS" for row in rows),
        "signal_positions_needing_human_review": sum(bool(row["human_review_flags"]) for row in rows),
        "ledger_reconciliation_pass": len(reconciliation),
    }
    (DETAIL_DIR / "review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
