from __future__ import annotations

from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP


DEFAULT_CURRENCY_VALUES_GC = {
    "Jelly": Decimal("10"),
    "Breath": Decimal("1"),
    "Web": Decimal("100"),
    "Kabuto": Decimal("0.5"),
    "Jawhar": Decimal("2"),
    "Baya": Decimal("5"),
}

DEFAULT_CURRENCIES = list(DEFAULT_CURRENCY_VALUES_GC.keys())
COIN_CURRENCIES = set(c for c in DEFAULT_CURRENCIES if c != "Jelly")
DEFAULT_EXCHANGE_FEE_PCT = Decimal("3")
COIN_ENC_PER_COIN = Decimal("0.1")

_CANONICAL_BY_LOWER = {k.lower(): k for k in DEFAULT_CURRENCIES}


def canonical_currency_name(name: str | None) -> str:
    raw = str(name or "").strip()
    if not raw:
        return "Jelly"
    return _CANONICAL_BY_LOWER.get(raw.lower(), raw)


def currency_value_gc(currency: str | None) -> Decimal | None:
    cur = canonical_currency_name(currency)
    return DEFAULT_CURRENCY_VALUES_GC.get(cur)


def currency_precision(currency: str | None) -> int:
    cur = canonical_currency_name(currency)
    if cur in COIN_CURRENCIES:
        # 1 gc coin = 100 bc for the same currency.
        return 100
    return 1


def _to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def major_to_minor(currency: str | None, amount, rounding: str = "half_up") -> int:
    cur = canonical_currency_name(currency)
    quant = Decimal(currency_precision(cur))
    raw = _to_decimal(amount) * quant
    mode = ROUND_HALF_UP
    if rounding == "ceil":
        mode = ROUND_CEILING
    elif rounding == "floor":
        mode = ROUND_FLOOR
    return int(raw.to_integral_value(rounding=mode))


def minor_to_major(currency: str | None, minor: int) -> Decimal:
    cur = canonical_currency_name(currency)
    quant = Decimal(currency_precision(cur))
    if not quant:
        return Decimal("0")
    return Decimal(int(minor or 0)) / quant


def minor_to_gc(currency: str | None, minor: int) -> Decimal:
    cur = canonical_currency_name(currency)
    val = currency_value_gc(cur)
    if val is None:
        return Decimal("0")
    return minor_to_major(cur, minor) * val


def gc_to_minor(currency: str | None, gc_amount, rounding: str = "ceil") -> int:
    cur = canonical_currency_name(currency)
    val = currency_value_gc(cur)
    if val is None or val <= 0:
        raise ValueError(f"Unsupported currency for conversion: {cur}")
    major = _to_decimal(gc_amount) / val
    return major_to_minor(cur, major, rounding=rounding)


def coin_breakdown(currency: str | None, minor: int) -> dict:
    cur = canonical_currency_name(currency)
    total_minor = max(0, int(minor or 0))
    if cur not in COIN_CURRENCIES:
        return {"coins": {}, "coin_count": 0}

    # Denominations are in bc units.
    pc = total_minor // 1000
    rem = total_minor % 1000
    gc = rem // 100
    rem %= 100
    sc = rem // 10
    bc = rem % 10
    return {
        "coins": {"pc": int(pc), "gc": int(gc), "sc": int(sc), "bc": int(bc)},
        "coin_count": int(pc + gc + sc + bc),
    }


def carried_coin_count(wallet: dict | None) -> int:
    if not isinstance(wallet, dict):
        return 0
    total = 0
    for currency, entry in wallet.items():
        if not isinstance(entry, dict):
            continue
        carried = int(entry.get("carried") or 0)
        total += int(coin_breakdown(currency, carried).get("coin_count") or 0)
    return total


def carried_coin_enc(wallet: dict | None) -> float:
    coins = carried_coin_count(wallet)
    return float((Decimal(coins) * COIN_ENC_PER_COIN).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

