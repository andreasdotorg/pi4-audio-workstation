#!/usr/bin/env python3
"""
Speaker driver YAML validation module (US-039).

Validates driver records at configs/drivers/{id}/driver.yml against the
schema defined in TEMPLATE.yml. Checks:
  - Required fields present and non-null
  - Correct types for all fields
  - Enum values valid
  - Physical consistency of Thiele-Small parameters
  - Referenced data files exist

Exit code 0 = all valid, 1 = validation errors found.
"""

import argparse
import math
import os
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Schema constants
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 1

DRIVER_TYPES = {"woofer", "midrange", "tweeter", "full-range", "subwoofer", "coaxial"}

TS_PARAMETER_SOURCES = {"manufacturer", "measured-added-mass", "measured-impedance-jig"}

MAGNET_TYPES = {"ferrite", "neodymium", "alnico"}

CONE_MATERIALS = {"paper", "polypropylene", "aluminum", "kevlar", "carbon-fiber"}

SURROUND_MATERIALS = {"rubber", "foam", "cloth"}

CONDITIONS = {"new", "good", "fair", "needs-repair", "retired"}

MEASUREMENT_SOURCES = {"measured", "datasheet", "manufacturer-file"}

# Required fields that must be non-null
REQUIRED_METADATA_FIELDS = {"id", "manufacturer", "model"}

# Required T/S fields (per TEMPLATE: fs_hz, re_ohm, z_nom_ohm, qts)
# Note: tweeters often lack T/S params entirely, so these are only
# required when any T/S field is populated.
REQUIRED_TS_FIELDS = {"fs_hz", "re_ohm", "z_nom_ohm", "qts"}


# ---------------------------------------------------------------------------
# Validation result
# ---------------------------------------------------------------------------

