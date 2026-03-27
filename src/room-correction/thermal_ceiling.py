"""Thermal ceiling computation for speaker protection.

Computes the maximum safe digital level (dBFS) at the PipeWire filter-chain
output for each speaker channel, based on the driver's thermal power rating
(pe_max_watts), impedance, amplifier voltage gain, DAC output level, and
the per-channel gain node Mult value in the PW filter-chain config.

The signal chain modelled (D-040):

  PW filter-chain (gain node Mult) -> ADA8200 (Vrms) -> amp (V*gain) -> speaker

The PW filter-chain convolver config uses ``linear`` builtin nodes with a
Mult parameter for per-channel attenuation (e.g. 0.001 = -60 dB for mains,
0.000631 = -64 dB for subs).  These are linear scale factors, NOT dB values.
Default values load from the ``.conf`` file at startup; runtime ``pw-cli``
changes are session-only and revert on PW restart (C-009).

The thermal ceiling is the maximum dBFS at the PW filter-chain input such
that the power delivered to the driver does not exceed pe_max_watts.

Sensitivity (sensitivity_db_spl) is included in the computation: horn-loaded
speakers with high sensitivity reach the same SPL at lower amplifier power,
so the thermal ceiling in dBFS is effectively higher (the amp delivers less
power for the same perceived level).  The default reference sensitivity is
87 dB SPL/W/m (typical direct-radiating driver).

A hardcoded safety cap (DEFAULT_HARD_CAP_DBFS = -20.0) is always enforced.
If T/S data is incomplete (pe_max_watts is null/None), the hard cap is
returned as a safe fallback and a warning is logged.

Usage:
    from thermal_ceiling import compute_thermal_ceiling_dbfs, load_channel_ceilings
"""

import logging
import math
import os
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

log = logging.getLogger(__name__)

# Defense-in-depth: never exceed this level regardless of computed ceiling.
# At -20 dBFS without attenuation: ~4.5W into 4 ohm (survivable for 7W CHN-50P).
# Matches SWEEP_LEVEL_HARD_CAP_DBFS in measure_nearfield.py.
DEFAULT_HARD_CAP_DBFS = -20.0

# Operator warning threshold: ceilings above this are dangerously high.
# At -6 dBFS the amp is approaching full output — operator must verify
# gain staging before proceeding.
OPERATOR_WARNING_DBFS = -6.0

# Default hardware parameters (McGrey PA4504 + Behringer ADA8200)
DEFAULT_AMP_VOLTAGE_GAIN = 42.4  # V/V at full gain
DEFAULT_ADA8200_0DBFS_VRMS = 4.9  # Vrms at 0 dBFS (+16 dBu)

# Reference sensitivity for thermal ceiling adjustment.
# 87 dB SPL/W/m is a typical direct-radiating woofer/full-range.
DEFAULT_SENSITIVITY_DB_SPL = 87.0

# Config paths relative to project root
HARDWARE_CONFIG_DIR = "configs/hardware"
SPEAKER_IDENTITY_DIR = "configs/speakers/identities"
SPEAKER_PROFILE_DIR = "configs/speakers/profiles"


def _find_project_root():
    """Walk up from this file to find the project root (contains configs/)."""
    d = Path(__file__).resolve().parent
    for _ in range(10):
        if (d / "configs").is_dir():
            return d
        d = d.parent
    return None


