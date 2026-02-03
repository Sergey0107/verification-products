import json
from datetime import datetime
from pathlib import Path

from app.core.config import settings


def _read_comp_data(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def _write_comp_data(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def update_comp_data(section: str, payload: dict) -> None:
    filename = "result_extraction" if section == "extraction" else "result_comparison"
    comp_dir = Path(settings.COMP_DATA_DIR)
    if comp_dir.exists() and comp_dir.is_file():
        comp_dir.unlink()
    comp_dir.mkdir(parents=True, exist_ok=True)
    path = comp_dir / filename
    data = _read_comp_data(path)
    data[section] = payload
    data["updated_at"] = datetime.utcnow().isoformat() + "Z"
    _write_comp_data(path, data)