class ValidationResult:
    """Collects errors and warnings from validating a single driver."""

    def __init__(self, driver_path):
        self.driver_path = str(driver_path)
        self.errors = []
        self.warnings = []

    def error(self, msg):
        self.errors.append(msg)

    def warn(self, msg):
        self.warnings.append(msg)

    @property
    def valid(self):
        return len(self.errors) == 0

    def __str__(self):
        lines = [f"{'PASS' if self.valid else 'FAIL'}: {self.driver_path}"]
        for e in self.errors:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings:
            lines.append(f"  WARN:  {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Type checking helpers
# ---------------------------------------------------------------------------

def _check_type(result, path, value, expected_type, allow_null=True):
    """Check that value is of expected_type (or null if allowed)."""
    if value is None:
        return
    # Booleans should not pass as numeric
    if isinstance(value, bool) and expected_type in ((int, float), int, float):
        result.error(f"{path}: expected numeric, got bool")
        return
    if not isinstance(value, expected_type):
        if isinstance(expected_type, tuple):
            names = "/".join(t.__name__ for t in expected_type)
        else:
            names = expected_type.__name__
        result.error(f"{path}: expected {names}, got {type(value).__name__}")


def _check_positive(result, path, value):
    """Check that a numeric value is positive if present."""
    if value is not None and isinstance(value, (int, float)) and value <= 0:
        result.error(f"{path}: must be positive, got {value}")


def _check_non_negative(result, path, value):
    """Check that a numeric value is non-negative if present."""
    if value is not None and isinstance(value, (int, float)) and value < 0:
        result.error(f"{path}: must be non-negative, got {value}")


def _check_enum(result, path, value, valid_values):
    """Check that value is in the set of valid enum values."""
    if value is not None and value not in valid_values:
        result.error(f"{path}: invalid value '{value}', must be one of {sorted(valid_values)}")


def _is_numeric(value):
    """Check if value is a number (int or float), not None."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------------------
# Section validators
# ---------------------------------------------------------------------------

def _validate_metadata(result, meta, driver_dir):
    """Validate the metadata section."""
    if not isinstance(meta, dict):
        result.error("metadata: must be a mapping")
        return

    # Required fields
    for field in REQUIRED_METADATA_FIELDS:
        val = meta.get(field)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            result.error(f"metadata.{field}: required field is missing or empty")

    # Type checks
    _check_type(result, "metadata.id", meta.get("id"), str)
    _check_type(result, "metadata.manufacturer", meta.get("manufacturer"), str)
    _check_type(result, "metadata.model", meta.get("model"), str)
    _check_enum(result, "metadata.driver_type", meta.get("driver_type"), DRIVER_TYPES)
    _check_type(result, "metadata.nominal_diameter_in", meta.get("nominal_diameter_in"), (int, float))
    _check_positive(result, "metadata.nominal_diameter_in", meta.get("nominal_diameter_in"))
    _check_type(result, "metadata.actual_diameter_mm", meta.get("actual_diameter_mm"), (int, float))
    _check_positive(result, "metadata.actual_diameter_mm", meta.get("actual_diameter_mm"))
    _check_enum(result, "metadata.magnet_type", meta.get("magnet_type"), MAGNET_TYPES)
    _check_enum(result, "metadata.cone_material", meta.get("cone_material"), CONE_MATERIALS)
    _check_enum(result, "metadata.surround_material", meta.get("surround_material"), SURROUND_MATERIALS)
    _check_type(result, "metadata.voice_coil_diameter_mm", meta.get("voice_coil_diameter_mm"), (int, float))
    _check_positive(result, "metadata.voice_coil_diameter_mm", meta.get("voice_coil_diameter_mm"))
    _check_type(result, "metadata.weight_kg", meta.get("weight_kg"), (int, float))
    _check_positive(result, "metadata.weight_kg", meta.get("weight_kg"))
    _check_type(result, "metadata.datasheet_url", meta.get("datasheet_url"), str)
    _check_type(result, "metadata.datasheet_file", meta.get("datasheet_file"), str)
    _check_enum(result, "metadata.ts_parameter_source", meta.get("ts_parameter_source"), TS_PARAMETER_SOURCES)
    _check_type(result, "metadata.ts_measurement_date", meta.get("ts_measurement_date"), str)
    _check_type(result, "metadata.ts_measurement_notes", meta.get("ts_measurement_notes"), str)
    _check_type(result, "metadata.notes", meta.get("notes"), str)
    _check_type(result, "metadata.quantity_owned", meta.get("quantity_owned"), int)
    _check_non_negative(result, "metadata.quantity_owned", meta.get("quantity_owned"))
    _check_enum(result, "metadata.condition", meta.get("condition"), CONDITIONS)

    serial_numbers = meta.get("serial_numbers")
    if serial_numbers is not None and not isinstance(serial_numbers, list):
        result.error("metadata.serial_numbers: must be a list")

    # Mounting sub-section
    mounting = meta.get("mounting")
    if mounting is not None:
        if not isinstance(mounting, dict):
            result.error("metadata.mounting: must be a mapping")
        else:
            for field in ("cutout_diameter_mm", "bolt_circle_diameter_mm",
                          "overall_depth_mm", "flange_diameter_mm"):
                _check_type(result, f"metadata.mounting.{field}", mounting.get(field), (int, float))
                _check_positive(result, f"metadata.mounting.{field}", mounting.get(field))
            _check_type(result, "metadata.mounting.bolt_count", mounting.get("bolt_count"), int)
            _check_non_negative(result, "metadata.mounting.bolt_count", mounting.get("bolt_count"))

    # Check datasheet_file exists if specified
    datasheet_file = meta.get("datasheet_file")
    if datasheet_file and driver_dir:
        data_dir = Path(driver_dir) / "data"
        datasheet_path = data_dir / datasheet_file
        if not datasheet_path.exists():
            result.warn(f"metadata.datasheet_file: referenced file not found: {datasheet_path}")


def _validate_thiele_small(result, ts):
    """Validate the thiele_small section."""
    if not isinstance(ts, dict):
        result.error("thiele_small: must be a mapping")
        return

    # Check if real T/S data is populated. z_nom_ohm alone is just an
    # impedance rating (passive radiators, some tweeters have it without
    # full T/S). We require all four core fields only when at least one
    # of the "measurement-derived" T/S fields (fs_hz, qts, qes, qms,
    # vas_liters, bl_tm, mms_g, cms_m_per_n) is present.
    ts_measurement_fields = [
        "fs_hz", "qts", "qes", "qms", "vas_liters", "bl_tm", "mms_g", "cms_m_per_n",
    ]
    has_ts_data = any(_is_numeric(ts.get(f)) for f in ts_measurement_fields)

    # If real T/S data exists, warn on missing core fields.
    # This is a warning (not error) because many scraped driver records
    # have partial T/S data (passive radiators lack re_ohm/qts, some
    # manufacturers only publish a subset of parameters).
    if has_ts_data:
        for field in REQUIRED_TS_FIELDS:
            val = ts.get(field)
            if not _is_numeric(val):
                result.warn(f"thiele_small.{field}: recommended when T/S data is present")

    # Type and range checks for all numeric fields
    numeric_positive_fields = [
        "fs_hz", "re_ohm", "z_nom_ohm", "qts", "qes", "qms",
        "vas_liters", "xmax_mm", "xmech_mm", "le_mh", "bl_tm",
        "mms_g", "mmd_g", "sd_cm2", "pe_max_watts", "pe_peak_watts",
        "eta0_percent", "vd_cm3",
    ]
    for field in numeric_positive_fields:
        val = ts.get(field)
        _check_type(result, f"thiele_small.{field}", val, (int, float))
        _check_positive(result, f"thiele_small.{field}", val)

    # cms_m_per_n can be very small but must be positive
    _check_type(result, "thiele_small.cms_m_per_n", ts.get("cms_m_per_n"), (int, float))
    _check_positive(result, "thiele_small.cms_m_per_n", ts.get("cms_m_per_n"))

    # Sensitivity can be any positive number
    for field in ("sensitivity_db_1w1m", "sensitivity_db_2v83_1m"):
        val = ts.get(field)
        _check_type(result, f"thiele_small.{field}", val, (int, float))

    _check_type(result, "thiele_small.power_handling_note", ts.get("power_handling_note"), str)

    # Useful-but-optional warnings
    if has_ts_data:
        if ts.get("xmax_mm") is None:
            result.warn("thiele_small.xmax_mm: missing (useful for excursion calculations)")
        if ts.get("le_mh") is None:
            result.warn("thiele_small.le_mh: missing (useful for impedance modeling)")
        if ts.get("sd_cm2") is None:
            result.warn("thiele_small.sd_cm2: missing (useful for Vd calculation)")


def _validate_measurements(result, meas, driver_dir):
    """Validate the measurements section."""
    if not isinstance(meas, dict):
        result.error("measurements: must be a mapping")
        return

    measurement_types = {
        "impedance_curve": ["source", "date", "conditions", "data_file"],
        "frequency_response": ["source", "date", "conditions", "reference_distance_m", "data_file"],
        "nearfield_response": ["source", "date", "data_file"],
        "distortion": ["data_file", "test_level_db_spl"],
    }

    for mtype, fields in measurement_types.items():
        section = meas.get(mtype)
        if section is None:
            continue
        if not isinstance(section, dict):
            result.error(f"measurements.{mtype}: must be a mapping")
            continue

        # Validate source enum if present
        source = section.get("source")
        if source is not None:
            _check_enum(result, f"measurements.{mtype}.source", source, MEASUREMENT_SOURCES)

        # Check data file exists
        data_file = section.get("data_file")
        if data_file and driver_dir:
            data_path = Path(driver_dir) / "data" / data_file
            if not data_path.exists():
                result.warn(f"measurements.{mtype}.data_file: referenced file not found: {data_path}")

        # reference_distance_m should be positive
        if "reference_distance_m" in fields:
            ref_dist = section.get("reference_distance_m")
            _check_type(result, f"measurements.{mtype}.reference_distance_m", ref_dist, (int, float))
            _check_positive(result, f"measurements.{mtype}.reference_distance_m", ref_dist)

        # test_level_db_spl is a number
        if "test_level_db_spl" in fields:
            _check_type(result, f"measurements.{mtype}.test_level_db_spl",
                        section.get("test_level_db_spl"), (int, float))


def _validate_application_notes(result, notes):
    """Validate the application_notes section."""
    if notes is None:
        return
    if not isinstance(notes, list):
        result.error("application_notes: must be a list")
        return


# ---------------------------------------------------------------------------
# Physical consistency checks
# ---------------------------------------------------------------------------

def _check_qts_consistency(result, ts):
    """Validate Qts = (Qes * Qms) / (Qes + Qms) within 10% tolerance.

    Manufacturer datasheets commonly round Qts, Qes, and Qms independently,
    which can produce 5-7% deviations from the computed value even when the
    underlying measurements are consistent. A 10% tolerance accommodates
    this rounding while still catching genuine data-entry errors.
    """
    qts = ts.get("qts")
    qes = ts.get("qes")
    qms = ts.get("qms")

    if not all(_is_numeric(v) for v in (qts, qes, qms)):
        return
    if qes + qms == 0:
        return

    expected_qts = (qes * qms) / (qes + qms)
    if expected_qts == 0:
        return

    deviation = abs(qts - expected_qts) / expected_qts
    if deviation > 0.10:
        result.error(
            f"thiele_small: Qts consistency check failed. "
            f"Qts={qts}, expected (Qes*Qms)/(Qes+Qms)={expected_qts:.4f}, "
            f"deviation={deviation:.1%} (>10%)"
        )


def _check_vd_consistency(result, ts):
    """Validate Vd = Sd * Xmax within 10% tolerance (if all three provided)."""
    vd = ts.get("vd_cm3")
    sd = ts.get("sd_cm2")
    xmax = ts.get("xmax_mm")

    if not all(_is_numeric(v) for v in (vd, sd, xmax)):
        return

    # Sd is in cm^2, Xmax is in mm -> convert to cm for Vd in cm^3
    expected_vd = sd * (xmax / 10.0)
    if expected_vd == 0:
        return

    deviation = abs(vd - expected_vd) / expected_vd
    if deviation > 0.10:
        result.error(
            f"thiele_small: Vd consistency check failed. "
            f"Vd={vd} cm^3, expected Sd*Xmax={expected_vd:.2f} cm^3, "
            f"deviation={deviation:.1%} (>10%)"
        )


def _check_ebp(result, ts):
    """Validate efficiency_bandwidth_product = Fs/Qes within 5% (if provided).

    Note: The AC mentions efficiency_bandwidth_product but the TEMPLATE and
    existing driver files don't have this field. We check it if present.
    """
    ebp = ts.get("efficiency_bandwidth_product")
    fs = ts.get("fs_hz")
    qes = ts.get("qes")

    if not all(_is_numeric(v) for v in (ebp, fs, qes)):
        return
    if qes == 0:
        return

    expected_ebp = fs / qes
    if expected_ebp == 0:
        return

    deviation = abs(ebp - expected_ebp) / expected_ebp
    if deviation > 0.05:
        result.error(
            f"thiele_small: EBP consistency check failed. "
            f"EBP={ebp}, expected Fs/Qes={expected_ebp:.2f}, "
            f"deviation={deviation:.1%} (>5%)"
        )


# ---------------------------------------------------------------------------
# Main validation function
# ---------------------------------------------------------------------------

def validate_driver(yaml_path, check_files=True):
    """
    Validate a single driver YAML file.

    Parameters
    ----------
    yaml_path : str or Path
        Path to the driver.yml file.
    check_files : bool
        Whether to check that referenced data files exist on disk.

    Returns
    -------
    ValidationResult
    """
    yaml_path = Path(yaml_path)
    result = ValidationResult(yaml_path)

    # Load YAML
    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        result.error(f"YAML parse error: {e}")
        return result
    except FileNotFoundError:
        result.error(f"File not found: {yaml_path}")
        return result

    if not isinstance(data, dict):
        result.error("Top-level structure must be a YAML mapping")
        return result

    # Schema version
    sv = data.get("schema_version")
    if sv != CURRENT_SCHEMA_VERSION:
        result.error(f"schema_version: expected {CURRENT_SCHEMA_VERSION}, got {sv}")

    driver_dir = yaml_path.parent if check_files else None

    # Sections
    _validate_metadata(result, data.get("metadata", {}), driver_dir)
    _validate_thiele_small(result, data.get("thiele_small", {}))
    _validate_measurements(result, data.get("measurements", {}), driver_dir)
    _validate_application_notes(result, data.get("application_notes"))

    # Physical consistency
    ts = data.get("thiele_small", {})
    if isinstance(ts, dict):
        _check_qts_consistency(result, ts)
        _check_vd_consistency(result, ts)
        _check_ebp(result, ts)

    return result


def validate_all_drivers(drivers_dir, check_files=True):
    """
    Validate all driver records in a directory tree.

    Expects structure: drivers_dir/{id}/driver.yml

    Parameters
    ----------
    drivers_dir : str or Path
        Root of the drivers directory (e.g., configs/drivers/).
    check_files : bool
        Whether to check referenced data files exist.

    Returns
    -------
    list of ValidationResult
    """
    drivers_dir = Path(drivers_dir)
    results = []

    for entry in sorted(drivers_dir.iterdir()):
        driver_yml = entry / "driver.yml"
        if entry.is_dir() and driver_yml.exists():
            results.append(validate_driver(driver_yml, check_files=check_files))

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Validate speaker driver YAML files against the schema."
    )
    parser.add_argument(
        "path",
        nargs="?",
        help="Path to a single driver.yml or a drivers directory. "
             "Defaults to configs/drivers/ relative to project root.",
    )
    parser.add_argument(
        "--no-file-check",
        action="store_true",
        help="Skip checking that referenced data files exist on disk.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Only print failures (suppress PASS results).",
    )

    args = parser.parse_args()

    check_files = not args.no_file_check

    if args.path:
        target = Path(args.path)
    else:
        project_root = Path(__file__).resolve().parent.parent.parent
        target = project_root / "configs" / "drivers"

    if target.is_file():
        results = [validate_driver(target, check_files=check_files)]
    elif target.is_dir():
        # Check if it looks like a single driver dir or the parent
        driver_yml = target / "driver.yml"
        if driver_yml.exists():
            results = [validate_driver(driver_yml, check_files=check_files)]
        else:
            results = validate_all_drivers(target, check_files=check_files)
    else:
        print(f"Error: path not found: {target}", file=sys.stderr)
        sys.exit(1)

    total = len(results)
    passed = sum(1 for r in results if r.valid)
    failed = total - passed

    for r in results:
        if not args.quiet or not r.valid:
            print(str(r))

    print(f"\n{passed}/{total} drivers passed, {failed} failed")

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
