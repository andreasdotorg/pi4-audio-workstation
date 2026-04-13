#!/usr/bin/env python3
"""Generate crossover-only FIR coefficient WAV files from a speaker profile.

Produces minimum-phase FIR filters containing only the crossover slope (no
room correction). These are the initial coefficients deployed before venue
measurement -- the room correction pipeline overwrites them with combined
crossover + correction filters after measurement.

Uses the topology-agnostic generate_profile_filters pipeline from
src/room-correction/.

Usage:
    python scripts/generate-crossover-coeffs.py \\
        --profile configs/speakers/profiles/2way-200hz-markaudio-ultimax.yml \\
        --output-dir /tmp/coeffs/

    # With identity directory override:
    python scripts/generate-crossover-coeffs.py \\
        --profile configs/speakers/profiles/2way-200hz-markaudio-ultimax.yml \\
        --identities-dir configs/speakers/identities/ \\
        --output-dir /tmp/coeffs/

Output filenames follow the convention: combined_<speaker_key>.wav
(e.g., combined_sat_left.wav, combined_sub1.wav).

For deployment, rename to match the convolver config expectations:
    combined_sat_left.wav  -> combined_left_hp.wav
    combined_sat_right.wav -> combined_right_hp.wav
    combined_sub1.wav      -> combined_sub1_lp.wav
"""

import argparse
import os
import sys

import yaml

# Add room-correction source to path
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "room-correction")
)

from room_correction.generate_profile_filters import generate_profile_filters


# Map speaker profile keys to the deployment filenames expected by the
# 30-filter-chain-convolver.conf.
DEPLOY_FILENAMES = {
    "sat_left": "combined_left_hp.wav",
    "sat_right": "combined_right_hp.wav",
    "sub1": "combined_sub1_lp.wav",
    "sub2": "combined_sub2_lp.wav",
}


def load_yaml(path):
    with open(path) as f:
        return yaml.safe_load(f)


def load_identities(identities_dir, profile):
    """Load all speaker identities referenced by the profile."""
    identities = {}
    speakers = profile.get("speakers", {})
    for spk_cfg in speakers.values():
        id_name = spk_cfg.get("identity", "")
        if id_name and id_name not in identities:
            id_path = os.path.join(identities_dir, f"{id_name}.yml")
            if os.path.exists(id_path):
                identities[id_name] = load_yaml(id_path)
            else:
                print(f"WARNING: identity file not found: {id_path}", file=sys.stderr)
                identities[id_name] = {}
    return identities


def main():
    parser = argparse.ArgumentParser(
        description="Generate crossover-only FIR coefficient WAV files from a speaker profile."
    )
    parser.add_argument(
        "--profile", required=True,
        help="Path to speaker profile YAML file.",
    )
    parser.add_argument(
        "--identities-dir", default=None,
        help="Directory containing speaker identity YAML files. "
             "Defaults to configs/speakers/identities/ relative to repo root.",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Output directory for WAV files.",
    )
    parser.add_argument(
        "--deploy-names", action="store_true",
        help="Use deployment filenames (combined_left_hp.wav etc.) instead of "
             "profile key names (combined_sat_left.wav etc.).",
    )
    args = parser.parse_args()

    # Resolve identities directory
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    identities_dir = args.identities_dir or os.path.join(
        repo_root, "configs", "speakers", "identities"
    )

    # Load profile and identities
    profile = load_yaml(args.profile)
    identities = load_identities(identities_dir, profile)

    n_taps = profile.get("filter_taps", 16384)

    print(f"Profile: {profile.get('name', 'unnamed')}")
    print(f"Crossover: {profile.get('crossover', {}).get('frequency_hz')} Hz, "
          f"{profile.get('crossover', {}).get('slope_db_per_oct')} dB/oct")
    print(f"Speakers: {list(profile.get('speakers', {}).keys())}")
    print(f"Filter taps: {n_taps}")
    print(f"Output: {args.output_dir}")
    print()

    # Generate crossover-only filters (no room correction)
    filters = generate_profile_filters(
        profile=profile,
        identities=identities,
        correction_filters=None,  # No room correction -- crossover only
        n_taps=n_taps,
    )

    # Export WAV files
    from room_correction.export import export_filter

    os.makedirs(args.output_dir, exist_ok=True)

    for spk_key, fir in filters.items():
        if args.deploy_names and spk_key in DEPLOY_FILENAMES:
            filename = DEPLOY_FILENAMES[spk_key]
        else:
            filename = f"combined_{spk_key}.wav"

        path = os.path.join(args.output_dir, filename)
        export_filter(fir, path, n_taps=n_taps)
        print(f"  {filename}: {len(fir)} taps, peak={max(abs(fir)):.6f}")

    print(f"\nGenerated {len(filters)} coefficient files in {args.output_dir}")


if __name__ == "__main__":
    main()
