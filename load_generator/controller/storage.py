"""Finite report admission; historical evidence is never deleted automatically."""

import os
from pathlib import Path


def check_report_budget(root: Path, reserve_bytes: int = 0) -> int:
    budget_mib = int(os.getenv("LOAD_REPORT_BUDGET_MIB", "512"))
    if not 1 <= budget_mib <= 4096:
        raise ValueError("Report budget must be between 1 and 4096 MiB")
    used = sum(file.stat().st_size for file in root.rglob("*") if file.is_file())
    if used + reserve_bytes > budget_mib * 1024**2:
        raise ValueError(
            "REPORT_STORAGE_BUDGET_EXCEEDED: archive evidence explicitly before running again"
        )
    return used
