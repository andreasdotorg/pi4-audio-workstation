"""
Unit tests for speaker driver YAML validation module (US-039).

Tests cover:
  - Valid driver records pass validation
  - Missing required fields produce errors
  - Invalid types produce errors
  - Invalid enum values produce errors
  - Physical consistency checks (Qts, Vd, EBP)
  - Warnings for missing optional fields
  - Data file existence checks
  - Schema version validation
  - Real driver records from configs/drivers/ pass validation
"""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

sys_path = os.path.join(os.path.dirname(__file__), "..")
import sys
sys.path.insert(0, sys_path)

from validate_driver import (
    ValidationResult,
    validate_driver,
    validate_all_drivers,
    DRIVER_TYPES,
    TS_PARAMETER_SOURCES,
    MAGNET_TYPES,
    CONE_MATERIALS,
    SURROUND_MATERIALS,
    CONDITIONS,
    MEASUREMENT_SOURCES,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _minimal_valid_driver():
    """Return a minimal valid driver record dict."""
    return {
        "schema_version": 1,
        "metadata": {
            "id": "test-driver-01",
            "manufacturer": "TestCo",
            "model": "TD-01",
            "driver_type": "woofer",
            "nominal_diameter_in": 6.5,
            "actual_diameter_mm": None,
            "magnet_type": None,
            "cone_material": None,
            "surround_material": None,
            "voice_coil_diameter_mm": None,
            "weight_kg": None,
            "mounting": {
                "cutout_diameter_mm": 145.0,
                "bolt_circle_diameter_mm": 166.0,
                "bolt_count": 6,
                "overall_depth_mm": 90.0,
                "flange_diameter_mm": 176.0,
            },
            "datasheet_url": None,
            "datasheet_file": None,
            "ts_parameter_source": "manufacturer",
            "ts_measurement_date": None,
            "ts_measurement_notes": "",
            "notes": "",
            "quantity_owned": None,
            "serial_numbers": [],
            "purchase_date": None,
            "condition": None,
        },
        "thiele_small": {
            "fs_hz": 33.0,
            "re_ohm": 3.7,
            "z_nom_ohm": 4,
            "qts": round((0.27 * 6.3) / (0.27 + 6.3), 4),  # Consistent with Qes/Qms
            "qes": 0.27,
            "qms": 6.3,
            "vas_liters": 28.9,
            "cms_m_per_n": 0.0011,
            "xmax_mm": 5.9,
            "xmech_mm": None,
            "le_mh": 0.32,
            "bl_tm": 7.7,
            "mms_g": 21.1,
            "mmd_g": None,
            "sd_cm2": 132.7,
            "sensitivity_db_1w1m": None,
            "sensitivity_db_2v83_1m": 90.3,
            "pe_max_watts": 250.0,
            "pe_peak_watts": None,
            "power_handling_note": "",
            "eta0_percent": None,
            "vd_cm3": None,
        },
        "measurements": {
            "impedance_curve": {
                "source": None,
                "date": None,
                "conditions": "",
                "data_file": None,
            },
            "frequency_response": {
                "source": None,
                "date": None,
                "conditions": "",
                "reference_distance_m": None,
                "data_file": None,
            },
            "nearfield_response": {
                "source": None,
                "date": None,
                "data_file": None,
            },
            "distortion": {
                "data_file": None,
                "test_level_db_spl": None,
            },
        },
        "application_notes": [],
    }


def _write_driver(tmpdir, driver_id, data):
    """Write a driver YAML to a temp directory and return the path."""
    driver_dir = Path(tmpdir) / driver_id
    driver_dir.mkdir(parents=True, exist_ok=True)
    (driver_dir / "data").mkdir(exist_ok=True)
    driver_path = driver_dir / "driver.yml"
    with open(driver_path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False)
    return driver_path


# ---------------------------------------------------------------------------
# Basic valid/invalid tests
# ---------------------------------------------------------------------------

class TestValidDriverPasses:
    def test_minimal_valid(self, tmp_path):
        data = _minimal_valid_driver()
        path = _write_driver(tmp_path, "test-driver-01", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid, got errors: {result.errors}"

    def test_valid_with_all_optional_fields(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["magnet_type"] = "neodymium"
        data["metadata"]["cone_material"] = "aluminum"
        data["metadata"]["surround_material"] = "rubber"
        data["metadata"]["weight_kg"] = 1.5
        data["metadata"]["condition"] = "new"
        data["metadata"]["quantity_owned"] = 2
        data["thiele_small"]["xmech_mm"] = 12.0
        data["thiele_small"]["mmd_g"] = 18.0
        data["thiele_small"]["sensitivity_db_1w1m"] = 87.5
        data["thiele_small"]["pe_peak_watts"] = 500.0
        path = _write_driver(tmp_path, "test-driver-01", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid, got errors: {result.errors}"

    def test_tweeter_no_ts_params(self, tmp_path):
        """Tweeters often have no T/S params -- should be valid."""
        data = _minimal_valid_driver()
        data["metadata"]["driver_type"] = "tweeter"
        data["thiele_small"] = {
            "fs_hz": None,
            "re_ohm": None,
            "z_nom_ohm": 4,
            "qts": None,
            "qes": None,
            "qms": None,
            "vas_liters": None,
            "cms_m_per_n": None,
            "xmax_mm": None,
            "xmech_mm": None,
            "le_mh": None,
            "bl_tm": None,
            "mms_g": None,
            "mmd_g": None,
            "sd_cm2": None,
            "sensitivity_db_1w1m": None,
            "sensitivity_db_2v83_1m": 96.0,
            "pe_max_watts": 20.0,
            "pe_peak_watts": 40.0,
            "power_handling_note": "",
            "eta0_percent": None,
            "vd_cm3": None,
        }
        path = _write_driver(tmp_path, "test-tweeter-01", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid, got errors: {result.errors}"


class TestRequiredFields:
    def test_missing_metadata_id(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["id"] = None
        path = _write_driver(tmp_path, "test-bad-01", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("metadata.id" in e for e in result.errors)

    def test_empty_metadata_id(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["id"] = ""
        path = _write_driver(tmp_path, "test-bad-01", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("metadata.id" in e for e in result.errors)

    def test_missing_manufacturer(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["manufacturer"] = None
        path = _write_driver(tmp_path, "test-bad-02", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("metadata.manufacturer" in e for e in result.errors)

    def test_missing_model(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["model"] = None
        path = _write_driver(tmp_path, "test-bad-03", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("metadata.model" in e for e in result.errors)

    def test_missing_recommended_ts_when_others_present(self, tmp_path):
        """If fs_hz is present, missing core T/S fields produce warnings."""
        data = _minimal_valid_driver()
        data["thiele_small"]["qts"] = None  # Remove one recommended field
        path = _write_driver(tmp_path, "test-bad-04", data)
        result = validate_driver(path, check_files=False)
        # Should still be valid (warning, not error) but warn about missing qts
        assert result.valid, f"Expected valid, got errors: {result.errors}"
        assert any("thiele_small.qts" in w for w in result.warnings)

    def test_missing_schema_version(self, tmp_path):
        data = _minimal_valid_driver()
        del data["schema_version"]
        path = _write_driver(tmp_path, "test-bad-05", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("schema_version" in e for e in result.errors)

    def test_wrong_schema_version(self, tmp_path):
        data = _minimal_valid_driver()
        data["schema_version"] = 99
        path = _write_driver(tmp_path, "test-bad-06", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("schema_version" in e for e in result.errors)


class TestTypeValidation:
    def test_fs_hz_string_rejected(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["fs_hz"] = "thirty-three"
        path = _write_driver(tmp_path, "test-type-01", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("fs_hz" in e and "expected" in e for e in result.errors)

    def test_negative_pe_max_rejected(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["pe_max_watts"] = -10
        path = _write_driver(tmp_path, "test-type-02", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("pe_max_watts" in e for e in result.errors)

    def test_zero_re_ohm_rejected(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["re_ohm"] = 0
        path = _write_driver(tmp_path, "test-type-03", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("re_ohm" in e for e in result.errors)

    def test_metadata_not_dict(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"] = "not a dict"
        path = _write_driver(tmp_path, "test-type-04", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("metadata" in e and "mapping" in e for e in result.errors)

    def test_thiele_small_not_dict(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"] = "not a dict"
        path = _write_driver(tmp_path, "test-type-05", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("thiele_small" in e and "mapping" in e for e in result.errors)

    def test_serial_numbers_not_list(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["serial_numbers"] = "SN12345"
        path = _write_driver(tmp_path, "test-type-06", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("serial_numbers" in e for e in result.errors)

    def test_application_notes_not_list(self, tmp_path):
        data = _minimal_valid_driver()
        data["application_notes"] = "some text"
        path = _write_driver(tmp_path, "test-type-07", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("application_notes" in e for e in result.errors)

    def test_quantity_owned_negative(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["quantity_owned"] = -1
        path = _write_driver(tmp_path, "test-type-08", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("quantity_owned" in e for e in result.errors)


class TestEnumValidation:
    def test_invalid_driver_type(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["driver_type"] = "speaker"
        path = _write_driver(tmp_path, "test-enum-01", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("driver_type" in e for e in result.errors)

    def test_invalid_ts_parameter_source(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["ts_parameter_source"] = "guessed"
        path = _write_driver(tmp_path, "test-enum-02", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("ts_parameter_source" in e for e in result.errors)

    def test_invalid_magnet_type(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["magnet_type"] = "ceramic"
        path = _write_driver(tmp_path, "test-enum-03", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("magnet_type" in e for e in result.errors)

    def test_invalid_condition(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["condition"] = "broken"
        path = _write_driver(tmp_path, "test-enum-04", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("condition" in e for e in result.errors)

    def test_invalid_measurement_source(self, tmp_path):
        data = _minimal_valid_driver()
        data["measurements"]["impedance_curve"]["source"] = "unknown"
        path = _write_driver(tmp_path, "test-enum-05", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("source" in e for e in result.errors)

    def test_all_valid_driver_types(self, tmp_path):
        for dtype in DRIVER_TYPES:
            data = _minimal_valid_driver()
            data["metadata"]["driver_type"] = dtype
            path = _write_driver(tmp_path, f"test-dtype-{dtype}", data)
            result = validate_driver(path, check_files=False)
            assert result.valid, f"driver_type={dtype} should be valid: {result.errors}"


class TestPhysicalConsistency:
    def test_qts_consistent(self, tmp_path):
        """Qts = (Qes * Qms) / (Qes + Qms) -- should pass when consistent."""
        data = _minimal_valid_driver()
        qes = 0.27
        qms = 6.3
        data["thiele_small"]["qes"] = qes
        data["thiele_small"]["qms"] = qms
        data["thiele_small"]["qts"] = (qes * qms) / (qes + qms)
        path = _write_driver(tmp_path, "test-qts-ok", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid: {result.errors}"

    def test_qts_inconsistent(self, tmp_path):
        """Qts far from expected value should fail."""
        data = _minimal_valid_driver()
        data["thiele_small"]["qes"] = 0.5
        data["thiele_small"]["qms"] = 5.0
        # Expected: (0.5 * 5.0) / (0.5 + 5.0) = 0.4545
        data["thiele_small"]["qts"] = 0.8  # Way off
        path = _write_driver(tmp_path, "test-qts-bad", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("Qts consistency" in e for e in result.errors)

    def test_qts_within_5_percent(self, tmp_path):
        """Qts within 5% tolerance should pass."""
        data = _minimal_valid_driver()
        qes = 0.5
        qms = 5.0
        expected_qts = (qes * qms) / (qes + qms)
        data["thiele_small"]["qes"] = qes
        data["thiele_small"]["qms"] = qms
        data["thiele_small"]["qts"] = expected_qts * 1.04  # 4% off
        path = _write_driver(tmp_path, "test-qts-margin", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid (within 5%): {result.errors}"

    def test_vd_consistent(self, tmp_path):
        """Vd = Sd * Xmax (in correct units)."""
        data = _minimal_valid_driver()
        sd = 132.7  # cm^2
        xmax = 5.9  # mm
        data["thiele_small"]["sd_cm2"] = sd
        data["thiele_small"]["xmax_mm"] = xmax
        data["thiele_small"]["vd_cm3"] = sd * (xmax / 10.0)  # Convert mm to cm
        path = _write_driver(tmp_path, "test-vd-ok", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid: {result.errors}"

    def test_vd_inconsistent(self, tmp_path):
        """Vd far from Sd * Xmax should fail."""
        data = _minimal_valid_driver()
        data["thiele_small"]["sd_cm2"] = 100.0
        data["thiele_small"]["xmax_mm"] = 10.0
        # Expected: 100 * (10/10) = 100 cm^3
        data["thiele_small"]["vd_cm3"] = 200.0  # 100% off
        path = _write_driver(tmp_path, "test-vd-bad", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("Vd consistency" in e for e in result.errors)

    def test_ebp_consistent(self, tmp_path):
        """EBP = Fs / Qes."""
        data = _minimal_valid_driver()
        data["thiele_small"]["fs_hz"] = 33.0
        data["thiele_small"]["qes"] = 0.27
        data["thiele_small"]["efficiency_bandwidth_product"] = 33.0 / 0.27
        path = _write_driver(tmp_path, "test-ebp-ok", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid: {result.errors}"

    def test_ebp_inconsistent(self, tmp_path):
        """EBP far from Fs/Qes should fail."""
        data = _minimal_valid_driver()
        data["thiele_small"]["fs_hz"] = 33.0
        data["thiele_small"]["qes"] = 0.27
        data["thiele_small"]["efficiency_bandwidth_product"] = 200.0  # Expected ~122
        path = _write_driver(tmp_path, "test-ebp-bad", data)
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("EBP consistency" in e for e in result.errors)

    def test_consistency_skipped_when_fields_missing(self, tmp_path):
        """No consistency error when required fields are null."""
        data = _minimal_valid_driver()
        data["thiele_small"]["qes"] = None
        data["thiele_small"]["qms"] = None
        path = _write_driver(tmp_path, "test-skip-consistency", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid: {result.errors}"


class TestWarnings:
    def test_warns_on_missing_xmax(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["xmax_mm"] = None
        path = _write_driver(tmp_path, "test-warn-01", data)
        result = validate_driver(path, check_files=False)
        assert result.valid  # Warnings don't fail
        assert any("xmax_mm" in w for w in result.warnings)

    def test_warns_on_missing_le(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["le_mh"] = None
        path = _write_driver(tmp_path, "test-warn-02", data)
        result = validate_driver(path, check_files=False)
        assert result.valid
        assert any("le_mh" in w for w in result.warnings)

    def test_warns_on_missing_sd(self, tmp_path):
        data = _minimal_valid_driver()
        data["thiele_small"]["sd_cm2"] = None
        path = _write_driver(tmp_path, "test-warn-03", data)
        result = validate_driver(path, check_files=False)
        assert result.valid
        assert any("sd_cm2" in w for w in result.warnings)


class TestDataFileChecks:
    def test_missing_datasheet_file_warns(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["datasheet_file"] = "nonexistent.pdf"
        path = _write_driver(tmp_path, "test-file-01", data)
        result = validate_driver(path, check_files=True)
        # Data file warning, not error
        assert any("datasheet_file" in w for w in result.warnings)

    def test_existing_datasheet_file_no_warn(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["datasheet_file"] = "spec.pdf"
        path = _write_driver(tmp_path, "test-file-02", data)
        # Create the file
        data_dir = path.parent / "data"
        data_dir.mkdir(exist_ok=True)
        (data_dir / "spec.pdf").write_text("dummy")
        result = validate_driver(path, check_files=True)
        assert result.valid
        assert not any("datasheet_file" in w for w in result.warnings)

    def test_missing_measurement_data_file_warns(self, tmp_path):
        data = _minimal_valid_driver()
        data["measurements"]["impedance_curve"]["data_file"] = "impedance.zma"
        path = _write_driver(tmp_path, "test-file-03", data)
        result = validate_driver(path, check_files=True)
        assert any("impedance_curve" in w and "data_file" in w for w in result.warnings)

    def test_no_file_check_skips_warnings(self, tmp_path):
        data = _minimal_valid_driver()
        data["metadata"]["datasheet_file"] = "nonexistent.pdf"
        path = _write_driver(tmp_path, "test-file-04", data)
        result = validate_driver(path, check_files=False)
        assert result.valid
        assert not any("datasheet_file" in w for w in result.warnings)


class TestValidateAll:
    def test_validate_multiple_drivers(self, tmp_path):
        good_data = _minimal_valid_driver()
        bad_data = _minimal_valid_driver()
        bad_data["metadata"]["id"] = None  # Invalid

        _write_driver(tmp_path, "driver-a", good_data)
        bad_data_copy = dict(bad_data)
        bad_data_copy["metadata"] = dict(bad_data["metadata"])
        _write_driver(tmp_path, "driver-b", bad_data)

        results = validate_all_drivers(tmp_path, check_files=False)
        assert len(results) == 2
        assert sum(1 for r in results if r.valid) == 1
        assert sum(1 for r in results if not r.valid) == 1

    def test_skips_non_driver_entries(self, tmp_path):
        """Files without driver.yml should be skipped."""
        good_data = _minimal_valid_driver()
        _write_driver(tmp_path, "driver-a", good_data)
        # Create a non-driver directory
        (tmp_path / "TEMPLATE.yml").write_text("not a driver")
        # Create a directory without driver.yml
        (tmp_path / "random-dir").mkdir()

        results = validate_all_drivers(tmp_path, check_files=False)
        assert len(results) == 1


class TestEdgeCases:
    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad" / "driver.yml"
        path.parent.mkdir(parents=True)
        path.write_text("{ invalid yaml: [")
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("YAML parse error" in e for e in result.errors)

    def test_nonexistent_file(self, tmp_path):
        result = validate_driver(tmp_path / "nope" / "driver.yml", check_files=False)
        assert not result.valid
        assert any("File not found" in e for e in result.errors)

    def test_top_level_not_dict(self, tmp_path):
        path = tmp_path / "bad" / "driver.yml"
        path.parent.mkdir(parents=True)
        path.write_text("just a string")
        result = validate_driver(path, check_files=False)
        assert not result.valid
        assert any("mapping" in e for e in result.errors)

    def test_integer_diameter_accepted(self, tmp_path):
        """Integer values for float fields should be accepted."""
        data = _minimal_valid_driver()
        data["metadata"]["nominal_diameter_in"] = 8  # int, not float
        data["thiele_small"]["z_nom_ohm"] = 8
        path = _write_driver(tmp_path, "test-int-01", data)
        result = validate_driver(path, check_files=False)
        assert result.valid, f"Expected valid: {result.errors}"


class TestRealDriverRecords:
    """Validate real driver records from the project's configs/drivers/ directory.

    These tests ensure that existing scraped driver data passes validation.
    They skip if the configs/drivers directory is not available.
    """

    PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
    DRIVERS_DIR = PROJECT_ROOT / "configs" / "drivers"

    @pytest.fixture
    def drivers_available(self):
        if not self.DRIVERS_DIR.exists():
            pytest.skip("configs/drivers/ not found")
        drivers = [
            d for d in self.DRIVERS_DIR.iterdir()
            if d.is_dir() and (d / "driver.yml").exists()
        ]
        if not drivers:
            pytest.skip("No driver records found")
        return drivers

    @pytest.mark.xfail(reason="F-254: Qts consistency check >5% for morel-tsct1104 and prv-audio-6mr500-ndy-4")
    def test_sample_real_drivers_pass(self, drivers_available):
        """Validate up to 20 real driver records as a smoke test."""
        sample = drivers_available[:20]
        failures = []
        for driver_dir in sample:
            result = validate_driver(
                driver_dir / "driver.yml", check_files=False
            )
            if not result.valid:
                failures.append(str(result))

        assert not failures, (
            f"{len(failures)}/{len(sample)} drivers failed:\n"
            + "\n".join(failures)
        )

    def test_template_is_not_validated(self):
        """TEMPLATE.yml is not inside a {id}/ directory, so it shouldn't be picked up."""
        template = self.DRIVERS_DIR / "TEMPLATE.yml"
        if not template.exists():
            pytest.skip("TEMPLATE.yml not found")
        # validate_all_drivers should not pick up TEMPLATE.yml
        # (it's not in a subdirectory)
        results = validate_all_drivers(self.DRIVERS_DIR, check_files=False)
        paths = [r.driver_path for r in results]
        assert not any("TEMPLATE" in p for p in paths)
