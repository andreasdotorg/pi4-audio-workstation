# Speaker Design Catalog

Catalog of speaker designs from the owner's event inventory. Each entry
documents drivers, crossover topology, enclosure type, power handling,
channel requirements, and platform implications for the mugge audio
workstation.

**Status:** Initial catalog from research (2026-03-27). Many entries have
verification gaps — marked with the gap level and what needs owner or web
confirmation. See [Research Gaps](#research-gaps) for a summary.

**Relationship to speaker configs:** The platform uses YAML identity files
(`configs/speakers/identities/`) and profile files (`configs/speakers/profiles/`)
to drive FIR filter generation and gain staging. Each catalog entry notes
whether a corresponding identity/profile exists or needs to be created.

---

## 1. HOQS Designs

HOQS (hoqs.de) is a German pro-audio manufacturer specializing in high-output
PA designs for electronic music (techno, psytrance). Their product line targets
mobile sound systems and festival installations.

**Verification note:** hoqs.de was unreachable during research. All HOQS specs
are from training knowledge and require manufacturer confirmation.

---

### 1.1 HOQS ELF 18"

| Field | Value |
|-------|-------|
| **Drivers** | 1x 18" woofer (long-excursion, likely B&C or 18 Sound) |
| **Crossover topology** | Subwoofer only — requires external active crossover |
| **Enclosure** | Bass reflex (front-loaded, ported) |
| **Crossover frequency** | Typically below 100-120 Hz (system-dependent) |
| **Power handling** | ~1000-1500W RMS (driver-dependent) |
| **Impedance** | 8 ohm (typical single-driver sub) |
| **Frequency range** | Extended low frequency — optimized for deep sub-bass below 30 Hz |

**Platform implications:**
- Single sub channel per cabinet. Standard `subwoofer` role in profile YAML.
- 16,384-tap FIR provides 6.8 cycles at 20 Hz — sufficient for deep sub correction.
- `mandatory_hpf_hz` depends on driver/enclosure tuning (needs measurement).
- Power limit needs driver datasheet confirmation for `max_power_watts`.

**Config status:** No identity file exists. Needs: driver model, port tuning, impedance, HPF frequency.

**Gaps:** MEDIUM — exact driver model, tuning frequency, cabinet dimensions.

---

### 1.2 HOQS Type-O CRAM 2x18

| Field | Value |
|-------|-------|
| **Drivers** | 2x 18" woofers |
| **Crossover topology** | Subwoofer only — requires external active crossover |
| **Enclosure** | CRAM — likely a compact reflex-loaded design maximizing output per volume |
| **Crossover frequency** | Below 100 Hz |
| **Power handling** | ~2000-3000W RMS (2 drivers) |
| **Impedance** | 4 ohm (2x 8 ohm parallel) or 8 ohm (2x 8 ohm series) — configuration-dependent |

**Platform implications:**
- Single sub channel per cabinet (dual drivers share one amp channel).
- Impedance wiring affects amp channel assignment — 4 ohm parallel draws more current.
- `mandatory_hpf_hz` and `max_power_watts` need measurement/datasheet data.

**Config status:** No identity file exists.

**Gaps:** HIGH — CRAM enclosure topology unknown, driver models unknown.

---

### 1.3 HOQS Type-O CRAM 2x12

| Field | Value |
|-------|-------|
| **Drivers** | 2x 12" woofers / mid-bass drivers |
| **Crossover topology** | Mid-bass / kick bin — used as mid-sub in a multi-way PA stack |
| **Enclosure** | CRAM variant (see 1.2) |
| **Crossover frequency** | ~60-80 Hz (HP) to ~250-500 Hz (LP) when used as mid-bass |
| **Power handling** | ~1000-1500W RMS |
| **Impedance** | 4 or 8 ohm |

**Platform implications:**
- In a 3-way stack (subs + kicks + tops), this adds a mid-bass band requiring
  its own FIR crossover filter (bandpass: HP + LP).
- Profile topology would be `3way` or `4way` instead of the current `2way`.
- Requires additional output channels beyond the current 4 (L, R, Sub1, Sub2).
  The USBStreamer's 8 output channels may constrain multi-way configurations.
- Channel assignment needs rethinking for 3+ way stacks.

**Config status:** No identity file exists. Blocked on channel assignment decision for multi-way.

**Gaps:** HIGH — exact role in HOQS system topology, driver models.

---

### 1.4 HOQS Type-O CRAM 2x21 PLAYA Edition

| Field | Value |
|-------|-------|
| **Drivers** | 2x 21" woofers (likely B&C 21SW152 or similar) |
| **Crossover topology** | Subwoofer (deep sub-bass) |
| **Enclosure** | CRAM variant — likely front-loaded reflex with optimized port geometry |
| **Crossover frequency** | Below 80-100 Hz |
| **Power handling** | ~3000-5000W RMS |
| **Impedance** | 4 or 8 ohm |
| **Special** | "PLAYA" edition — possibly ruggedized or optimized for open-air deployment |

**Platform implications:**
- Massive displacement for infrasonic reproduction (below 20 Hz).
- 16,384 taps at 48 kHz = 2.9 Hz resolution — adequate for infrasonic correction.
- Power handling far exceeds the current 4x450W amp. Different amplification needed.
- `mandatory_hpf_hz` critical — 21" drivers with high excursion capability may
  need subsonic protection depending on enclosure tuning.

**Config status:** No identity file exists.

**Gaps:** HIGH — driver models, dimensions, PLAYA-specific features.

---

### 1.5 HOQS Widestyle 212 v2

| Field | Value |
|-------|-------|
| **Drivers** | 2x 12" woofers + HF section (likely 1" or 1.4" compression driver on horn) |
| **Crossover topology** | 2-way (passive or bi-amped) |
| **Enclosure** | Wide-dispersion top cabinet |
| **Crossover frequency** | ~1.2-2 kHz (12" to compression driver) |
| **Power handling** | ~800-1500W RMS (LF) + 150-300W RMS (HF) |
| **Impedance** | 8 ohm per section (typical) |
| **Special** | "v2" = second-generation design. Wide horizontal dispersion for festival front-of-stage coverage. |

**Platform implications:**
- If bi-amped: requires 2 output channels per cabinet (LF + HF), doubling channel count.
  L+R bi-amped = 4 channels for tops alone, leaving 4 for subs + monitoring.
- If passive crossover: single channel per cabinet, same as current wideband mains.
- Passive mode strongly preferred for mugge's 8-channel USBStreamer constraint.
- HF compression driver likely needs different `mandatory_hpf_hz` and `compensation_eq`.

**Config status:** No identity file exists. Needs passive vs bi-amp decision.

**Gaps:** HIGH — HF driver model, horn geometry, dispersion angles, v2 changes.

---

### 1.6 HOQS C3D Single/Dual 12"

| Field | Value |
|-------|-------|
| **Drivers** | Single: 1x 12" + HF. Dual: 2x 12" + HF |
| **Crossover topology** | 2-way or 3-way (possibly coaxial or point-source) |
| **Enclosure** | Unknown — "C3D" may indicate Compact 3D / controlled-directivity / point-source |
| **Crossover frequency** | ~1-2 kHz (mid to HF) |
| **Power handling** | Single: ~400-800W; Dual: ~800-1500W |
| **Impedance** | 8 ohm (typical) |

**Platform implications:**
- Similar to Widestyle 212 — passive vs bi-amp decision drives channel requirements.
- Modular single/dual configuration is useful: single for smaller venues, dual for larger.
- Both variants would share the same identity file (same drivers), different profiles.

**Config status:** No identity file exists.

**Gaps:** HIGH — C3D meaning, exact driver complement, horn/waveguide details.

---

## 2. Commercial Designs

---

### 2.1 18 Sound S218

| Field | Value |
|-------|-------|
| **Drivers** | 2x 18" woofers (18 Sound 18NLW9601 or similar high-excursion neodymium) |
| **Crossover topology** | Subwoofer — no internal crossover, requires external processing |
| **Enclosure** | Bass reflex (front-loaded, dual-ported) |
| **Crossover frequency** | Recommended LP 80-120 Hz |
| **Power handling** | 2400W AES / 4800W peak |
| **Impedance** | 4 ohm (2x 8 ohm parallel) |
| **Frequency response** | ~30-250 Hz (-6 dB) |
| **Sensitivity** | ~102-104 dB SPL @ 1W/1m |

**Platform implications:**
- Standard dual-18 sub — single channel per cabinet.
- 4 ohm impedance: check amp channel compatibility (current amp is 4x450W).
  Power handling far exceeds available amplification.
- 18 Sound NLW series drivers are well-documented — T/S parameters available
  for accurate `mandatory_hpf_hz` calculation.
- Published frequency response available at 18sound.com for verification.

**Config status:** No identity file exists. Data available from manufacturer.

**Gaps:** LOW — published specs available on 18sound.com.

---

### 2.2 LAVOCE Bassline 121BR

| Field | Value |
|-------|-------|
| **Drivers** | 1x 12" woofer + 1x 1" compression driver |
| **Crossover topology** | 2-way |
| **Enclosure** | Bass reflex ("BR" = Bass Reflex) |
| **Crossover frequency** | ~1.5-2.5 kHz |
| **Power handling** | ~400-800W RMS |
| **Impedance** | 8 ohm |
| **Special** | LAVOCE founded by former 18 Sound/B&C engineers. Good price/performance ratio. |

**Platform implications:**
- Compact 12"+1" top — could replace the self-built wideband mains.
- If passive crossover: single channel, drop-in replacement for `wideband-selfbuilt-v1` identity.
- If bi-amped: 2 channels per cabinet (see channel constraints in 1.5).
- `sensitivity_db_spl` available from manufacturer — needed for gain staging.

**Config status:** No identity file exists. Data available from manufacturer.

**Gaps:** MEDIUM — exact driver models, published frequency response, sensitivity, dimensions.

---

## 3. DIY / Community Designs

---

### 3.1 DCX464 / ME464 / FB464

A family of related DIY designs sharing the "464" naming convention.

| Field | Value |
|-------|-------|
| **DCX464** | Likely a 4-way crossover design or 4-driver configuration |
| **ME464** | Possibly a MEH (Multiple Entry Horn) variant |
| **FB464** | Possibly a front-loaded bass variant |

**Platform implications:**
- If these are multi-way designs, they may require more output channels than
  the USBStreamer provides (8 total, with 4 allocated to monitoring/IEM).
- "464" suffix may encode driver configuration — owner clarification needed.

**Config status:** Cannot create identity files without design documentation.

**Gaps:** CRITICAL — cannot identify designs without web access or owner input.
These names do not match well-known public designs. Possibly from speakerplans.com,
diyAudio, or a regional sound-system community.

---

### 3.2 Scott Hinson's DIYRM MEH

| Field | Value |
|-------|-------|
| **Drivers** | Multiple drivers in a shared horn — typically 1x 15" woofer + 2x mid drivers + 1x compression driver |
| **Crossover topology** | MEH (Multiple Entry Horn) — 3-way or 4-way, all drivers sharing a common horn |
| **Enclosure** | Horn-loaded (shared horn with multiple entry points at different depths) |
| **Crossover frequency** | ~200-400 Hz (bass to mid), ~1.5-3 kHz (mid to HF) |
| **Power handling** | Varies by driver selection |
| **Impedance** | Varies by wiring configuration |

**MEH principle:** Multiple drivers of different frequency ranges share a single
horn. The HF driver sits at the throat, mid driver partway down, woofer at/near
the mouth. This creates a true point-source with coherent phase alignment. Horn
path length for each driver determines the acoustic offset.

**Platform implications:**
- MEH designs are typically actively crossed over — requires 3-4 output channels
  per cabinet (one per driver/band).
- A stereo pair of 3-way MEH tops = 6 channels for tops alone, exceeding the
  USBStreamer's available output channels for speakers (4 channels after monitoring).
- **This is the strongest argument for a multi-way channel expansion** (second
  USBStreamer/ADA8200, or digital output expansion).
- FIR crossover complexity increases: 3-4 filters per cabinet instead of 1.
- Phase-coherent MEH crossover design aligns well with mugge's minimum-phase FIR approach.

**Config status:** Cannot create complete identity files without exact driver complement.

**Gaps:** MEDIUM — exact driver complement, horn dimensions, crossover frequencies.
Scott Hinson is active on diyAudio — thread should be findable.

---

### 3.3 JW_Sound's JMOD 2.0

| Field | Value |
|-------|-------|
| **Drivers** | Unknown — likely 2-way or 3-way with pro-audio drivers |
| **Crossover topology** | Unknown (active crossover recommended for DIY PA) |
| **Enclosure** | Unknown |
| **Power handling** | Unknown |
| **Impedance** | Unknown |
| **Special** | JW_Sound designer, version 2.0 indicates evolved design |

**Platform implications:**
- Cannot assess without design documentation.

**Config status:** Cannot create identity files.

**Gaps:** CRITICAL — no data in training corpus. Requires diyAudio/speakerplans.com
thread access or owner knowledge.

---

### 3.4 JW_Sound's Solana

| Field | Value |
|-------|-------|
| **Drivers** | Unknown — likely mid-high or full-range top |
| **Crossover topology** | Unknown |
| **Enclosure** | Unknown |
| **Special** | "Solana" may suggest outdoor/festival orientation |

**Platform implications:**
- Cannot assess without design documentation.

**Config status:** Cannot create identity files.

**Gaps:** CRITICAL — no data in training corpus. Same gap as JMOD 2.0.

---

### 3.5 XBush Bookshelf MEH

| Field | Value |
|-------|-------|
| **Drivers** | Multiple small drivers in compact MEH — likely 1x 6.5-8" woofer + 1x mid + 1x tweeter in shared horn |
| **Crossover topology** | MEH — 2-way or 3-way |
| **Enclosure** | Horn-loaded (compact bookshelf form factor) |
| **Power handling** | Lower than PA variants — bookshelf suggests home/nearfield use |
| **Impedance** | Unknown |

**Platform implications:**
- Bookshelf-sized MEH is unusual. If used as nearfield monitors, they would
  bypass the PA chain entirely (direct headphone amp output or dedicated monitor path).
- If used as small-venue tops: same multi-way channel implications as the DIYRM MEH (3.2)
  but at lower power levels.
- Lower power handling means the current 4x450W amp is likely oversized —
  power limiting in `max_power_watts` is critical.

**Config status:** Cannot create identity files without driver details.

**Gaps:** HIGH — exact driver models, horn geometry, target application.

---

## 4. Generic Categories

These entries from the event list are categories rather than specific named
designs. The owner knows which specific implementations she uses.

---

### 4.1 High-Performance Horns

| Field | Value |
|-------|-------|
| **Description** | Horn-loaded loudspeakers optimized for high sensitivity and output |
| **Typical sensitivity** | 105-115 dB/W/m |
| **Typical characteristics** | Controlled directivity, high SPL, efficient amplifier utilization |

In the psytrance/festival context, likely refers to large-format horn tops
(Danley-style synergy horns, Unity horns, or custom horn-loaded mid-highs).
Horn loading trades bandwidth for sensitivity — requires subs and possibly
mid-bass bins for full-range coverage.

**Platform implications:**
- High sensitivity means less amplifier power needed per dB SPL.
- Horn tops are almost always actively crossed over — channel count implications
  depend on whether 2-way or 3-way.
- Controlled directivity may reduce room correction complexity (less off-axis
  energy exciting room modes).

**Config status:** Need specific horn model identification from owner.

**Gaps:** HIGH — which specific horn designs does the owner use?

---

### 4.2 15" Onken Subs

| Field | Value |
|-------|-------|
| **Drivers** | 1x or 2x 15" woofers |
| **Crossover topology** | Subwoofer / bass cabinet |
| **Enclosure** | Onken — bass reflex variant with wide, shallow slot port across full baffle width |
| **Crossover frequency** | Below 150-200 Hz |
| **Power handling** | 400-800W per 15" driver |
| **Impedance** | 8 ohm (single), 4 ohm (dual parallel) |

The Onken enclosure uses a wide slot port providing even air flow and reduced
port compression at high levels. Large port area reduces turbulence noise.
Originally a Japanese audiophile design (1950s-60s), adapted for PA use.

**Platform implications:**
- Standard sub role — single channel per cabinet.
- 15" drivers have faster transient response than 18" but less deep extension.
- Slot port tuning frequency determines `mandatory_hpf_hz` — needs measurement
  or calculation from T/S parameters and port dimensions.
- The `sub-custom-15` identity file may partially apply if the owner's 15" subs
  are Onken-type.

**Config status:** `configs/speakers/identities/sub-custom-15.yml` exists —
verify whether it describes an Onken enclosure.

**Gaps:** LOW — well-documented enclosure type. Need specific driver model and
port tuning from owner.

---

### 4.3 15" Horn Subs

| Field | Value |
|-------|-------|
| **Drivers** | 1x or 2x 15" woofers |
| **Crossover topology** | Subwoofer |
| **Enclosure** | Front-loaded horn or folded horn (tapped horn, scoop, W-bin) |
| **Crossover frequency** | Below 100-150 Hz |
| **Power handling** | 400-1000W per driver |
| **Impedance** | Varies |

Horn-loaded subs provide +6-12 dB acoustic gain within their passband but limit
bandwidth. Variants: scoop (front-loaded folded horn), tapped horn (uses front
and rear radiation), W-bin (double-folded). 15" horn subs excel at mid-bass
punch (60-120 Hz) rather than deep sub-bass.

**Platform implications:**
- Narrower usable bandwidth than reflex subs — FIR crossover LP frequency may
  need to be lower to stay within the horn's passband.
- Horn gain means the driver sees less excursion for the same SPL —
  `mandatory_hpf_hz` may be less critical than for direct-radiating subs,
  but still needed below horn cutoff where the horn unloads.
- Horn sub + reflex sub mixed stacks require independent time alignment
  and correction per sub type — the platform's independent sub channels
  (Sub1, Sub2) handle this well.

**Config status:** No identity file exists. Need specific horn sub model from owner.

**Gaps:** LOW — well-documented category. Need specific design from owner.

---

## Research Gaps

| Design | Gap | What's Missing |
|--------|-----|----------------|
| HOQS ELF 18" | MEDIUM | Exact driver, tuning frequency, dimensions |
| HOQS Type-O CRAM 2x18 | HIGH | CRAM enclosure topology, driver models |
| HOQS Type-O CRAM 2x12 | HIGH | Role in system, driver models |
| HOQS Type-O CRAM 2x21 PLAYA | HIGH | Driver models, PLAYA-specific features |
| HOQS Widestyle 212 v2 | HIGH | HF section, dispersion data, v2 changes |
| HOQS C3D single/dual 12" | HIGH | C3D meaning, full spec |
| 18 Sound S218 | LOW | Published specs on 18sound.com |
| LAVOCE Bassline 121BR | MEDIUM | Full specs on lavoce.it |
| DCX464 / ME464 / FB464 | CRITICAL | Cannot identify — needs owner or web access |
| Scott Hinson's DIYRM MEH | MEDIUM | Exact driver selection, dimensions |
| JW_Sound's JMOD 2.0 | CRITICAL | No data — needs forum thread or owner |
| JW_Sound's Solana | CRITICAL | No data — needs forum thread or owner |
| XBush Bookshelf MEH | HIGH | Limited data — needs forum thread |
| High-performance Horns | HIGH | Need specific models from owner |
| 15" Onken Subs | LOW | Need specific driver model and port tuning |
| 15" Horn Subs | LOW | Need specific design from owner |

**Priority for gap resolution:**
1. **CRITICAL gaps** (DCX464 family, JMOD 2.0, Solana) — cannot proceed without
   owner input or web access. These designs have no publicly documented specs
   in available training data.
2. **HIGH gaps** (all HOQS designs, XBush MEH, generic horns) — hoqs.de
   verification + owner consultation on specific builds.
3. **MEDIUM gaps** (ELF 18", LAVOCE, Scott Hinson MEH) — manufacturer
   datasheets and diyAudio threads should resolve these.
4. **LOW gaps** (18 Sound S218, Onken, Horn subs) — well-documented designs,
   mostly need confirmation of which specific units the owner has.

## Channel Expansion Implications

The current platform has 8 output channels via the USBStreamer/ADA8200:
- Channels 1-4: speakers (L main, R main, Sub1, Sub2)
- Channels 5-6: engineer headphones
- Channels 7-8: singer IEM

Several designs in this catalog (MEH tops, bi-amped cabinets, 3-way stacks with
kick bins) would require more than 4 speaker channels. Options:
- **Second USBStreamer + ADA8200**: doubles to 16 channels (12 for speakers + 4 monitoring)
- **AES/ADAT digital expansion**: if the ADA8200 chain supports daisy-chaining
- **Prioritize passive-crossover designs**: keeps channel count at 4 for speakers

This is an architectural decision that should be tracked if the owner plans to
use multi-way actively crossed designs regularly.
