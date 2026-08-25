"""Go-Live Phase Configuration.

Defines phased approach to live trading deployment.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class PhaseStatus(str, Enum):
    """Status of a deployment phase."""

    PENDING = "pending"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PhaseCriteria:
    """Success criteria for advancing from a phase."""

    min_duration_days: int = 7
    min_trades: int = 10
    min_win_rate_pct: float = 50.0
    max_drawdown_pct: float = 0.10  # 10%
    min_pnl: float = 0.0  # Can be negative if within drawdown
    max_consecutive_losses: int = 3
    no_emergency_stops: bool = True


@dataclass
class PhaseConfig:
    """Configuration for a single deployment phase."""

    phase: int
    name: str
    description: str

    # Capital allocation
    capital_usd: float
    max_position_usd: float

    # Risk limits
    max_daily_loss_usd: float
    max_drawdown_pct: float

    # Execution
    use_twap: bool = True
    max_slippage_bps: float = 50.0

    # Success criteria
    criteria: PhaseCriteria = field(default_factory=PhaseCriteria)

    # Validation
    require_backtest: bool = True
    require_paper_trading: bool = True


# Define deployment phases
DEPLOYMENT_PHASES = [
    PhaseConfig(
        phase=1,
        name="Initial Validation",
        description="Test basic functionality with minimal capital",
        capital_usd=250.0,
        max_position_usd=25.0,
        max_daily_loss_usd=15.0,
        max_drawdown_pct=0.08,
        use_twap=True,
        max_slippage_bps=30.0,
        criteria=PhaseCriteria(
            min_duration_days=7,
            min_trades=10,
            min_win_rate_pct=45.0,
            max_drawdown_pct=0.08,
            min_pnl=-10.0,  # Allow small losses
            no_emergency_stops=True,
        ),
    ),
    PhaseConfig(
        phase=2,
        name="Scale Up",
        description="Increase capital and verify consistent performance",
        capital_usd=500.0,
        max_position_usd=50.0,
        max_daily_loss_usd=30.0,
        max_drawdown_pct=0.12,
        use_twap=True,
        max_slippage_bps=50.0,
        criteria=PhaseCriteria(
            min_duration_days=14,
            min_trades=25,
            min_win_rate_pct=50.0,
            max_drawdown_pct=0.12,
            min_pnl=0.0,  # Must be profitable
            no_emergency_stops=True,
        ),
    ),
    PhaseConfig(
        phase=3,
        name="Production Ready",
        description="Full capital allocation with standard risk limits",
        capital_usd=1000.0,
        max_position_usd=100.0,
        max_daily_loss_usd=50.0,
        max_drawdown_pct=0.15,
        use_twap=True,
        max_slippage_bps=50.0,
        criteria=PhaseCriteria(
            min_duration_days=30,
            min_trades=50,
            min_win_rate_pct=55.0,
            max_drawdown_pct=0.15,
            min_pnl=0.0,
            no_emergency_stops=True,
        ),
    ),
    PhaseConfig(
        phase=4,
        name="Aggressive Growth",
        description="Maximum capital allocation for experienced operators",
        capital_usd=2000.0,
        max_position_usd=200.0,
        max_daily_loss_usd=100.0,
        max_drawdown_pct=0.20,
        use_twap=True,
        max_slippage_bps=75.0,
        criteria=PhaseCriteria(
            min_duration_days=60,
            min_trades=100,
            min_win_rate_pct=55.0,
            max_drawdown_pct=0.20,
            min_pnl=0.0,
            no_emergency_stops=True,
        ),
    ),
]


@dataclass
class PhaseProgress:
    """Progress within a phase."""

    phase: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: PhaseStatus = PhaseStatus.PENDING

    # Metrics
    trades_executed: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    emergency_stops: int = 0

    # P&L
    starting_balance: float = 0.0
    current_balance: float = 0.0
    peak_balance: float = 0.0
    current_drawdown_pct: float = 0.0

    # Days
    days_elapsed: int = 0

    def can_advance(self, criteria: PhaseCriteria) -> tuple[bool, list[str]]:
        """
        Check if phase criteria are met.

        Returns:
            Tuple of (can_advance, list_of_unmet_criteria)
        """
        unmet = []

        # Duration check
        if self.days_elapsed < criteria.min_duration_days:
            unmet.append(f"Duration: {self.days_elapsed}/{criteria.min_duration_days} days")

        # Trade count check
        if self.trades_executed < criteria.min_trades:
            unmet.append(f"Trades: {self.trades_executed}/{criteria.min_trades}")

        # Win rate check
        win_rate = (
            self.winning_trades / self.trades_executed * 100 if self.trades_executed > 0 else 0
        )
        if win_rate < criteria.min_win_rate_pct:
            unmet.append(f"Win Rate: {win_rate:.1f}% (min: {criteria.min_win_rate_pct}%)")

        # Drawdown check
        if self.current_drawdown_pct > criteria.max_drawdown_pct:
            unmet.append(
                f"Drawdown: {self.current_drawdown_pct * 100:.2f}% "
                f"(max: {criteria.max_drawdown_pct * 100:.1f}%)"
            )

        # P&L check
        pnl = self.current_balance - self.starting_balance
        if pnl < criteria.min_pnl:
            unmet.append(f"P&L: ${pnl:.2f} (min: ${criteria.min_pnl:.2f})")

        # Emergency stops check
        if self.emergency_stops > 0 and not criteria.no_emergency_stops:
            unmet.append(f"Emergency Stops: {self.emergency_stops} (max: 0)")

        return len(unmet) == 0, unmet

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status.value,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "metrics": {
                "trades": self.trades_executed,
                "wins": self.winning_trades,
                "losses": self.losing_trades,
                "win_rate": (
                    self.winning_trades / self.trades_executed * 100
                    if self.trades_executed > 0
                    else 0
                ),
            },
            "balance": {
                "start": self.starting_balance,
                "current": self.current_balance,
                "peak": self.peak_balance,
                "pnl": self.current_balance - self.starting_balance,
            },
            "risk": {
                "drawdown": self.current_drawdown_pct * 100,
                "emergency_stops": self.emergency_stops,
            },
            "progress": {
                "days_elapsed": self.days_elapsed,
            },
        }


class GoLiveManager:
    """
    Manages the phased approach to live trading deployment.

    Use this to track progress through deployment phases
    and validate advancement criteria.
    """

    def __init__(
        self,
        phases: list[PhaseConfig] = DEPLOYMENT_PHASES,
    ):
        self.phases = {p.phase: p for p in phases}
        self.current_phase: int = 1
        self.progress: dict[int, PhaseProgress] = {}

        # Initialize phase 1
        self._initialize_phase(1)

        logger.info(f"[GO-LIVE] Manager initialized with {len(phases)} phases")

    def _initialize_phase(self, phase: int) -> PhaseProgress:
        """Initialize progress tracking for a phase."""
        progress = PhaseProgress(
            phase=phase,
            status=PhaseStatus.PENDING,
        )
        self.progress[phase] = progress
        return progress

    def start_phase(self, phase: int, starting_balance: float) -> PhaseProgress:
        """
        Start a deployment phase.

        Args:
            phase: Phase number to start
            starting_balance: Starting capital for this phase

        Returns:
            PhaseProgress for the started phase
        """
        if phase not in self.phases:
            raise ValueError(f"Unknown phase: {phase}")

        if phase != self.current_phase:
            raise ValueError(f"Cannot start phase {phase}, current is {self.current_phase}")

        progress = self.progress.get(phase)
        if not progress:
            progress = self._initialize_phase(phase)

        progress.status = PhaseStatus.ACTIVE
        progress.started_at = datetime.now(timezone.utc)
        progress.starting_balance = starting_balance
        progress.current_balance = starting_balance
        progress.peak_balance = starting_balance

        logger.info(
            f"[GO-LIVE] Started Phase {phase}: {self.phases[phase].name} with ${starting_balance}"
        )

        return progress

    def record_trade(
        self,
        pnl: float,
        is_win: bool,
        current_balance: float,
    ) -> None:
        """Record a completed trade."""
        phase = self.current_phase
        progress = self.progress.get(phase)

        if not progress or progress.status != PhaseStatus.ACTIVE:
            return

        # Update metrics
        progress.trades_executed += 1
        if is_win:
            progress.winning_trades += 1
        else:
            progress.losing_trades += 1

        # Update balance
        progress.current_balance = current_balance

        if current_balance > progress.peak_balance:
            progress.peak_balance = current_balance

        # Update drawdown
        if progress.peak_balance > 0:
            progress.current_drawdown_pct = (
                progress.peak_balance - current_balance
            ) / progress.peak_balance

        # Update days elapsed
        if progress.started_at:
            progress.days_elapsed = (datetime.now(timezone.utc) - progress.started_at).days

    def record_emergency_stop(self) -> None:
        """Record an emergency stop."""
        phase = self.current_phase
        progress = self.progress.get(phase)

        if progress:
            progress.emergency_stops += 1
            logger.warning(f"[GO-LIVE] Emergency stop recorded: {progress.emergency_stops} total")

    def check_phase_completion(self) -> tuple[bool, list[str]]:
        """
        Check if current phase is complete and can advance.

        Returns:
            Tuple of (can_advance, unmet_criteria)
        """
        phase = self.current_phase
        progress = self.progress.get(phase)
        config = self.phases.get(phase)

        if not progress or not config:
            return False, ["Phase not initialized"]

        if progress.status != PhaseStatus.ACTIVE:
            return False, ["Phase not active"]

        can_advance, unmet = progress.can_advance(config.criteria)

        if can_advance:
            logger.info(f"[GO-LIVE] Phase {phase} criteria met, can advance")

        return can_advance, unmet

    def advance_phase(self, new_balance: float) -> PhaseProgress | None:
        """
        Advance to the next phase.

        Args:
            new_balance: Current balance to carry to next phase

        Returns:
            PhaseProgress for new phase, or None if no more phases
        """
        # Mark current phase complete
        current_progress = self.progress.get(self.current_phase)
        if current_progress:
            current_progress.status = PhaseStatus.COMPLETED
            current_progress.completed_at = datetime.now(timezone.utc)

        # Check for next phase
        next_phase = self.current_phase + 1

        if next_phase not in self.phases:
            logger.info("[GO-LIVE] All phases completed!")
            return None

        # Start next phase
        self.current_phase = next_phase
        next_progress = self.start_phase(next_phase, new_balance)

        logger.info(f"[GO-LIVE] Advanced to Phase {next_phase}: {self.phases[next_phase].name}")

        return next_progress

    def regress_phase(self) -> PhaseProgress | None:
        """
        Regress to previous phase (if criteria not met).

        Returns:
            PhaseProgress for regressed phase
        """
        if self.current_phase <= 1:
            logger.warning("[GO-LIVE] Already at phase 1, cannot regress")
            return None

        # Mark current phase as failed
        current_progress = self.progress.get(self.current_phase)
        if current_progress:
            current_progress.status = PhaseStatus.FAILED

        # Revert to previous phase
        self.current_phase -= 1
        prev_progress = self.progress.get(self.current_phase)

        if prev_progress:
            prev_progress.status = PhaseStatus.ACTIVE
            prev_progress.started_at = datetime.now(timezone.utc)

        logger.warning(
            f"[GO-LIVE] Regressed to Phase {self.current_phase}: "
            f"{self.phases[self.current_phase].name}"
        )

        return prev_progress

    def get_current_phase_config(self) -> PhaseConfig | None:
        """Get configuration for current phase."""
        return self.phases.get(self.current_phase)

    def get_current_progress(self) -> PhaseProgress | None:
        """Get progress for current phase."""
        return self.progress.get(self.current_phase)

    def get_status(self) -> dict[str, Any]:
        """Get overall go-live status."""
        return {
            "current_phase": self.current_phase,
            "current_phase_name": (
                self.phases.get(self.current_phase).name
                if self.current_phase in self.phases
                else None
            ),
            "total_phases": len(self.phases),
            "progress": {phase: p.to_dict() for phase, p in self.progress.items()},
            "can_advance": self.check_phase_completion()[0],
        }

    def generate_report(self) -> str:
        """Generate a formatted status report."""
        lines = [
            "=" * 50,
            "POLYMETEO GO-LIVE STATUS",
            "=" * 50,
            "",
        ]

        for phase_num in sorted(self.phases.keys()):
            config = self.phases[phase_num]
            progress = self.progress.get(phase_num)

            current_marker = "👉 " if phase_num == self.current_phase else "   "
            phase_marker = {
                PhaseStatus.PENDING: "⏳",
                PhaseStatus.ACTIVE: "🔄",
                PhaseStatus.COMPLETED: "✅",
                PhaseStatus.FAILED: "❌",
                PhaseStatus.SKIPPED: "⏭️",
            }.get(progress.status if progress else PhaseStatus.PENDING, "?")

            lines.append(f"{current_marker}{phase_marker} Phase {phase_num}: {config.name}")
            lines.append(f"      Capital: ${config.capital_usd}")

            if progress:
                if progress.status == PhaseStatus.ACTIVE:
                    lines.append(
                        f"      Progress: {progress.days_elapsed} days, "
                        f"{progress.trades_executed} trades"
                    )
                    lines.append(
                        f"      Balance: ${progress.current_balance:.2f} "
                        f"({progress.current_balance - progress.starting_balance:+.2f})"
                    )
                elif progress.status == PhaseStatus.COMPLETED:
                    lines.append(f"      Completed: {progress.completed_at.strftime('%Y-%m-%d')}")

            lines.append("")

        # Current phase details
        current_config = self.get_current_phase_config()
        current_progress = self.get_current_progress()

        if current_config and current_progress:
            lines.append("-" * 50)
            lines.append(f"Current Phase {self.current_phase} Criteria:")

            criteria = current_config.criteria
            lines.append(
                f"  • Duration: {current_progress.days_elapsed}/{criteria.min_duration_days} days"
            )
            lines.append(f"  • Trades: {current_progress.trades_executed}/{criteria.min_trades}")

            win_rate = (
                current_progress.winning_trades / current_progress.trades_executed * 100
                if current_progress.trades_executed > 0
                else 0
            )
            lines.append(f"  • Win Rate: {win_rate:.1f}% (min: {criteria.min_win_rate_pct}%)")
            lines.append(
                f"  • Drawdown: {current_progress.current_drawdown_pct * 100:.2f}% "
                f"(max: {criteria.max_drawdown_pct * 100:.1f}%)"
            )

        return "\n".join(lines)


def create_go_live_manager(
    conservative: bool = False,
) -> GoLiveManager:
    """
    Create a go-live manager with appropriate phases.

    Args:
        conservative: If True, use more conservative phase progression
    """
    phases = [p for p in DEPLOYMENT_PHASES if p.phase <= 2] if conservative else DEPLOYMENT_PHASES

    return GoLiveManager(phases=phases)
