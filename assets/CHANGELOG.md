## [1.1.0-beta.2] - 2026-11-20

### Added
* **Native HTML Configuration UI (`config_ui.html`):** Replaced raw JSON editing in OrcaSlicer's plugin configuration panel with a self-contained dark-mode interface connected via `window.orca.getConfig()` / `window.orca.saveConfig()` (`has_config_ui`, `get_config_ui`, and `get_default_config`).
  * Includes quick hotend length presets (**ChromaHead** `64.857 mm`, **Bambu X1/P1** `51.0 mm`, **Bambu A1** `38.249 mm`), live `len - sm` effective Target preview, automatic disabling of dependent fields, and Safety Zones quick toggles (*Safe Defaults*, *Select All*, *Deselect All*).
* **Dynamic Pre-Cut Retraction (Klipper & Experimental Bambu Lab):** Added `pre_cut_retract` (default: `false`) and `max_pre_cut_retract` (default: `18.0 mm`) parameters across the plugin, CLI (`--pre_cut_retract`, `--max_pre_cut_retract`), and UI.
  * Dynamically recovers the remaining filament gap (`min(TARGET - early_cut_saving, max_pre_cut_retract)`) before cutting—both alongside partial Early-Cuts and in `[RETRACT_ONLY]` mode when Early-Cut is omitted.
  * **Klipper (`SmartPurge.cfg`):** `FILAMENT_CHANGE` now accepts `RETRACT_BEFORE_CUT`, performing synchronized pre-cut retraction (`M400`) before `FILAMENT_CUT` and controlled post-load recovery (`F300`) prior to `WIPING_CYCLE`.
  * **Bambu Lab (Experimental):** Injects pre-cut retraction (`G1 E-X F1800` + `M400`) and single-shot post-load recovery (`G1 E+X F300` + `M400`) before *Return Travel* (Early-Cut) or once inside `Chunk 1/N` of `; FLUSH_START` (`RETRACT_ONLY`).
* **Native `long_retractions_when_cut` Safety Guardrail:** Detects OrcaSlicer's `M620.11 S1` (Bambu Lab) or profile/global long-retraction flags (Klipper). When active, safely omits both Early-Cut and Pre-Cut Retraction (`[OMITTED: LONG_RETRACT]`), preserves native slicer flush sequences, and displays a `[WARNING]` banner in the report.
* **Sandbox-Safe Persistent Logging (`DualLogger`):** Mirrors full console output to `~/chromasave_logs/chromasave_console.log` alongside `chromasave_history.log` using passive directory detection (`os.path.isdir`) without `os.makedirs`, avoiding OrcaSlicer's "Full access" permission prompt.
* **Itemized Savings Breakdown in `GLOBAL REPORT`:** Separately reports `Saved by Early-Cut` and `Saved by Pre-Cut Retraction` alongside `Dynamic Pre-Cut Retraction` status (`ENABLED`, `EXPERIMENTAL`, or `DISABLED`).

### Changed
* Updated `pyproject.toml` packaging (`package-data`) to bundle `config_ui.html` and removed the deprecated `config_schema.json`.
* Refined Bambu Lab multi-chunk static purging (`> 45.0 mm`) with preserved flush setup headers (`M1002`, `M109`, `M106`, `M400`) and inter-flush wipe sequences.

### Fixed
* **`SmartPurge.cfg` (`PURGE_IN_TRASH`):** Fixed parameter mismatch so the macro reads `SKIP_THRESHOLD` passed by ChromaSave (retaining backward compatibility with `SKIP_PURGE`).
* **Change Count & OCE Accuracy:** Excluded initialization/pre-layer changes (`LAYER_NUM = -1`) from `Total Changes` and Overall Changes Efficiency (`OCE`).

### Verified
* Audited and validated across controlled test batteries for **Klipper (`K1–K3`)** and **Bambu Lab (`B1–B3`)**, covering hybrid Early-Cut + Pre-Cut Retraction, `bucket_only` multi-chunk `RETRACT_ONLY`, disabled-mode regression, and `M620.11 S1` conflict omission.

> **Upgrade Note for Klipper Users:** Update your `SmartPurge.cfg` on the printer and restart Klipper firmware before enabling **Dynamic Pre-Cut Retraction**.
> **Note for Bambu Lab Beta Testers:** Dynamic Pre-Cut Retraction is **experimental** on Bambu Lab printers (most beneficial on X1/P1 hotends). Ensure OrcaSlicer's native *Long retraction when cut* is disabled before testing, and monitor the first toolchanges closely.