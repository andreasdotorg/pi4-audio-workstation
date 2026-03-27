"""Hardware configuration REST endpoints (US-093).

CRUD access to amplifier and DAC YAML profiles.

Amplifiers:
    GET    /api/v1/hardware/amplifiers           List all amplifier profiles
    GET    /api/v1/hardware/amplifiers/{name}     Read one amplifier profile
    POST   /api/v1/hardware/amplifiers           Create new amplifier profile
    PUT    /api/v1/hardware/amplifiers/{name}     Update existing amplifier profile
    DELETE /api/v1/hardware/amplifiers/{name}     Delete amplifier profile

DACs:
    GET    /api/v1/hardware/dacs                 List all DAC profiles
    GET    /api/v1/hardware/dacs/{name}           Read one DAC profile
    POST   /api/v1/hardware/dacs                 Create new DAC profile
    PUT    /api/v1/hardware/dacs/{name}           Update existing DAC profile
    DELETE /api/v1/hardware/dacs/{name}           Delete DAC profile

YAML files live under ``configs/hardware/amplifiers/`` and
``configs/hardware/dacs/`` in the repo (development) or on the Pi.
"""

from __future__ import annotations

import logging
import os
import pathlib
import re
from typing import Any

import yaml
from fastapi import APIRouter
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/hardware", tags=["hardware"])

# Resolve config directories: check Pi path first, then repo fallback.
_PI_HARDWARE_DIR = pathlib.Path(
    os.environ.get("PI4AUDIO_HARDWARE_DIR", "/etc/pi4audio/hardware")
)
_REPO_HARDWARE_DIR = (
    pathlib.Path(__file__).resolve().parents[3] / "configs" / "hardware"
)

# Allowed filename characters (prevent path traversal).
_SAFE_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")


def _hardware_dir() -> pathlib.Path | None:
    """Return the hardware config directory, checking Pi path then repo."""
    if _PI_HARDWARE_DIR.is_dir():
        return _PI_HARDWARE_DIR
    if _REPO_HARDWARE_DIR.is_dir():
        return _REPO_HARDWARE_DIR
    return None


def _list_yamls(subdir: str) -> list[dict]:
    """List YAML files in a hardware subdirectory."""
    base = _hardware_dir()
    if base is None:
        return []
    d = base / subdir
    if not d.is_dir():
        return []
    result = []
    for f in sorted(d.iterdir()):
        if f.suffix in (".yml", ".yaml") and f.is_file():
            try:
                data = yaml.safe_load(f.read_text())
            except Exception:
                data = {}
            display_name = data.get("name", f.stem) if isinstance(data, dict) else f.stem
            result.append({"name": f.stem, "display_name": display_name})
    return result


def _read_yaml(subdir: str, name: str) -> dict | None:
    """Read a single YAML file by stem name from a hardware subdirectory."""
    if not _SAFE_NAME.match(name):
        return None
    base = _hardware_dir()
    if base is None:
        return None
    d = base / subdir
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            try:
                data = yaml.safe_load(path.read_text())
                return data if isinstance(data, dict) else None
            except Exception as exc:
                log.warning("Failed to parse %s: %s", path, exc)
                return None
    return None


def _write_yaml(subdir: str, name: str, data: dict) -> pathlib.Path | None:
    """Write a dict to a YAML file. Returns the path on success."""
    if not _SAFE_NAME.match(name):
        return None
    base = _hardware_dir()
    if base is None:
        return None
    d = base / subdir
    # Check for existing file with either extension.
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            break
    else:
        path = d / (name + ".yml")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return path
    except Exception as exc:
        log.warning("Failed to write %s: %s", path, exc)
        return None


def _delete_yaml(subdir: str, name: str) -> bool:
    """Delete a YAML file by stem name. Returns True if deleted."""
    if not _SAFE_NAME.match(name):
        return False
    base = _hardware_dir()
    if base is None:
        return False
    d = base / subdir
    for ext in (".yml", ".yaml"):
        path = d / (name + ext)
        if path.is_file():
            path.unlink()
            return True
    return False


def _name_error(name: str) -> JSONResponse | None:
    """Return a 400 response if the name is invalid, or None if valid."""
    if not _SAFE_NAME.match(name):
        return JSONResponse(
            status_code=400,
            content={"error": "invalid_name",
                     "detail": "Name must match [a-zA-Z0-9][a-zA-Z0-9._-]*"},
        )
    return None


def _slugify(name: str) -> str:
    """Convert a display name to a filename-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug or "unnamed"


# -- Validation ---------------------------------------------------------------

_AMP_REQUIRED = {"name", "type", "channels", "power_per_channel_watts",
                 "impedance_rated_ohms", "voltage_gain"}

_VALID_AMP_TYPES = {"class_d", "class_ab", "class_h", "tube", "other"}

_DAC_REQUIRED = {"name", "type", "channels", "output_0dbfs_vrms"}

_VALID_DAC_TYPES = {"usb_audio", "adat_converter", "spdif", "dante",
                    "aes_ebu", "analog", "other"}


def _validate_amplifier(data: Any) -> str | None:
    """Validate an amplifier dict. Returns error string, or None if valid."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    missing = _AMP_REQUIRED - data.keys()
    if missing:
        return f"Missing required fields: {', '.join(sorted(missing))}"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "'name' must be a non-empty string"
    if data["type"] not in _VALID_AMP_TYPES:
        return f"'type' must be one of: {', '.join(sorted(_VALID_AMP_TYPES))}"
    if not isinstance(data["channels"], int) or data["channels"] < 1:
        return "'channels' must be a positive integer"
    if not isinstance(data["power_per_channel_watts"], (int, float)) or data["power_per_channel_watts"] <= 0:
        return "'power_per_channel_watts' must be a positive number"
    if not isinstance(data["impedance_rated_ohms"], (int, float)) or data["impedance_rated_ohms"] <= 0:
        return "'impedance_rated_ohms' must be a positive number"
    if not isinstance(data["voltage_gain"], (int, float)) or data["voltage_gain"] <= 0:
        return "'voltage_gain' must be a positive number"
    return None


