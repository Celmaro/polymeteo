"""Trading Reports for Daily, Weekly, and Monthly Analysis.

Generates formatted reports for performance tracking.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ReportPeriod(str, Enum):
    """Report time periods."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class TradeSummary:
    """Summary of a single trade."""

    trade_id: str
    timestamp: datetime
    side: str
    token_id: str
    size_usd: float
    price: float
    pnl: float
    quorum_size: int
    execution_type: str  # "twap", "market", "limit"
    slippage_bps: float


@dataclass
class DailyReport:
    """Daily trading report."""

    date: datetime
    starting_balance: float
    ending_balance: float

    # Trade Stats
    total_trades: int
    winning_trades: int
    losing_trades: int

    # P&L
    realized_pnl: float
    unrealized_pnl: float
    daily_pnl: float

    # Trade Details
    biggest_win: float
    biggest_loss: float
    avg_trade_size: float
    avg_trade_duration_minutes: float

    # System Stats
    quorum_hits: int
    quorum_total_signals: int
    obi_skips: int
    avg_latency_ms: float
    error_count: int

    # Risk Stats
    peak_drawdown_pct: float
    peak_balance: float

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.winning_trades / self.total_trades) * 100

    @property
    def pnl_pct(self) -> float:
        if self.starting_balance == 0:
            return 0.0
        return (self.daily_pnl / self.starting_balance) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "date": self.date.strftime("%Y-%m-%d"),
            "balance": {
                "start": self.starting_balance,
                "end": self.ending_balance,
                "change": self.daily_pnl,
                "change_pct": self.pnl_pct,
            },
            "trades": {
                "total": self.total_trades,
                "wins": self.winning_trades,
                "losses": self.losing_trades,
                "win_rate": self.win_rate,
            },
            "pnl": {
                "realized": self.realized_pnl,
                "unrealized": self.unrealized_pnl,
                "total": self.daily_pnl,
            },
            "performance": {
                "biggest_win": self.biggest_win,
                "biggest_loss": self.biggest_loss,
                "avg_size": self.avg_trade_size,
            },
            "system": {
                "quorum_hits": self.quorum_hits,
                "quorum_total": self.quorum_total_signals,
                "obi_skips": self.obi_skips,
                "avg_latency_ms": self.avg_latency_ms,
                "errors": self.error_count,
            },
            "risk": {
                "peak_drawdown": self.peak_drawdown_pct * 100,
                "peak_balance": self.peak_balance,
            },
        }


@dataclass
class WeeklyReport:
    """Weekly trading report."""

    week_start: datetime
    week_end: datetime
    daily_reports: list[DailyReport]

    @property
    def total_pnl(self) -> float:
        return sum(r.daily_pnl for r in self.daily_reports)

    @property
    def total_trades(self) -> int:
        return sum(r.total_trades for r in self.daily_reports)

    @property
    def total_wins(self) -> int:
        return sum(r.winning_trades for r in self.daily_reports)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return (self.total_wins / self.total_trades) * 100

    @property
    def avg_daily_pnl(self) -> float:
        if not self.daily_reports:
            return 0.0
        return self.total_pnl / len(self.daily_reports)

    @property
    def max_daily_gain(self) -> float:
        return max((r.daily_pnl for r in self.daily_reports), default=0.0)

    @property
    def max_daily_loss(self) -> float:
        return min((r.daily_pnl for r in self.daily_reports), default=0.0)

    @property
    def sharpe_ratio(self) -> float:
        """Estimated Sharpe ratio."""
        if not self.daily_reports or len(self.daily_reports) < 2:
            return 0.0

        pnls = [r.daily_pnl for r in self.daily_reports]
        mean_pnl = sum(pnls) / len(pnls)

        variance = sum((p - mean_pnl) ** 2 for p in pnls) / len(pnls)
        std_dev = variance**0.5

        if std_dev == 0:
            return 0.0

        # Annualized Sharpe (assuming 252 trading days)
        return (mean_pnl / std_dev) * (252**0.5) if std_dev > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": {
                "start": self.week_start.strftime("%Y-%m-%d"),
                "end": self.week_end.strftime("%Y-%m-%d"),
            },
            "summary": {
                "total_pnl": self.total_pnl,
                "total_trades": self.total_trades,
                "win_rate": self.win_rate,
                "avg_daily_pnl": self.avg_daily_pnl,
            },
            "extremes": {
                "max_daily_gain": self.max_daily_gain,
                "max_daily_loss": self.max_daily_loss,
            },
            "risk": {
                "sharpe_ratio": self.sharpe_ratio,
            },
            "daily": [r.to_dict() for r in self.daily_reports],
        }