def _load_yaml(path):
    """Load a YAML file. Raises if pyyaml is not available."""
    if yaml is None:
        raise ImportError("pyyaml is required: pip install pyyaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _mult_to_db(mult):
    """Convert a linear Mult gain factor to dB.

    Parameters
    ----------
    mult : float
        Linear gain factor (e.g. 0.001 for -60 dB).

    Returns
    -------
    float
        Gain in dB (always negative or zero for mult <= 1).
    """
    if mult <= 0:
        raise ValueError(f"Mult must be positive, got {mult}")
    return 20.0 * math.log10(mult)


def compute_thermal_ceiling_dbfs(pe_max_watts, impedance_ohm,
                                  pw_gain_mult,
                                  amp_voltage_gain=DEFAULT_AMP_VOLTAGE_GAIN,
                                  ada8200_0dbfs_vrms=DEFAULT_ADA8200_0DBFS_VRMS,
                                  sensitivity_db_spl=DEFAULT_SENSITIVITY_DB_SPL):
    """Compute the maximum safe digital level at PW filter-chain input.

    Returns the raw thermal ceiling without applying any hard cap. Use
    safe_ceiling_dbfs() to apply the defense-in-depth cap.

    Parameters
    ----------
    pe_max_watts : float or None
        Thermal power rating of the driver (watts). If None, returns None
        (caller should apply fallback).
    impedance_ohm : float
        Nominal impedance of the driver (ohms).
    pw_gain_mult : float
        PW filter-chain gain node Mult value (linear scale, e.g. 0.001
        for -60 dB).  This is the per-channel attenuation applied after
        the convolver in the PW filter-chain.
    amp_voltage_gain : float
        Amplifier voltage gain (V/V). Default: 42.4 (McGrey PA4504).
    ada8200_0dbfs_vrms : float
        DAC output voltage at 0 dBFS (Vrms). Default: 4.9 (ADA8200).
    sensitivity_db_spl : float
        Driver sensitivity in dB SPL/W/m. Default: 87.0. Higher
        sensitivity means the driver reaches the same SPL at lower power,
        so the thermal ceiling (in dBFS) is effectively higher.

    Returns
    -------
    float or None
        Maximum safe digital level in dBFS, or None if pe_max_watts is
        missing/invalid.
    """
    if pe_max_watts is None or pe_max_watts <= 0:
        return None

    if impedance_ohm <= 0:
        raise ValueError(f"impedance_ohm must be positive, got {impedance_ohm}")
    if amp_voltage_gain <= 0:
        raise ValueError(f"amp_voltage_gain must be positive, got {amp_voltage_gain}")
    if ada8200_0dbfs_vrms <= 0:
        raise ValueError(f"ada8200_0dbfs_vrms must be positive, got {ada8200_0dbfs_vrms}")
    if pw_gain_mult <= 0:
        raise ValueError(f"pw_gain_mult must be positive, got {pw_gain_mult}")

    # Maximum voltage the driver can handle (V = sqrt(P * Z))
    v_max = math.sqrt(pe_max_watts * impedance_ohm)

    # Voltage at DAC output that would produce v_max at the speaker
    v_at_dac = v_max / amp_voltage_gain

    # That voltage expressed in dBFS (relative to DAC's 0 dBFS output)
    dbfs_at_dac = 20.0 * math.log10(v_at_dac / ada8200_0dbfs_vrms)

    # The PW filter-chain applies a gain of pw_gain_mult (linear) between
    # the digital input and the DAC.  Convert to dB for the chain math.
    gain_db = _mult_to_db(pw_gain_mult)

    # The filter-chain input goes through the gain node before reaching
    # the DAC.  So the maximum input level is higher (less negative) by
    # the attenuation amount: ceiling = dac_limit - gain_db.
    # (gain_db is negative for attenuation, so subtracting it adds headroom.)
    raw_ceiling = dbfs_at_dac - gain_db

    # Sensitivity adjustment: a more sensitive driver produces the same SPL
    # at lower power.  For every dB above the reference sensitivity, the
    # thermal ceiling (in dBFS) is 1 dB higher — the amp needs less power
    # to reach a given SPL, so the thermal limit is farther away.
    sensitivity_offset = sensitivity_db_spl - DEFAULT_SENSITIVITY_DB_SPL
    raw_ceiling += sensitivity_offset

    return raw_ceiling


def safe_ceiling_dbfs(pe_max_watts, impedance_ohm,
                       pw_gain_mult,
                       amp_voltage_gain=DEFAULT_AMP_VOLTAGE_GAIN,
                       ada8200_0dbfs_vrms=DEFAULT_ADA8200_0DBFS_VRMS,
                       sensitivity_db_spl=DEFAULT_SENSITIVITY_DB_SPL,
                       hard_cap_dbfs=DEFAULT_HARD_CAP_DBFS):
    """Compute thermal ceiling with defense-in-depth hard cap.

    Wraps compute_thermal_ceiling_dbfs and enforces:
    - Falls back to hard_cap_dbfs when pe_max_watts is None/invalid.
    - Never returns a value higher (louder) than hard_cap_dbfs.
    - Logs a warning when pe_max_watts is missing (fallback triggered).

    Returns
    -------
    float
        Maximum safe digital level in dBFS. Always <= hard_cap_dbfs.
    """
    raw = compute_thermal_ceiling_dbfs(
        pe_max_watts, impedance_ohm, pw_gain_mult,
        amp_voltage_gain, ada8200_0dbfs_vrms, sensitivity_db_spl)

    if raw is None:
        log.warning("pe_max_watts is missing or invalid — using hard cap "
                    "%.1f dBFS as fallback", hard_cap_dbfs)
        return hard_cap_dbfs

    ceiling = min(raw, hard_cap_dbfs)
    if ceiling > OPERATOR_WARNING_DBFS:
        log.warning("Thermal ceiling %.1f dBFS exceeds operator warning "
                    "threshold (%.1f dBFS) — verify gain staging before "
                    "proceeding", ceiling, OPERATOR_WARNING_DBFS)
    return ceiling


def compute_amp_adjusted_ceiling(speaker_identity, amp_profile,
                                  pw_gain_mult,
                                  ada8200_0dbfs_vrms=DEFAULT_ADA8200_0DBFS_VRMS,
                                  sensitivity_db_spl=None):
    """Compute thermal ceiling adjusted for amplifier power limits.

    The effective ceiling is the minimum of:
    - Speaker-limited: amp can deliver more power than the speaker handles
    - Amp-limited: amp clips before reaching the speaker's thermal limit

    Parameters
    ----------
    speaker_identity : dict
        Keys: pe_max_watts, impedance_ohm, sensitivity_db_spl
    amp_profile : dict
        Keys: power_per_channel_watts, impedance_rated_ohms, voltage_gain
    pw_gain_mult : float
        PW filter-chain gain node Mult value.
    ada8200_0dbfs_vrms : float
        DAC output at 0 dBFS.
    sensitivity_db_spl : float or None
        Override sensitivity. Uses speaker_identity value if None.

    Returns
    -------
    dict
        Keys: ceiling_dbfs, limiting_factor ("speaker" or "amplifier"),
              speaker_ceiling_dbfs, amp_ceiling_dbfs
    """
    pe_max = speaker_identity.get("pe_max_watts")
    z_speaker = speaker_identity.get("impedance_ohm")
    sens = (sensitivity_db_spl if sensitivity_db_spl is not None
            else speaker_identity.get("sensitivity_db_spl", DEFAULT_SENSITIVITY_DB_SPL))

    amp_gain = amp_profile.get("voltage_gain", DEFAULT_AMP_VOLTAGE_GAIN)
    amp_power = amp_profile.get("power_per_channel_watts")
    amp_z = amp_profile.get("impedance_rated_ohms")

    # Speaker-limited ceiling (existing computation)
    speaker_ceiling = compute_thermal_ceiling_dbfs(
        pe_max_watts=pe_max,
        impedance_ohm=z_speaker,
        pw_gain_mult=pw_gain_mult,
        amp_voltage_gain=amp_gain,
        ada8200_0dbfs_vrms=ada8200_0dbfs_vrms,
        sensitivity_db_spl=sens,
    )

    # Amp-limited ceiling: at what dBFS does the amp clip?
    amp_ceiling = None
    if amp_power and amp_power > 0 and amp_z and amp_z > 0:
        # Max voltage the amp can deliver (at rated impedance)
        v_amp_max = math.sqrt(amp_power * amp_z)
        # If speaker impedance differs from rated, re-derive actual max power
        # into the speaker load. For simplicity, use voltage limit:
        # The amp can deliver v_amp_max regardless of load (voltage-source model).
        # Actual power into speaker: P = v_amp_max^2 / z_speaker
        # Clipping dBFS: the input level that makes the amp output reach v_amp_max
        if z_speaker and z_speaker > 0 and pw_gain_mult > 0:
            v_dac_for_clip = v_amp_max / amp_gain
            dbfs_at_dac = 20.0 * math.log10(v_dac_for_clip / ada8200_0dbfs_vrms)
            gain_db = _mult_to_db(pw_gain_mult)
            amp_ceiling = dbfs_at_dac - gain_db

    # Pick the more restrictive limit
    if speaker_ceiling is None and amp_ceiling is None:
        return {
            "ceiling_dbfs": None,
            "limiting_factor": "unknown",
            "speaker_ceiling_dbfs": None,
            "amp_ceiling_dbfs": None,
        }

    if speaker_ceiling is None:
        effective = amp_ceiling
        factor = "amplifier"
    elif amp_ceiling is None:
        effective = speaker_ceiling
        factor = "speaker"
    elif amp_ceiling < speaker_ceiling:
        effective = amp_ceiling
        factor = "amplifier"
    else:
        effective = speaker_ceiling
        factor = "speaker"

    return {
        "ceiling_dbfs": effective,
        "limiting_factor": factor,
        "speaker_ceiling_dbfs": speaker_ceiling,
        "amp_ceiling_dbfs": amp_ceiling,
    }


# D-009 safety margin
_D009_MARGIN_DB = 0.5


def compute_gain_staging(amp_profile, dac_profile, speaker_identity):
    """Compute full signal chain gain and identify the clipping point.

    Signal chain: DAC (dBFS -> Vrms) -> amp (Vrms * gain) -> speaker (V -> W -> SPL)

    Parameters
    ----------
    amp_profile : dict
        Keys: voltage_gain, power_per_channel_watts, impedance_rated_ohms
    dac_profile : dict
        Keys: output_0dbfs_vrms
    speaker_identity : dict
        Keys: pe_max_watts, impedance_ohm, sensitivity_db_spl

    Returns
    -------
    dict
        Keys: dac_0dbfs_vrms, amp_gain, amp_max_voltage,
              speaker_max_voltage, clipping_point, recommended_headroom_dbfs,
              max_spl_at_0dbfs
    """
    dac_vrms = dac_profile.get("output_0dbfs_vrms", DEFAULT_ADA8200_0DBFS_VRMS)
    amp_gain = amp_profile.get("voltage_gain", DEFAULT_AMP_VOLTAGE_GAIN)
    amp_power = amp_profile.get("power_per_channel_watts")
    amp_z = amp_profile.get("impedance_rated_ohms")

    pe_max = speaker_identity.get("pe_max_watts")
    z_speaker = speaker_identity.get("impedance_ohm")
    sens = speaker_identity.get("sensitivity_db_spl", DEFAULT_SENSITIVITY_DB_SPL)

    # Voltage at speaker at 0 dBFS
    v_at_speaker_0dbfs = dac_vrms * amp_gain

    # Amp max output voltage (at rated impedance)
    amp_max_v = math.sqrt(amp_power * amp_z) if (amp_power and amp_z and amp_power > 0 and amp_z > 0) else None

    # Speaker max voltage (from thermal rating)
    spk_max_v = math.sqrt(pe_max * z_speaker) if (pe_max and z_speaker and pe_max > 0 and z_speaker > 0) else None

    # Identify clipping point (which is the weakest link)
    if amp_max_v is not None and spk_max_v is not None:
        if amp_max_v < spk_max_v:
            clipping_point = "amplifier"
            limit_v = amp_max_v
        else:
            clipping_point = "speaker"
            limit_v = spk_max_v
    elif amp_max_v is not None:
        clipping_point = "amplifier"
        limit_v = amp_max_v
    elif spk_max_v is not None:
        clipping_point = "speaker"
        limit_v = spk_max_v
    else:
        clipping_point = "unknown"
        limit_v = None

    # Recommended headroom: how far below 0 dBFS to stay safe
    if limit_v is not None and v_at_speaker_0dbfs > 0:
        headroom_db = 20.0 * math.log10(limit_v / v_at_speaker_0dbfs) - _D009_MARGIN_DB
        headroom_db = min(headroom_db, 0.0)  # never recommend above 0 dBFS
    else:
        headroom_db = DEFAULT_HARD_CAP_DBFS

    # Max SPL at 0 dBFS (no attenuation)
    if z_speaker and z_speaker > 0 and v_at_speaker_0dbfs > 0:
        power_at_0dbfs = v_at_speaker_0dbfs ** 2 / z_speaker
        if power_at_0dbfs > 0:
            spl_at_0dbfs = sens + 10.0 * math.log10(power_at_0dbfs)
        else:
            spl_at_0dbfs = None
    else:
        spl_at_0dbfs = None

    return {
        "dac_0dbfs_vrms": dac_vrms,
        "amp_gain": amp_gain,
        "amp_max_voltage": amp_max_v,
        "speaker_max_voltage": spk_max_v,
        "clipping_point": clipping_point,
        "recommended_headroom_dbfs": round(headroom_db, 2),
        "max_spl_at_0dbfs": round(spl_at_0dbfs, 1) if spl_at_0dbfs is not None else None,
    }


def load_amp_profile(amp_name, project_root=None):
    """Load an amplifier profile from configs/hardware/amplifiers/.

    Parameters
    ----------
    amp_name : str
        Amplifier profile name without .yml extension.
    project_root : str or Path, optional

    Returns
    -------
    dict or None
        Amplifier profile dict, or None if not found.
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        return None
    path = Path(project_root) / HARDWARE_CONFIG_DIR / "amplifiers" / f"{amp_name}.yml"
    if not path.exists():
        return None
    return _load_yaml(path)


def load_dac_profile(dac_name, project_root=None):
    """Load a DAC profile from configs/hardware/dacs/.

    Parameters
    ----------
    dac_name : str
        DAC profile name without .yml extension.
    project_root : str or Path, optional

    Returns
    -------
    dict or None
        DAC profile dict, or None if not found.
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        return None
    path = Path(project_root) / HARDWARE_CONFIG_DIR / "dacs" / f"{dac_name}.yml"
    if not path.exists():
        return None
    return _load_yaml(path)


def load_hardware_config(project_root=None):
    """Load hardware config files and return amp gain and DAC output level.

    Parameters
    ----------
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.

    Returns
    -------
    dict
        Keys: amp_voltage_gain, ada8200_0dbfs_vrms
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        return {
            "amp_voltage_gain": DEFAULT_AMP_VOLTAGE_GAIN,
            "ada8200_0dbfs_vrms": DEFAULT_ADA8200_0DBFS_VRMS,
        }

    project_root = Path(project_root)
    hw_dir = project_root / HARDWARE_CONFIG_DIR

    result = {
        "amp_voltage_gain": DEFAULT_AMP_VOLTAGE_GAIN,
        "ada8200_0dbfs_vrms": DEFAULT_ADA8200_0DBFS_VRMS,
    }

    amp_path = hw_dir / "amp-mcgrey-pa4504.yml"
    if amp_path.exists():
        amp = _load_yaml(amp_path)
        if amp and "specs" in amp:
            if "voltage_gain" not in amp["specs"]:
                raise ValueError(
                    f"Hardware config {amp_path} has 'specs' section but "
                    f"missing required key 'voltage_gain'")
            result["amp_voltage_gain"] = amp["specs"]["voltage_gain"]

    dac_path = hw_dir / "dac-behringer-ada8200.yml"
    if dac_path.exists():
        dac = _load_yaml(dac_path)
        if dac and "specs" in dac:
            if "output_level_0dbfs_vrms" not in dac["specs"]:
                raise ValueError(
                    f"Hardware config {dac_path} has 'specs' section but "
                    f"missing required key 'output_level_0dbfs_vrms'")
            result["ada8200_0dbfs_vrms"] = dac["specs"]["output_level_0dbfs_vrms"]

    return result


def load_speaker_identity(identity_name, project_root=None):
    """Load a speaker identity YAML and return driver parameters.

    Parameters
    ----------
    identity_name : str
        Identity file name without .yml extension (e.g. "markaudio-chn-50p-sealed-1l16").
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.

    Returns
    -------
    dict
        Keys: pe_max_watts (float or None), impedance_ohm (float),
              sensitivity_db_spl (float)
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        raise FileNotFoundError("Cannot find project root (no configs/ directory)")

    project_root = Path(project_root)
    identity_path = project_root / SPEAKER_IDENTITY_DIR / f"{identity_name}.yml"

    if not identity_path.exists():
        raise FileNotFoundError(f"Speaker identity not found: {identity_path}")

    data = _load_yaml(identity_path)

    if "impedance_ohm" not in data:
        raise ValueError(
            f"Speaker identity {identity_path} missing required key "
            f"'impedance_ohm'")

    return {
        "pe_max_watts": data.get("max_power_watts"),
        "impedance_ohm": data["impedance_ohm"],
        "sensitivity_db_spl": data.get(
            "sensitivity_db_spl", DEFAULT_SENSITIVITY_DB_SPL),
    }


def load_channel_ceilings(profile_name, pw_gain_mults=None,
                           project_root=None,
                           hard_cap_dbfs=DEFAULT_HARD_CAP_DBFS,
                           amp_profile=None, dac_profile=None):
    """Compute thermal ceilings for all speaker channels in a profile.

    Parameters
    ----------
    profile_name : str
        Speaker profile name without .yml (e.g. "bose-home-chn50p").
    pw_gain_mults : dict or None
        Mapping of speaker name -> PW gain node Mult value (linear scale).
        E.g. {"sat_left": 0.001, "sub1": 0.000631}.
        If None or a speaker key is missing, falls back to 1.0 (0 dB,
        no attenuation — most conservative).
    project_root : str or Path, optional
        Project root directory. Auto-detected if not provided.
    hard_cap_dbfs : float
        Absolute maximum digital level. Default: -20.0.
    amp_profile : dict or None
        Amplifier profile dict (from hardware config). When provided,
        ceilings account for amp clipping via compute_amp_adjusted_ceiling.
        When None, uses legacy load_hardware_config behavior.
    dac_profile : dict or None
        DAC profile dict (from hardware config). When provided, uses its
        output_0dbfs_vrms instead of the legacy config value.

    Returns
    -------
    dict
        Mapping of speaker name -> dict with keys:
            channel (int), ceiling_dbfs (float), identity (str),
            pe_max_watts (float or None), impedance_ohm (float),
            sensitivity_db_spl (float), pw_gain_mult (float),
            pw_gain_db (float), limiting_factor (str, when amp_profile given)
    """
    if project_root is None:
        project_root = _find_project_root()
    if project_root is None:
        raise FileNotFoundError("Cannot find project root (no configs/ directory)")

    if pw_gain_mults is None:
        pw_gain_mults = {}

    project_root = Path(project_root)

    # Resolve hardware parameters
    if amp_profile is not None:
        amp_gain = amp_profile.get("voltage_gain", DEFAULT_AMP_VOLTAGE_GAIN)
    else:
        hw = load_hardware_config(project_root)
        amp_gain = hw["amp_voltage_gain"]

    if dac_profile is not None:
        dac_vrms = dac_profile.get("output_0dbfs_vrms", DEFAULT_ADA8200_0DBFS_VRMS)
    else:
        if amp_profile is None:
            # hw already loaded above
            dac_vrms = hw["ada8200_0dbfs_vrms"]
        else:
            hw_legacy = load_hardware_config(project_root)
            dac_vrms = hw_legacy["ada8200_0dbfs_vrms"]

    profile_path = project_root / SPEAKER_PROFILE_DIR / f"{profile_name}.yml"
    if not profile_path.exists():
        raise FileNotFoundError(f"Speaker profile not found: {profile_path}")

    profile = _load_yaml(profile_path)
    speakers = profile.get("speakers", {})
    results = {}

    for spk_name, spk_data in speakers.items():
        identity_name = spk_data.get("identity")
        channel = spk_data.get("channel")

        if identity_name is None or channel is None:
            continue

        identity = load_speaker_identity(identity_name, project_root)
        pe = identity["pe_max_watts"]
        z = identity["impedance_ohm"]
        sens = identity["sensitivity_db_spl"]

        # Per-channel Mult from PW filter-chain config.
        # Default 1.0 (0 dB) is conservative — no attenuation assumed.
        mult = pw_gain_mults.get(spk_name, 1.0)

        # Use amp-adjusted ceiling when amp_profile is provided
        if amp_profile is not None:
            adjusted = compute_amp_adjusted_ceiling(
                speaker_identity=identity,
                amp_profile=amp_profile,
                pw_gain_mult=mult,
                ada8200_0dbfs_vrms=dac_vrms,
            )
            raw_ceiling = adjusted["ceiling_dbfs"]
            limiting_factor = adjusted["limiting_factor"]
        else:
            raw_ceiling = compute_thermal_ceiling_dbfs(
                pe_max_watts=pe,
                impedance_ohm=z,
                pw_gain_mult=mult,
                amp_voltage_gain=amp_gain,
                ada8200_0dbfs_vrms=dac_vrms,
                sensitivity_db_spl=sens,
            )
            limiting_factor = "speaker"

        # Apply hard cap
        if raw_ceiling is None:
            log.warning("pe_max_watts is missing for %s — using hard cap "
                        "%.1f dBFS as fallback", spk_name, hard_cap_dbfs)
            ceiling = hard_cap_dbfs
        else:
            ceiling = min(raw_ceiling, hard_cap_dbfs)

        if ceiling > OPERATOR_WARNING_DBFS:
            log.warning("Channel %s ceiling %.1f dBFS exceeds operator "
                        "warning threshold (%.1f dBFS) — verify gain "
                        "staging", spk_name, ceiling, OPERATOR_WARNING_DBFS)

        entry = {
            "channel": channel,
            "ceiling_dbfs": ceiling,
            "identity": identity_name,
            "pe_max_watts": pe,
            "impedance_ohm": z,
            "sensitivity_db_spl": sens,
            "pw_gain_mult": mult,
            "pw_gain_db": round(_mult_to_db(mult), 2),
        }
        if amp_profile is not None:
            entry["limiting_factor"] = limiting_factor

        results[spk_name] = entry

    return results


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser(
        description="Compute thermal ceiling for speaker channels.")
    parser.add_argument("--profile", default="bose-home-chn50p",
                        help="Speaker profile name (default: bose-home-chn50p)")
    parser.add_argument("--mains-mult", type=float, default=0.001,
                        help="PW gain node Mult for mains (default: 0.001 = -60 dB)")
    parser.add_argument("--subs-mult", type=float, default=0.000631,
                        help="PW gain node Mult for subs (default: 0.000631 = -64 dB)")
    parser.add_argument("--project-root", default=None,
                        help="Project root directory (auto-detected if omitted)")
    args = parser.parse_args()

    # Build per-channel Mult map from CLI args (sat=mains, sub=subs).
    mult_map = {
        "sat_left": args.mains_mult,
        "sat_right": args.mains_mult,
        "sub1": args.subs_mult,
        "sub2": args.subs_mult,
    }

    ceilings = load_channel_ceilings(
        args.profile, pw_gain_mults=mult_map,
        project_root=args.project_root)

    mains_db = round(_mult_to_db(args.mains_mult), 1)
    subs_db = round(_mult_to_db(args.subs_mult), 1)
    print(f"Thermal ceilings for profile '{args.profile}'")
    print(f"PW gain: mains Mult={args.mains_mult} ({mains_db} dB), "
          f"subs Mult={args.subs_mult} ({subs_db} dB)")
    print(f"Hard cap: {DEFAULT_HARD_CAP_DBFS} dBFS")
    print()

    for name, info in sorted(ceilings.items(), key=lambda x: x[1]["channel"]):
        pe_str = f"{info['pe_max_watts']}W" if info['pe_max_watts'] else "N/A"
        print(f"  ch {info['channel']} ({name}): {info['ceiling_dbfs']:.2f} dBFS "
              f"[{info['identity']}, {pe_str} @ {info['impedance_ohm']} ohm, "
              f"sens={info['sensitivity_db_spl']} dB, "
              f"Mult={info['pw_gain_mult']} ({info['pw_gain_db']} dB)]")