def _validate_dac(data: Any) -> str | None:
    """Validate a DAC dict. Returns error string, or None if valid."""
    if not isinstance(data, dict):
        return "Body must be a JSON object"
    missing = _DAC_REQUIRED - data.keys()
    if missing:
        return f"Missing required fields: {', '.join(sorted(missing))}"
    if not isinstance(data["name"], str) or not data["name"].strip():
        return "'name' must be a non-empty string"
    if data["type"] not in _VALID_DAC_TYPES:
        return f"'type' must be one of: {', '.join(sorted(_VALID_DAC_TYPES))}"
    if not isinstance(data["channels"], int) or data["channels"] < 1:
        return "'channels' must be a positive integer"
    if not isinstance(data["output_0dbfs_vrms"], (int, float)) or data["output_0dbfs_vrms"] <= 0:
        return "'output_0dbfs_vrms' must be a positive number"
    return None


# -- Amplifier endpoints ------------------------------------------------------

@router.get("/amplifiers")
async def list_amplifiers():
    """List all amplifier profiles."""
    return {"amplifiers": _list_yamls("amplifiers")}


@router.get("/amplifiers/{name}")
async def get_amplifier(name: str):
    """Read a single amplifier profile by filename stem."""
    data = _read_yaml("amplifiers", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Amplifier '{name}' not found"},
        )
    return data


@router.post("/amplifiers")
async def create_amplifier(body: dict[str, Any]):
    """Create a new amplifier profile."""
    err = _validate_amplifier(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    slug = body.pop("slug", None) or _slugify(body["name"])
    name_err = _name_error(slug)
    if name_err:
        return name_err
    if _read_yaml("amplifiers", slug) is not None:
        return JSONResponse(
            status_code=409,
            content={"error": "already_exists",
                     "detail": f"Amplifier '{slug}' already exists"},
        )
    path = _write_yaml("amplifiers", slug, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return JSONResponse(
        status_code=201,
        content={"ok": True, "name": slug, "path": str(path)},
    )


@router.put("/amplifiers/{name}")
async def update_amplifier(name: str, body: dict[str, Any]):
    """Update an existing amplifier profile."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if _read_yaml("amplifiers", name) is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Amplifier '{name}' not found"},
        )
    err = _validate_amplifier(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    path = _write_yaml("amplifiers", name, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return {"ok": True, "name": name, "path": str(path)}


@router.delete("/amplifiers/{name}")
async def delete_amplifier(name: str):
    """Delete an amplifier profile."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if not _delete_yaml("amplifiers", name):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"Amplifier '{name}' not found"},
        )
    return {"ok": True, "deleted": name}


# -- DAC endpoints ------------------------------------------------------------

@router.get("/dacs")
async def list_dacs():
    """List all DAC profiles."""
    return {"dacs": _list_yamls("dacs")}


@router.get("/dacs/{name}")
async def get_dac(name: str):
    """Read a single DAC profile by filename stem."""
    data = _read_yaml("dacs", name)
    if data is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"DAC '{name}' not found"},
        )
    return data


@router.post("/dacs")
async def create_dac(body: dict[str, Any]):
    """Create a new DAC profile."""
    err = _validate_dac(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    slug = body.pop("slug", None) or _slugify(body["name"])
    name_err = _name_error(slug)
    if name_err:
        return name_err
    if _read_yaml("dacs", slug) is not None:
        return JSONResponse(
            status_code=409,
            content={"error": "already_exists",
                     "detail": f"DAC '{slug}' already exists"},
        )
    path = _write_yaml("dacs", slug, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return JSONResponse(
        status_code=201,
        content={"ok": True, "name": slug, "path": str(path)},
    )


@router.put("/dacs/{name}")
async def update_dac(name: str, body: dict[str, Any]):
    """Update an existing DAC profile."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if _read_yaml("dacs", name) is None:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"DAC '{name}' not found"},
        )
    err = _validate_dac(body)
    if err:
        return JSONResponse(status_code=422, content={"error": "validation", "detail": err})
    path = _write_yaml("dacs", name, body)
    if path is None:
        return JSONResponse(status_code=500, content={"error": "write_failed"})
    return {"ok": True, "name": name, "path": str(path)}


@router.delete("/dacs/{name}")
async def delete_dac(name: str):
    """Delete a DAC profile."""
    name_err = _name_error(name)
    if name_err:
        return name_err
    if not _delete_yaml("dacs", name):
        return JSONResponse(
            status_code=404,
            content={"error": "not_found",
                     "detail": f"DAC '{name}' not found"},
        )
    return {"ok": True, "deleted": name}
