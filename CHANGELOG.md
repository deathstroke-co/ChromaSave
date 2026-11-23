## [1.1.1] - 2026-11-22

ChromaSave **v1.1.1** introduces **Creality SPARKX i7** native G-code support (**Beta**) with Early-Cut, native `M8200 R` Dynamic Pre-Cut Retraction, and multi-chunk chute purging, alongside a parser hardening fix for `M82`/`M83` extrusion mode detection.

### Platform Support & Maturity
| Platform / Feature | Status |
| :--- | :--- |
| **Klipper** (Early-Cut + Dynamic Pre-Cut Retraction + `SmartPurge.cfg`) | **Stable** (Physically verified) |
| **OrcaSlicer Native HTML Config UI & Passive `DualLogger`** | **Stable** |
| **Creality SPARKX i7** (Early-Cut + Native `M8200 R` Pre-Cut Retraction + Multi-Chunk Purge) | **Beta** (G-code verified; community physical testing) |
| **Bambu Lab** (Early-Cut + Multi-Chunk Purge) | **Beta** (Community testing) |
| **Bambu Lab** (Dynamic Pre-Cut Retraction) | **Experimental** |

### Added
* **Creality SPARKX i7 Native Support (`M8200`):**
  * Automatic printer profile detection via `M8200` commands without requiring custom Klipper macros.
  * **Early-Cut Relocation:** Relocates the toolchange cut sequence into hidden zones while filtering prime-tower spiral-lift moves (`G17`, `G2`) and preserving the `G1 X0 F18000` pre-cut park sequence, followed by safe *Return Travel* and *Chute Re-route*.
  * **Native Dynamic Pre-Cut Retraction:** Injects `M8200 R E-<mm>` + `M400` before `M8200 C` and post-load recovery (`G1 E<mm> F349`) after `M8200 L`, dynamically capped by the remaining cold-zone gap (`TARGET - early_cut_saving`) and `max_pre_cut_retract`.
  * **Safe Multi-Chunk Chute Purging:** Splits residual purges `> 45.0 mm` into equal chunks with cooling pulses (`M106 S255`, `G4 P2500`), retractions (`G1 E-2 F1800`), and `; WIPE` routines between chunks.
  * **Long-Retraction Safety Guardrail:** Detects native `M8200 R E-` in stock toolchanges and safely omits optimization (`[OMITTED: LONG_RETRACT]`) when OrcaSlicer's *Long retraction when cut* is enabled.
* **HTML Config UI (`config_ui.html`):** Added **SPARKX i7 (`63.2 mm`)** hotend length preset and bumped UI badge to `v1.1.1`.

### Changed
* **Klipper `SmartPurge.cfg` Upgrades:**
  * Added configurable post-purge solidification cooling pulse (`variable_pulse_cool_fan: 255`, `variable_pulse_cool_ms: 2000`) before `WIPING_CYCLE` in both `PURGE_IN_TRASH` and `FILAMENT_CHANGE`.
  * Made `filament_sensor` suspension safe across generic Klipper setups via `variable_filament_sensor` with automatic switch/motion sensor detection.
  * Added optional auxiliary/chamber fan (`variable_aux_fan`) pause and state restoration during purges and toolchanges.
  * Added a commented generic `FILAMENT_CUT` template with perpendicular `pre_cut_x` → `cut_x` staging (non-conflicting with CoPrint `cp_macro.cfg`).

### Fixed
* **Extrusion Mode Parser (`M82`/`M83`):** Replaced loose substring matching with strict anchored regexes (`^\s*M82\b`, `^\s*M83\b`) so commands like `M8200` or inline comments never trigger a false switch to absolute extrusion (`M82`).

### Validation
* **Creality SPARKX i7 (3-Layer Cube Audit):** Verified Stock Long-Retraction guardrail (`0/3` omitted), Early-Cut only (`3/3`, `0.35 g` saved, `OFE: 28.66%`), and Early-Cut + Native Pre-Cut Retraction (`3/3`, `0.42 g` saved, `OFE: 34.29%`, `CSE: 87.72%`).
* **Regression Suite (Klipper & Bambu Lab A1):** Confirmed zero regressions across Early-Cut, Pre-Cut Retraction, multi-chunk purging, and `M620.11 S1` long-retraction protection.

---


## [1.1.0] - 2026-11-21

ChromaSave **v1.1.0** graduates **Klipper Early-Cut + Dynamic Pre-Cut Retraction** and the new **native HTML Configuration UI** to **Stable** following physical print validation, while expanding **Bambu Lab** compatibility in **Beta / Experimental** mode.

### Platform Support & Maturity
| Platform / Feature | Status |
| :--- | :--- |
| **Klipper** (Early-Cut + Dynamic Pre-Cut Retraction + `SmartPurge.cfg`) | **Stable** (Physically verified) |
| **OrcaSlicer Native HTML Config UI & Passive `DualLogger`** | **Stable** |
| **Bambu Lab** (Early-Cut + Multi-Chunk Purge) | **Beta** (Community testing) |
| **Bambu Lab** (Dynamic Pre-Cut Retraction) | **Experimental** |