@dataclass
class MonthlyReport:
    """Monthly trading report."""

    month: datetime
    weekly_reports: list[WeeklyReport]

    @property
    def total_pnl(self) -> float:
        return sum(w.total_pnl for w in self.weekly_reports)

    @property
    def total_trades(self) -> int:
        return sum(w.total_trades for w in self.weekly_reports)

    @property
    def win_rate(self) -> float:
        total_wins = sum(
            sum(d.winning_trades for d in w.daily_reports) for w in self.weekly_reports
        )
        if self.total_trades == 0:
            return 0.0
        return (total_wins / self.total_trades) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "month": self.month.strftime("%Y-%m"),
            "total_pnl": self.total_pnl,
            "total_trades": self.total_trades,
            "win_rate": self.win_rate,
            "weekly": [w.to_dict() for w in self.weekly_reports],
        }


class ReportFormatter:
    """Formats reports for various outputs (console)."""

    @staticmethod
    def format_daily(daily: DailyReport) -> str:
        """Format daily report."""
        emoji = "🟢" if daily.daily_pnl >= 0 else "🔴"

        return f"""
📅 **Daily Report: {daily.date.strftime("%Y-%m-%d")}** {emoji}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **Balance**
• Start: ${daily.starting_balance:,.2f}
• End: ${daily.ending_balance:,.2f}
• P&L: ${daily.daily_pnl:+,.2f} ({daily.pnl_pct:+.2f}%)

📊 **Trades**
• Total: {daily.total_trades}
• Wins: {daily.winning_trades} | Losses: {daily.losing_trades}
• Win Rate: {daily.win_rate:.1f}%

💵 **Performance**
• Biggest Win: ${daily.biggest_win:+,.2f}
• Biggest Loss: ${daily.biggest_loss:+,.2f}
• Avg Size: ${daily.avg_trade_size:,.2f}

🔧 **System**
• Quorum: {daily.quorum_hits}/{daily.quorum_total_signals} hits
• OBI Skips: {daily.obi_skips}
• Avg Latency: {daily.avg_latency_ms:.0f}ms
• Errors: {daily.error_count}

⚠️ **Risk**
• Peak Drawdown: {daily.peak_drawdown_pct * 100:.2f}%
• Peak Balance: ${daily.peak_balance:,.2f}
"""

    @staticmethod
    def format_weekly(weekly: WeeklyReport) -> str:
        """Format weekly report."""
        return f"""
📅 **Weekly Report: {weekly.week_start.strftime("%Y-%m-%d")} to {weekly.week_end.strftime("%Y-%m-%d")}**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **Summary**
• Total P&L: ${weekly.total_pnl:+,.2f}
• Total Trades: {weekly.total_trades}
• Win Rate: {weekly.win_rate:.1f}%
• Avg Daily P&L: ${weekly.avg_daily_pnl:+,.2f}

📊 **Daily Extremes**
• Best Day: ${weekly.max_daily_gain:+,.2f}
• Worst Day: ${weekly.max_daily_loss:+,.2f}

📈 **Risk Metrics**
• Sharpe Ratio: {weekly.sharpe_ratio:.2f}

📋 **Daily Breakdown**
{chr(10).join(f"  {r.date.strftime('%a')}: ${r.daily_pnl:+,.2f}" for r in weekly.daily_reports)}
"""

    @staticmethod
    def format_monthly(monthly: MonthlyReport) -> str:
        """Format monthly report."""
        emoji = "💰" if monthly.total_pnl >= 0 else "💸"

        return f"""
📅 **Monthly Report: {monthly.month.strftime("%B %Y")}** {emoji}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💰 **Total P&L: ${monthly.total_pnl:+,.2f}**
📊 Total Trades: {monthly.total_trades}
📈 Win Rate: {monthly.win_rate:.1f}%

📋 **Weekly Performance**
{chr(10).join(f"  Week {i + 1}: ${w.total_pnl:+,.2f}" for i, w in enumerate(monthly.weekly_reports))}
"""


