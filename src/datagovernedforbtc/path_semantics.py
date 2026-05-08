from __future__ import annotations

from pathlib import Path


def infer_source_market_type(path: Path | str) -> str:
    """Infer raw source market type from OKX directory layer.

    Expected raw layout:
    okx/<Dataset>/<Perpetual|Spot>/<YYYY>/<file>
    """
    parts = [p.lower() for p in Path(path).parts]
    if "perpetual" in parts:
        return "perpetual"
    if "spot" in parts:
        return "spot"
    return "unknown"


def infer_instrument_type_from_path(instrument_name: str | None, path: Path | str) -> str:
    market_type = infer_source_market_type(path)
    inst = instrument_name or ""
    if market_type == "perpetual":
        if inst.endswith("-SWAP"):
            return "perpetual_swap"
        return "perpetual_unknown_contract"
    if market_type == "spot":
        return "spot"
    if inst.endswith("-SWAP"):
        return "perpetual_swap"
    if inst:
        return "spot_or_margin_unknown"
    return "unknown"