### Added
* **Native HTML Configuration UI (`config_ui.html`):** Replaced raw JSON editing in OrcaSlicer's plugin configuration panel with a self-contained dark-mode interface connected via `window.orca.getConfig()` / `window.orca.saveConfig()` (`has_config_ui`, `get_config_ui`, and `get_default_config`).
  * Includes quick hotend length presets (**ChromaHead** `64.857 mm`, **Bambu X1/P1** `44.485 mm`, **Bambu A1** `38.249 mm`), live `len - sm` effective target preview, automatic disabling of dependent fields, and **Safety Zones** quick toggles (*Safe Defaults*, *Select All*, *Deselect All*).
* **Dynamic Pre-Cut Retraction (`pre_cut_retract` / `max_pre_cut_retract`):** Dynamically recovers the remaining filament gap (`min(TARGET - early_cut_saving, max_pre_cut_retract)`) before cutting—working alongside partial Early-Cuts and in `[RETRACT_ONLY]` mode when Early-Cut is omitted. Available in both the OrcaSlicer plugin and CLI (`--pre_cut_retract`, `--max_pre_cut_retract`).
  * **Klipper (`SmartPurge.cfg`) — Stable:** `FILAMENT_CHANGE` accepts `RETRACT_BEFORE_CUT`, performing synchronized pre-cut retraction (`M400`) before `FILAMENT_CUT` and controlled post-load recovery (`F300`) prior to `WIPING_CYCLE`.
  * **Bambu Lab — Experimental:** Injects pre-cut retraction (`G1 E-X F1800` + `M400`) and single-shot post-load recovery (`G1 E+X F300` + `M400`) before *Return Travel* (Early-Cut) or once inside `Chunk 1/N` of `; FLUSH_START` (`RETRACT_ONLY`).
* **Native `long_retractions_when_cut` Safety Guardrail:** Detects OrcaSlicer's `M620.11 S1` (Bambu Lab) or profile/global long-retraction flags (Klipper). When active, safely omits both Early-Cut and Pre-Cut Retraction (`[OMITTED: LONG_RETRACT]`), preserves native slicer flush sequences, and displays a `[WARNING]` banner in the report.
* **Sandbox-Safe Passive Logging (`DualLogger`):** Mirrors console output to `~/chromasave_logs/chromasave_console.log` alongside `chromasave_history.log` using passive directory detection (`os.path.isdir`) without `os.makedirs`, avoiding OrcaSlicer's *Full access* permission prompt.
* **Itemized Savings Breakdown in `GLOBAL REPORT`:** Separately reports `Saved by Early-Cut` and `Saved by Pre-Cut Retraction` alongside `Dynamic Pre-Cut Retraction` status (`ENABLED`, `EXPERIMENTAL`, or `DISABLED`).

### Changed
* Updated `pyproject.toml` (`package-data`) to bundle `config_ui.html` and removed the deprecated `config_schema.json`.
* Refined Bambu Lab multi-chunk static purging (`> 45.0 mm`) with preserved flush setup headers (`M1002`, `M109`, `M106`, `M400`) and inter-flush wipe sequences.

### Fixed
* **`SmartPurge.cfg` (`PURGE_IN_TRASH`):** Fixed parameter matching so the macro reads `SKIP_THRESHOLD` passed by ChromaSave (retaining backward compatibility with `SKIP_PURGE`).
* **Change Count & OCE Accuracy:** Excluded initialization/pre-layer changes (`LAYER_NUM = -1`) from `Total Changes` and Overall Changes Efficiency (`OCE`).

### Physical Validation (Klipper — 248 Toolchanges)
Validated on a 4-color ABS/PC stress test (**27.87% real waste reduction** on scale: `55.17 g` actual vs. `76.49 g` slicer baseline; `100%` OCE). Full breakdown, scale evidence, and `.3mf` in [`examples/klipper_santa_claus_test/`](https://github.com/deathstroke-co/ChromaSave/tree/main/examples/klipper_santa_claus_test).

https://github.com/user-attachments/assets/6451f07b-2b36-4e11-bcdd-1d6e2a0991e6

### Upgrade & Testing Notes
* **Klipper Users:** Update `SmartPurge.cfg` on your printer and restart Klipper before enabling **Dynamic Pre-Cut Retraction**.
* **Bambu Lab Beta Testers:** Ensure OrcaSlicer's native *Long retraction when cut* is **disabled** before enabling ChromaSave optimization, preview the generated G-code, and monitor the first toolchanges closely. Please report feedback via [GitHub Issues](https://github.com/deathstroke-co/ChromaSave/issues).