class ReportGenerator:
    """Generates reports from trading data."""

    def __init__(self):
        self.daily_reports: list[DailyReport] = []

    def add_daily_report(self, report: DailyReport) -> None:
        """Add a daily report."""
        self.daily_reports.append(report)
        logger.info(f"[REPORT] Added daily report for {report.date.date()}")

    def generate_daily(
        self,
        date: datetime,
        trades: list[TradeSummary],
        starting_balance: float,
        ending_balance: float,
        quorum_hits: int,
        quorum_total: int,
        obi_skips: int,
        avg_latency_ms: float,
        error_count: int,
    ) -> DailyReport:
        """Generate a daily report from trade data."""

        winning_trades = [t for t in trades if t.pnl > 0]
        losing_trades = [t for t in trades if t.pnl < 0]

        realized_pnl = sum(t.pnl for t in trades)
        unrealized_pnl = 0.0  # Would come from open positions

        # Calculate peak drawdown
        peak_balance = starting_balance
        max_drawdown = 0.0
        running_balance = starting_balance

        for trade in trades:
            running_balance += trade.pnl
            if running_balance > peak_balance:
                peak_balance = running_balance
            drawdown = (peak_balance - running_balance) / peak_balance if peak_balance > 0 else 0
            max_drawdown = max(max_drawdown, drawdown)

        report = DailyReport(
            date=date,
            starting_balance=starting_balance,
            ending_balance=ending_balance,
            total_trades=len(trades),
            winning_trades=len(winning_trades),
            losing_trades=len(losing_trades),
            realized_pnl=realized_pnl,
            unrealized_pnl=unrealized_pnl,
            daily_pnl=realized_pnl + unrealized_pnl,
            biggest_win=max((t.pnl for t in winning_trades), default=0.0),
            biggest_loss=min((t.pnl for t in losing_trades), default=0.0),
            avg_trade_size=sum(t.size_usd for t in trades) / len(trades) if trades else 0,
            avg_trade_duration_minutes=0.0,  # Would calculate from trade timestamps
            quorum_hits=quorum_hits,
            quorum_total_signals=quorum_total,
            obi_skips=obi_skips,
            avg_latency_ms=avg_latency_ms,
            error_count=error_count,
            peak_drawdown_pct=max_drawdown,
            peak_balance=peak_balance,
        )

        self.add_daily_report(report)
        return report

    def generate_weekly(self, week_start: datetime) -> WeeklyReport | None:
        """Generate weekly report from daily reports."""
        week_end = week_start + timedelta(days=6)

        weekly_daily = [
            r for r in self.daily_reports if week_start.date() <= r.date.date() <= week_end.date()
        ]

        if not weekly_daily:
            return None

        return WeeklyReport(
            week_start=week_start,
            week_end=week_end,
            daily_reports=sorted(weekly_daily, key=lambda r: r.date),
        )

    def generate_monthly(self, year: int, month: int) -> MonthlyReport | None:
        """Generate monthly report from weekly reports."""
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)

        if month == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
        else:
            month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)

        monthly_daily = [
            r for r in self.daily_reports if month_start.date() <= r.date.date() <= month_end.date()
        ]

        if not monthly_daily:
            return None

        # Group into weeks
        weeks: dict[int, list[DailyReport]] = {}
        for report in monthly_daily:
            week_num = report.date.isocalendar()[1]
            if week_num not in weeks:
                weeks[week_num] = []
            weeks[week_num].append(report)

        weekly_reports = []
        for week_num in sorted(weeks.keys()):
            week_reports = weeks[week_num]
            week_start = min(r.date for r in week_reports)
            week_end = max(r.date for r in week_reports)
            weekly_reports.append(
                WeeklyReport(
                    week_start=week_start,
                    week_end=week_end,
                    daily_reports=sorted(week_reports, key=lambda r: r.date),
                )
            )

        return MonthlyReport(
            month=month_start,
            weekly_reports=weekly_reports,
        )

    def get_recent_daily(self, days: int = 7) -> list[DailyReport]:
        """Get recent daily reports."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return [r for r in self.daily_reports if r.date >= cutoff]
