"""Per-platform fee models for cross-platform arbitrage.

Polymarket and Kalshi keep the original simple model: a flat taker rate on the
price of each leg plus a fixed gas cost per order. PredictIt charges on
*profit* and on withdrawals, so edges for pairs that involve it are computed as
the worst case across outcome states.

A cross-platform trade is "buy token T on platform A at ``buy_price``" and
"sell token T on platform B at ``sell_price``". Selling T at ``s`` is
equivalent to buying the opposite token at ``1 - s``, so exactly one leg pays
$1 whichever way the market resolves.
"""

from dataclasses import dataclass, field
from typing import Optional

from polymarket_client.models import OrderBookSide, PriceLevel

POLYMARKET_TAKER_FEE = 0.015
KALSHI_TAKER_FEE = 0.01
GAS_COST = 0.02


@dataclass(frozen=True)
class PredictItFees:
    """PredictIt: 10% of profit on the winning leg, 5% on withdrawals (optional)."""
    profit_fee_pct: float = 0.10
    withdrawal_fee_pct: float = 0.05
    apply_withdrawal_fee: bool = False

    def payout_after_fees(self, price: float) -> float:
        """Net payout per $1 contract bought at ``price`` if it wins."""
        payout = 1.0 - self.profit_fee_pct * max(0.0, 1.0 - price)
        if self.apply_withdrawal_fee:
            payout *= 1.0 - self.withdrawal_fee_pct
        return payout


@dataclass
class FeeBreakdown:
    buy_fee: float = 0.0
    sell_fee: float = 0.0
    gas: float = 0.0
    profit_fee: float = 0.0       # PredictIt profit fee in the worst-case state
    withdrawal_fee: float = 0.0   # PredictIt withdrawal fee in the worst-case state
    total: float = 0.0
    model: str = "flat"

    def to_dict(self) -> dict:
        return {k: round(v, 6) if isinstance(v, float) else v for k, v in self.__dict__.items()}


@dataclass
class FeeModel:
    polymarket_taker_fee: float = POLYMARKET_TAKER_FEE
    kalshi_taker_fee: float = KALSHI_TAKER_FEE
    gas_cost: float = GAS_COST
    predictit: PredictItFees = field(default_factory=PredictItFees)

    def taker_rate(self, platform: str) -> float:
        if platform == "polymarket":
            return self.polymarket_taker_fee
        if platform == "kalshi":
            return self.kalshi_taker_fee
        return 0.0  # PredictIt has no per-trade fee

    def breakdown(
        self, buy_platform: str, sell_platform: str, buy_price: float, sell_price: float,
    ) -> FeeBreakdown:
        if "predictit" not in (buy_platform, sell_platform):
            # Original model, unchanged.
            buy_fee = buy_price * self.taker_rate(buy_platform)
            sell_fee = sell_price * self.taker_rate(sell_platform)
            gas = self.gas_cost * 2
            return FeeBreakdown(buy_fee, sell_fee, gas, total=buy_fee + sell_fee + gas)

        # Two-legs-bought view. Upfront per-trade fees, then the fee deducted
        # from the winning leg's payout in each outcome state; take the worse.
        leg_buy = (buy_platform, buy_price)
        leg_sell = (sell_platform, 1.0 - sell_price)
        buy_fee = leg_buy[1] * self.taker_rate(buy_platform)
        sell_fee = leg_sell[1] * self.taker_rate(sell_platform)
        gas = self.gas_cost * sum(1 for p in (buy_platform, sell_platform) if p == "polymarket")

        def deduction(platform: str, price: float) -> tuple[float, float, float]:
            if platform != "predictit":
                return 0.0, 0.0, 0.0
            profit_fee = self.predictit.profit_fee_pct * max(0.0, 1.0 - price)
            after_profit = 1.0 - profit_fee
            withdrawal = (after_profit * self.predictit.withdrawal_fee_pct
                          if self.predictit.apply_withdrawal_fee else 0.0)
            return profit_fee + withdrawal, profit_fee, withdrawal

        worst = max((deduction(*leg_buy), deduction(*leg_sell)), key=lambda d: d[0])
        total = buy_fee + sell_fee + gas + worst[0]
        return FeeBreakdown(buy_fee, sell_fee, gas, worst[1], worst[2], total, model="predictit")


# --------------------------------------------------------------- book walking
class UnknownSizeLevel(PriceLevel):
    """A price level whose size the platform does not publish (e.g. PredictIt)."""
    size_known = False

    def __init__(self, price: float):
        super().__init__(price=price, size=0.0)


def level_size(level: PriceLevel) -> Optional[float]:
    """Size at a level, or None when the platform does not publish it."""
    if getattr(level, "size_known", True) is False:
        return None
    return level.size


def top_of_book_size(side: OrderBookSide) -> Optional[float]:
    if not side.levels:
        return None
    return level_size(side.levels[0])


def walk_book(side: OrderBookSide, size: float) -> Optional[float]:
    """Volume-weighted average price for ``size`` shares, or None if unknown.

    If the book is shallower than ``size`` the average over what is available
    is returned (the size is then not fully fillable; ``depth`` shows that).
    """
    if size <= 0 or not side.levels:
        return None
    remaining, cost, filled = size, 0.0, 0.0
    for level in side.levels:
        avail = level_size(level)
        if avail is None:
            return None
        take = min(remaining, avail)
        cost += take * level.price
        filled += take
        remaining -= take
        if remaining <= 1e-12:
            break
    return cost / filled if filled else None
