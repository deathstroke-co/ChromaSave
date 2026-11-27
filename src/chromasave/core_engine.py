# ChromaSave - OrcaSlicer Post-processing plugin for filament optimization and waste reduction.
# Copyright (C) 2026 Luis Miguel Lara (deathstroke-co)
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import math
import re
import datetime

try:
    from ._version import __version__
except ImportError:
    from _version import __version__

class DualLogger:
    """Duplicates stdout to both console and a persistent log file."""
    def __init__(self, log_path):
        self.terminal = sys.stdout
        self.log_file = None
        try:
            self.log_file = open(log_path, "a", encoding="utf-8")
        except Exception as e:
            print(f"[ChromaSave LOG] Alert: Could not open console log file ({e})", file=sys.stderr)

    def write(self, message):
        self.terminal.write(message)
        if self.log_file is not None:
            try:
                self.log_file.write(message)
            except Exception:
                pass

    def flush(self):
        self.terminal.flush()
        if self.log_file is not None:
            try:
                self.log_file.flush()
            except Exception:
                pass

    def close(self):
        if self.log_file is not None:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None

    def __getattr__(self, name):
        return getattr(self.terminal, name)


def hex_to_color_name(hex_code):
    """Converts a HEX code to an approximate color name."""
    hex_code = hex_code.strip()
    if not hex_code.startswith('#') or len(hex_code) != 7:
        return hex_code
    
    try:
        r, g, b = tuple(int(hex_code[i:i+2], 16) for i in (1, 3, 5))
    except ValueError:
        return hex_code

    colors = {
        "Black": (0,0,0), "White": (255,255,255), "Red": (255,0,0),
        "Lime": (0,255,0), "Blue": (0,0,255), "Yellow": (255,255,0),
        "Cyan": (0,255,255), "Magenta": (255,0,255), "Silver": (192,192,192),
        "Gray": (128,128,128), "Maroon": (128,0,0), "Olive": (128,128,0),
        "Green": (0,128,0), "Purple": (128,0,128), "Teal": (0,128,128),
        "Navy": (0,0,128), "Orange": (255,165,0), "Pink": (255,192,203),
        "Brown": (165,42,42), "Gold": (255,215,0)
    }
    
    min_dist = float('inf')
    closest_name = hex_code
    for name, (cr, cg, cb) in colors.items():
        dist = (r - cr)**2 + (g - cg)**2 + (b - cb)**2
        if dist < min_dist:
            min_dist = dist
            closest_name = name
            
    return closest_name

def append_retract_param(line_str, retract_mm):
    """Appends RETRACT_BEFORE_CUT parameter to a Klipper FILAMENT_CHANGE command."""
    if retract_mm <= 0.0:
        return line_str
    stripped = line_str.rstrip('\r\n')
    newline = '\r\n' if line_str.endswith('\r\n') else '\n'
    return f"{stripped} RETRACT_BEFORE_CUT={retract_mm:.2f}{newline}"

def filament_change_optimizer(config):
    """Entry point with passive persistent DualLogger in ~/chromasave_logs/ (no os.makedirs)."""
    persistent_log_dir = os.path.join(os.path.expanduser("~"), "chromasave_logs")
    console_log_path = None
    history_log_path = None
    dual_logger = None
    original_stdout = sys.stdout

    try:
        if os.path.isdir(persistent_log_dir):
            test_console_path = os.path.join(persistent_log_dir, "chromasave_console.log")
            logger = DualLogger(test_console_path)
            if logger.log_file is not None:
                dual_logger = logger
                console_log_path = test_console_path
                history_log_path = os.path.join(persistent_log_dir, "chromasave_history.log")
                sys.stdout = dual_logger
    except Exception:
        # Sandbox blocked access or folder unavailable: skip external logs silently
        console_log_path = None
        history_log_path = None

    try:
        if dual_logger is not None:
            run_ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print("\n" + "=" * 90)
            print(f"[{run_ts}] ChromaSave Run | Input: {config.filepath}")
            print("=" * 90)
        return _run_optimizer(config, history_log_path, console_log_path)
    finally:
        if dual_logger is not None:
            sys.stdout = original_stdout
            dual_logger.close()

def _run_optimizer(config, history_log_path, console_log_path):
    try:
        with open(config.filepath, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except FileNotFoundError:
        print(f"Post-Processing Error: The file doesn't exist in the path {config.filepath}", file=sys.stderr)
        sys.exit(1)
    except PermissionError:
        print(f"Post-Processing Error: No permission to open the file: {config.filepath}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Post-Processing Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # CONSTANTS & PARAMETERS
    REMAINING_LENGTH = getattr(config, 'len', 64.857)
    SAFETY_MARGIN = getattr(config, 'sm', 10.0)
    TARGET = max(0.0, REMAINING_LENGTH - SAFETY_MARGIN)
    
    SEARCH_RETRACTIONS = getattr(config, 'sre', True)
    RETRACTION_MARGIN = getattr(config, 'rem', 5.0)
    AVOID_IN_PIECE_CUT = getattr(config, 'aipc', True)
    PURGE_TARGET = getattr(config, 'purge_target', 'hybrid').strip().lower()
    MIN_SAVING_THRESHOLD = getattr(config, 'min_saving', 3.0)
    ENABLE_PRE_CUT_RETRACT = bool(getattr(config, 'pre_cut_retract', False))
    MAX_PRE_CUT_RETRACT = float(getattr(config, 'max_pre_cut_retract', 18.0))
    
    SAFETY_ZONES = {
        "Prime tower": True,            
        "Wipe tower": True,             
        "Support": True,                
        "Support interface": True,      
        "Sparse infill": True,          
        "Dense infill": True,           
        "Solid infill": True,           
        "Internal solid infill": True, 
        "Skirt": True,                 
        "Brim": True,                  
        "Gap fill": True,              
        "Outer wall": True,            
        "Inner wall": True,            
        "Overhang wall": True,         
        "Top surface": True,           
        "Bottom surface": True,        
        "Internal bridge": True,       
        "Bridge": True,                
        "Custom": True                 
    }
    
    dzones = getattr(config, 'dzones', None) or []
    for zone in dzones:
        SAFETY_ZONES[zone] = False
        
    print(f"Final SAFETY_ZONE defined: {SAFETY_ZONES}")
    print("Current status of functions:")
    for zone, state in SAFETY_ZONES.items():
        print(f"- {zone}: {'Active' if state else 'Deactivated'}")
    
    PROTECTED_BLOCKS = [
        (";WIPE_START", ";WIPE_END"),
        ("; CP TOOLCHANGE WIPE", "; CP TOOLCHANGE END"),
        ("; CP EMPTY GRID START", "; CP EMPTY GRID END")
    ]
     
    # REGULAR EXPRESSIONS
    re_extrusion = re.compile(r"^(?:G1|G2|G3|G0)\b.*?\b[Ee](-?[0-9]*\.?[0-9]+)")
    re_retraction = re.compile(r"^(?:(?:G1|G2|G3|G0)\b.*?\b[Ee](-[0-9]*\.?[0-9]+)|G10\b)")
    re_z_hop = re.compile(r"^G1\b.*?[Zz]([0-9]*\.?[0-9]+)")
    re_filament_change = re.compile(r"^FILAMENT_CHANGE\s+LAYER_NUM=(-?\d+)")
    re_layer_comment = re.compile(r"^;\s*(?:LAYER:|layer_num\s*=)\s*(-?\d+)", re.IGNORECASE)
    re_tool = re.compile(r"^(T\d+)")
    re_bambu_tool = re.compile(r"^M620\s+S(\d+)")
    re_bambu_long_retract = re.compile(r"^M620\.11\s+S1\b")
    re_sparkx_long_retract = re.compile(r"^M8200\s+R\s+E-")
    re_sparkx_cut = re.compile(r"^M8200\s+C\b")
    re_sparkx_load = re.compile(r"^M8200\s+L\b")
    re_fan_speed = re.compile(r"^M106\s+(?:P0\s+)?S([0-9]*\.?[0-9]+)")
    re_x0_park = re.compile(r"^\s*G[01]\s+X0(?:\.0+)?\b")
    re_k2_cfs_model = re.compile(r"^\s*;\s*printer_model\s*=\s*Creality\s+K2\b", re.IGNORECASE)

    re_purge = re.compile(r"^\s*PURGE_IN_TRASH")
    re_type = re.compile(r"^;\s*(?:TYPE|FEATURE|_EXTRUSION_ROLE):\s*(.+)", re.IGNORECASE)
    re_wipe_start = re.compile(r"^;\s*(?:CP TOOLCHANGE WIPE|WIPE_TOWER_START)", re.IGNORECASE)
    re_wipe_end = re.compile(r"^;\s*(?:CP TOOLCHANGE END|WIPE_TOWER_END)", re.IGNORECASE)
    re_e_reset = re.compile(r"E(-?[0-9]*\.?[0-9]+)")
    re_accel = re.compile(r"^M204\s+S([0-9]*\.?[0-9]+)")
    
    re_fmatrix = re.compile(r"^\s*; flush_volumes_matrix = (.+)")
    re_gmultiplier = re.compile(r"^\s*; flush_multiplier = (.+)")
    re_gdiams = re.compile(r"^\s*; filament_diameter = (.+)")
    re_gdens = re.compile(r"^\s*; filament_density = (.+)")
    re_gcolor = re.compile(r"^\s*; filament_colour = (.+)")
    re_gtype = re.compile(r"^\s*; filament_type = (.+)")
    re_gmin_purge = re.compile(r"^\s*; filament_minimal_purge_on_wipe_tower = (.+)")
    re_gprime_volume = re.compile(r"^\s*; prime_volume = (.+)")
    re_long_retract_cut = re.compile(r"^\s*; filament_long_retractions_when_cut = (.+)")
    re_global_long_retract_cut = re.compile(r"^\s*; long_retractions_when_cut = (.+)")
    re_nozzle_temp = re.compile(r"^\s*; nozzle_temperature = (.+)")
    re_nozzle_temp_init = re.compile(r"^\s*; nozzle_temperature_initial_layer = (.+)")

    re_m82 = re.compile(r"^\s*M82\b")
    re_m83 = re.compile(r"^\s*M83\b")
    
    total_lines = len(lines)
    line_extrusions = [0.0] * total_lines
    line_types = ["unknown"] * total_lines
    line_layers = [0] * total_lines
    unbreakable_ranges = []
    active_blocks = {start: -1 for start, end in PROTECTED_BLOCKS}
    
    current_type = "unknown"
    current_layer = 0
    saw_explicit_layer = False
    is_absolute_e = False
    last_e = 0.0
    max_e = 0.0                     
    current_retraction_depth = 0.0  

    state_x = [0.0] * total_lines
    state_y = [0.0] * total_lines
    state_z = [0.0] * total_lines
    state_f = [0.0] * total_lines
    state_accel = [0.0] * total_lines
    state_fan = [0.0] * total_lines

    current_x, current_y, current_z, current_f, current_accel, current_fan = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    printer_mode = "klipper"
    first_layer_change_idx = 0
    initial_tool_idx = None
    first_tc_seen = False

    long_retract_cut_flags = []
    global_long_retract_cut = 0
    nozzle_temps = []
    nozzle_temps_init = []

    re_bambu_tc_start = re.compile(r"^;\s*CP TOOLCHANGE START")
    re_bambu_tc_end = re.compile(r"^;\s*CP TOOLCHANGE END")
    re_flush_start = re.compile(r"^;\s*FLUSH_START")
    re_flush_end = re.compile(r"^;\s*FLUSH_END")
    
    re_coord_x = re.compile(r"X(-?[0-9]*\.?[0-9]+)")
    re_coord_y = re.compile(r"Y(-?[0-9]*\.?[0-9]+)")
    re_coord_z = re.compile(r"Z(-?[0-9]*\.?[0-9]+)")
    re_feedrate = re.compile(r"F([0-9]*\.?[0-9]+)")
    
    search_type = re_type.search
    search_ext = re_extrusion.search
    search_e_reset = re_e_reset.search
    
    area = 0.0

    # PRE-PROCESSING
    for i in range(total_lines):
        line = lines[i]
        
        # Layer Tracking Universal
        if "LAYER" in line or "layer" in line:
            m_lc = re_layer_comment.search(line)
            if m_lc:
                current_layer = int(m_lc.group(1))
                saw_explicit_layer = True
            else:
                m_fc = re_filament_change.search(line)
                if m_fc:
                    current_layer = int(m_fc.group(1))
                    saw_explicit_layer = True
                elif ("; CHANGE_LAYER" in line or ";LAYER_CHANGE" in line) and not saw_explicit_layer:
                    current_layer += 1
                    if first_layer_change_idx == 0:
                        first_layer_change_idx = i
        line_layers[i] = current_layer
        
        # Topology Tracking
        if re_wipe_start.search(line) or re_wipe_end.search(line) or "; FLUSH_END" in line:
            current_type = "Prime tower"
        elif "; FLUSH_START" in line:
            current_type = "Toolchange"
        elif ";" in line:
            match_type = search_type(line)
            if match_type:
                current_type = match_type.group(1).strip()
        line_types[i] = current_type
        
        # Protected Blocks
        for start_tag, end_tag in PROTECTED_BLOCKS:
            if start_tag in line: 
                active_blocks[start_tag] = i
            elif end_tag in line and active_blocks[start_tag] != -1:
                unbreakable_ranges.append((active_blocks[start_tag], i))
                active_blocks[start_tag] = -1
        
        # Printer Detection
        if line.startswith("M620 S"):
            printer_mode = "bambu"
        elif line.startswith("M8200 "):
            printer_mode = "sparkx_i7"
        elif printer_mode == "klipper" and re_k2_cfs_model.search(line):
            printer_mode = "k2_cfs"

        # Capture initial tool loaded in Start G-code before the first change
        if not first_tc_seen:
            if current_layer >= 1 or "; CP TOOLCHANGE START" in line or line.startswith("FILAMENT_CHANGE"):
                first_tc_seen = True
            else:
                m_init_t = re_tool.search(line)
                if m_init_t:
                    t_num = int(m_init_t.group(1)[1:])
                    if t_num < 16:
                        initial_tool_idx = t_num
                else:
                    m_init_bt = re_bambu_tool.search(line)
                    if m_init_bt:
                        t_num = int(m_init_bt.group(1))
                        if t_num < 16:
                            initial_tool_idx = t_num

        mx = re_coord_x.search(line)
        my = re_coord_y.search(line)
        mz = re_coord_z.search(line)
        mf = re_feedrate.search(line)
        ma = re_accel.search(line)
        
        if mx: current_x = float(mx.group(1))
        if my: current_y = float(my.group(1))
        if mz: current_z = float(mz.group(1))
        if mf: current_f = float(mf.group(1))
        if ma: current_accel = float(ma.group(1))
        
        state_x[i] = current_x
        state_y[i] = current_y
        state_z[i] = current_z
        state_f[i] = current_f

        mfan = re_fan_speed.search(line)
        if mfan:
            current_fan = float(mfan.group(1))
        elif line.startswith("M107"):
            current_fan = 0.0

        state_accel[i] = current_accel
        state_fan[i] = current_fan
                
        # API Fallback & Config Block Parsing
        if not hasattr(config, "flush_multiplier") and "; flush_multiplier =" in line:
            m = re_gmultiplier.search(line)
            if m: config.flush_multiplier = float(m.group(1).strip())
        if not hasattr(config, "flush_matrix") and "; flush_volumes_matrix =" in line:
            m = re_fmatrix.search(line)
            if m: config.flush_matrix = [float(n.strip())/getattr(config, 'flush_multiplier', 1.0) for n in m.group(1).split(",") if n.strip()]
        if not hasattr(config, "diams") and "; filament_diameter =" in line:    
            m = re_gdiams.search(line)
            if m: config.diams = [float(n.strip()) for n in m.group(1).split(",") if n.strip()]            
        if not hasattr(config, "densities") and "; filament_density =" in line:   
            m = re_gdens.search(line)
            if m: config.densities = [float(n.strip()) for n in m.group(1).split(",") if n.strip()]
        if not hasattr(config, "colors") and "; filament_colour =" in line:    
            m = re_gcolor.search(line)
            if m: config.colors = [str(n.strip()) for n in m.group(1).split(";") if n.strip()]
        if not hasattr(config, "types") and "; filament_type =" in line:    
            m = re_gtype.search(line)
            if m: config.types = [str(n.strip()) for n in m.group(1).split(";") if n.strip()]
        if not hasattr(config, "min_purge") and "; filament_minimal_purge_on_wipe_tower =" in line:
            m = re_gmin_purge.search(line)
            if m: config.min_purge = [float(n.strip()) for n in m.group(1).split(",") if n.strip()]
        if not hasattr(config, "prime_volume") and "; prime_volume =" in line:
            m = re_gprime_volume.search(line)
            if m: config.prime_volume = float(m.group(1).strip())
        if not long_retract_cut_flags and "; filament_long_retractions_when_cut =" in line:
            m = re_long_retract_cut.search(line)
            if m: long_retract_cut_flags = [int(n.strip()) for n in m.group(1).split(",") if n.strip().isdigit()]
        if global_long_retract_cut == 0 and "; long_retractions_when_cut =" in line:
            m = re_global_long_retract_cut.search(line)
            if m and m.group(1).strip().isdigit():
                global_long_retract_cut = int(m.group(1).strip())
        if not nozzle_temps and "; nozzle_temperature =" in line:
            m = re_nozzle_temp.search(line)
            if m: nozzle_temps = [float(n.strip()) for n in m.group(1).split(",") if n.strip()]
        if not nozzle_temps_init and "; nozzle_temperature_initial_layer =" in line:
            m = re_nozzle_temp_init.search(line)
            if m: nozzle_temps_init = [float(n.strip()) for n in m.group(1).split(",") if n.strip()]
            
        if re_m82.search(line):
            is_absolute_e = True
        elif re_m83.search(line):
            is_absolute_e = False
            
        # G92 E0 Handling
        if "G92" in line and "E" in line:
            m_e_reset = search_e_reset(line)
            reset_val = float(m_e_reset.group(1)) if m_e_reset else 0.0
            last_e = reset_val
            max_e = reset_val
            current_retraction_depth = 0.0
        
        # Extrusion Extraction
        if line.startswith(("G1", "G2", "G3", "G0")) and "E" in line:
            match_ext = search_ext(line)
            if match_ext:
                e_val = float(match_ext.group(1))
                if is_absolute_e:
                    if e_val > max_e:
                        delta_e = e_val - max_e
                        max_e = e_val
                    else:
                        delta_e = 0.0
                    last_e = e_val
                else:
                    if e_val < 0:
                        current_retraction_depth += abs(e_val)
                        delta_e = 0.0
                    else:
                        if current_retraction_depth > 0:
                            recovered = min(current_retraction_depth, e_val)
                            current_retraction_depth -= recovered
                            delta_e = e_val - recovered
                        else:
                            delta_e = e_val
                            
                line_extrusions[i] = delta_e

    is_bambu_lab = (printer_mode == "bambu")
    is_sparkx_i7 = (printer_mode == "sparkx_i7")
    is_k2_cfs = (printer_mode == "k2_cfs")
    is_native_gcode_tc = is_bambu_lab or is_sparkx_i7 or is_k2_cfs
    
    # IDENTIFYING BLOCKS AND TOOLS
    changes = []
    i = 0
    while i < total_lines:
        line = lines[i]

        match_klipper = re_filament_change.search(line) if not is_native_gcode_tc else None
        match_native = re_bambu_tc_start.search(line) if is_native_gcode_tc else None

        # Fallback detection when enable_prime_tower = 0 (no '; CP TOOLCHANGE START')
        no_tower_mode = None
        if is_native_gcode_tc and not match_native and line_layers[i] >= 1:
            if is_bambu_lab:
                m_bt_raw = re_bambu_tool.search(line)
                if m_bt_raw and int(m_bt_raw.group(1)) != 255:
                    no_tower_mode = "bambu"
            elif is_k2_cfs:
                m_t_raw = re_tool.search(line)
                if m_t_raw and int(m_t_raw.group(1)[1:]) < 16:
                    no_tower_mode = "k2_cfs"
            elif is_sparkx_i7:
                if re_sparkx_cut.search(line):
                    no_tower_mode = "sparkx_i7"

        if match_klipper or match_native or no_tower_mode:
            origin = i
            end_move = i
            layer_num = int(match_klipper.group(1)) if match_klipper else line_layers[i]

            # Back-scan preambles when there is no '; CP TOOLCHANGE START'
            if no_tower_mode == "bambu":
                for back_k in range(i - 1, max(-1, i - 6), -1):
                    st_b = lines[back_k].strip()
                    if st_b.startswith(("M1007 S0", "G392 S0")):
                        origin = back_k
                    elif st_b == "" or st_b.startswith(";"):
                        continue
                    else:
                        break
            elif no_tower_mode == "k2_cfs":
                for back_k in range(i - 1, max(-1, i - 12), -1):
                    st_b = lines[back_k].strip()
                    if st_b == "" or st_b.startswith((";", "M73", "M106", "G17", "G2 ", "G3 ")) or re_x0_park.match(st_b) or (st_b.startswith("G1 Z") and "E" not in st_b):
                        if st_b != "" and not st_b.startswith(";"):
                            origin = back_k
                    else:
                        break
            elif no_tower_mode == "sparkx_i7":
                for back_k in range(i - 1, max(-1, i - 15), -1):
                    st_b = lines[back_k].strip()
                    if st_b == "" or st_b.startswith((";", "M73", "M106", "M104", "M400", "M8200", "SET_VELOCITY_LIMIT", "G17", "G2 ", "G3 ")) or re_x0_park.match(st_b) or (st_b.startswith(("G0 ", "G1 ")) and "E" not in st_b and "Z" in st_b):
                        if st_b != "" and not st_b.startswith(";"):
                            origin = back_k
                    else:
                        break

            t_idx = 0
            current_tool = "T?"

            tc_block_end = i
            wipe_sub_start = -1
            tool_line_idx = -1
            search_limit = min(i + 400, total_lines)

            if no_tower_mode == "k2_cfs":
                m_t_k2 = re_tool.search(lines[i])
                current_tool = m_t_k2.group(1)
                t_idx = int(current_tool[1:])
                tool_line_idx = i
                tc_block_end = i
            else:
                for j in range(origin, search_limit):
                    match_tool = re_tool.search(lines[j])
                    if match_tool:
                        current_tool = match_tool.group(1)
                        if current_tool[1:].isdigit():
                            t_idx = int(current_tool[1:])
                            if tool_line_idx == -1:
                                tool_line_idx = j
                    elif is_bambu_lab:
                        m_bt = re_bambu_tool.search(lines[j])
                        if m_bt and int(m_bt.group(1)) != 255:
                            t_idx = int(m_bt.group(1))
                            current_tool = f"T{t_idx}"

                    if is_native_gcode_tc:
                        if "; CP TOOLCHANGE WIPE" in lines[j] and wipe_sub_start == -1:
                            wipe_sub_start = j

                        if no_tower_mode == "bambu":
                            if lines[j].startswith("M621 S"):
                                tc_block_end = j
                                for fwd_k in range(j + 1, min(j + 6, total_lines)):
                                    if lines[fwd_k].strip().startswith(("G392 S0", "M1007 S1")):
                                        tc_block_end = fwd_k
                                    elif lines[fwd_k].strip() != "":
                                        break
                                break
                        elif no_tower_mode == "sparkx_i7":
                            st_j = lines[j].strip()
                            if j > i and (st_j.startswith((";TYPE:", ";FEATURE:", ";LAYER_CHANGE", "; CHANGE_LAYER")) or re_sparkx_cut.search(st_j)):
                                break
                            if st_j.startswith("M8200 O") or re_flush_end.search(lines[j]) or re_sparkx_load.search(st_j):
                                tc_block_end = j
                                if st_j.startswith("M8200 O"):
                                    break
                        elif re_bambu_tc_end.search(lines[j]):
                            tc_block_end = j
                            break
                    elif not is_native_gcode_tc and match_tool:
                        tc_block_end = j
                        break

            # Skip ghost/empty CP TOOLCHANGE START blocks (e.g., end-of-print tower close)
            if is_native_gcode_tc and current_tool == "T?":
                i = tc_block_end + 1
                continue

            # Capture ALL purge pulses
            idx_purge_start = -1
            idx_purge_end = -1
            wiper_x = None
            if is_k2_cfs:
                if tool_line_idx != -1:
                    end_move = max(origin, tool_line_idx - 1)
                    idx_purge_start = tool_line_idx
                    idx_purge_end = tool_line_idx
                elif wipe_sub_start != -1:
                    end_move = wipe_sub_start - 1
                else:
                    end_move = tc_block_end
            elif is_native_gcode_tc:
                m628_idx = -1
                m629_idx = -1
                for j in range(origin, min(tc_block_end + 50, total_lines)):
                    if "; CP TOOLCHANGE WIPE" in lines[j]:
                        break
                    if re_flush_start.search(lines[j]):
                        if idx_purge_start == -1:
                            idx_purge_start = j
                    elif re_flush_end.search(lines[j]):
                        idx_purge_end = j
                    elif is_bambu_lab:
                        st_l = lines[j].strip()
                        if st_l.startswith("M628 S0") and m628_idx == -1:
                            m628_idx = j
                        elif st_l == "M629" and m628_idx != -1 and m629_idx == -1:
                            m629_idx = j

                if is_bambu_lab and idx_purge_start == -1 and m628_idx != -1 and m629_idx > m628_idx + 1:
                    idx_purge_start = m628_idx + 1
                    idx_purge_end = m629_idx - 1

                if is_bambu_lab and idx_purge_end != -1:
                    for j in range(idx_purge_end + 1, min(tc_block_end + 1, total_lines)):
                        if lines[j].startswith("M621"):
                            break
                        if lines[j].startswith(("G1 ", "G0 ")) and "X" in lines[j]:
                            mx_w = re_coord_x.search(lines[j])
                            if mx_w:
                                val_x = float(mx_w.group(1))
                                if val_x < 0.0 and (wiper_x is None or val_x < wiper_x):
                                    wiper_x = val_x

                if idx_purge_start != -1:
                    end_move = idx_purge_start - 1
                    if is_bambu_lab:
                        for j in range(idx_purge_start - 1, origin, -1):
                            if lines[j].strip().startswith("M628 S0"):
                                end_move = j - 1
                                break
                    elif is_sparkx_i7:
                        while end_move > origin and (lines[end_move].strip() == "" or lines[end_move].lstrip().startswith(";flush_length")):
                            end_move -= 1
                elif wipe_sub_start != -1:
                    end_move = wipe_sub_start - 1
                else:
                    end_move = tc_block_end
            else:
                end_move = tc_block_end
                for j in range(end_move, min(end_move + 250, total_lines)):
                    if re_purge.search(lines[j]):
                        idx_purge_start = j
                        idx_purge_end = j
                        break

            # Direct G-code detection of Long Retraction When Cut
            has_bambu_lr = is_bambu_lab and any(
                re_bambu_long_retract.search(lines[k])
                for k in range(origin, min(end_move + 1, total_lines))
            )
            has_sparkx_lr = is_sparkx_i7 and any(
                re_sparkx_long_retract.search(lines[k])
                for k in range(origin, min(end_move + 1, total_lines))
            )

            slicer_flush_e_mm = 0.0
            if idx_purge_start != -1 and idx_purge_end != -1:
                slicer_flush_e_mm = sum(line_extrusions[k] for k in range(idx_purge_start, idx_purge_end + 1))

            changes.append({
                "layer": layer_num,
                "origin": origin,
                "end_move": end_move,
                "tc_block_end": tc_block_end,
                "wipe_sub_start": wipe_sub_start,
                "idx_purge_start": idx_purge_start,
                "idx_purge_end": idx_purge_end,
                "slicer_flush_e_mm": slicer_flush_e_mm,
                "has_bambu_lr": has_bambu_lr,
                "has_sparkx_lr": has_sparkx_lr,
                "wiper_x": wiper_x,
                "tool": current_tool,
                "t_idx": t_idx,
                "tower_e_mm": 0.0
            })

            i = max(tc_block_end, idx_purge_end)

        i += 1

    # EXACT TOWER CALCULATION
    if is_k2_cfs:
        bed_max_xy = 350.0
    elif is_sparkx_i7:
        bed_max_xy = 260.0
    else:
        bed_max_xy = 256.0

    for idx_change, c in enumerate(changes):
        if is_k2_cfs:
            start_search = (c["idx_purge_end"] + 1) if c["idx_purge_end"] != -1 else (c["end_move"] + 1)
            chute_x, chute_y = -999.0, -999.0
        elif is_native_gcode_tc:
            start_search = (c["idx_purge_end"] + 1) if c["idx_purge_end"] != -1 else (c["end_move"] + 1)
            chute_x = state_x[c["idx_purge_end"]] if c["idx_purge_end"] != -1 else state_x[c["origin"]]
            chute_y = state_y[c["idx_purge_end"]] if c["idx_purge_end"] != -1 else state_y[c["origin"]]
        else:
            start_search = max(c["end_move"], c["idx_purge_end"]) + 1
            chute_x, chute_y = -999.0, -999.0

        next_origin = changes[idx_change + 1]["origin"] if (idx_change + 1) < len(changes) else total_lines
        end_search = min(start_search + 5000, next_origin)

        tower_e_mm = 0.0
        for j in range(start_search, end_search):
            if line_extrusions[j] <= 0.0:
                continue
            t_type = line_types[j]
            if "Prime tower" in t_type or "Wipe tower" in t_type:
                if is_native_gcode_tc:
                    if abs(state_x[j] - chute_x) < 1.0 and abs(state_y[j] - chute_y) < 1.0:
                        continue
                    if state_x[j] < 0.0 or state_x[j] > bed_max_xy or state_y[j] < 0.0 or state_y[j] > bed_max_xy:
                        continue
                tower_e_mm += line_extrusions[j]

        c["tower_e_mm"] = tower_e_mm
        
    # BACKTRACKING WITH CHRONOLOGICAL PROTECTION & DYNAMIC PRE-CUT RETRACTION
    long_retract_warning = False
    for idx_change, c in enumerate(changes):
        curr_t_idx = c.get("t_idx", 0)
        fallback_prev = initial_tool_idx if initial_tool_idx is not None else curr_t_idx
        prev_t_idx = changes[idx_change - 1].get("t_idx", 0) if idx_change > 0 else fallback_prev

        if is_bambu_lab:
            has_long_retract = c.get("has_bambu_lr", False)
            lr_source = "M620.11 S1 in toolchange G-code"
        elif is_sparkx_i7:
            has_long_retract = c.get("has_sparkx_lr", False)
            lr_source = "M8200 R E- in toolchange G-code"
        else:
            filament_lr_active = (
                prev_t_idx < len(long_retract_cut_flags)
                and long_retract_cut_flags[prev_t_idx] == 1
            )
            has_long_retract = filament_lr_active or (global_long_retract_cut == 1)
            lr_source = f"T{prev_t_idx} filament profile" if filament_lr_active else "global printer settings"


        is_init_block = (c["layer"] < 1) if is_native_gcode_tc else (c["layer"] < 0)

        if has_long_retract:
            candidate_index = c["origin"]
            candidate_saving = 0.0
            c["break_flag"] = f"Incompatible: long_retractions_when_cut active ({lr_source}) (Early-cut omitted)"
            c["status_tag"] = "[OMITTED: LONG_RETRACT]"
            long_retract_warning = True
        elif is_init_block:
            candidate_index = c["origin"]
            candidate_saving = 0.0
            c["break_flag"] = "Blocked by initialization (0.00 mm)"
            c["status_tag"] = "[OMITTED: INIT]"
        else:
            e_acumulated = 0.0
            candidate_index = c["origin"]
            candidate_saving = 0.0
            break_flag = "Unknown"

            if idx_change == 0:
                lower_limit = first_layer_change_idx + 1
            else:
                previous_change = changes[idx_change - 1]
                if is_native_gcode_tc:
                    lower_limit = max(previous_change["origin"], previous_change["end_move"], previous_change["idx_purge_end"]) + 1
                else:
                    lower_limit = max(previous_change["origin"], previous_change["end_move"], previous_change["idx_purge_start"]) + 1
                
            is_in_skippable_block = False
                
            for idx in range(c["origin"] - 1, lower_limit - 1, -1):
                line = lines[idx]
                
                # --- GEOMETRIC FILTERS FOR BAMBU LAB ---
                if "; SKIPPABLE_END" in line:
                    is_in_skippable_block = True
                    continue
                if "; SKIPPABLE_START" in line:
                    is_in_skippable_block = False
                    continue
                if is_in_skippable_block:
                    continue
                    
                if line.startswith(("M620", "M621", "M622", "M628", "M629", "M1002", "M1004", "M1006", "M1007", "M971", "M8200", "M5001")):
                    continue

                if is_native_gcode_tc and line.startswith(("G1", "G0")) and "X" in line:
                    mx = re_coord_x.search(line)
                    if mx and (float(mx.group(1)) > bed_max_xy or float(mx.group(1)) < 0.0):
                        continue
                # --- END FILTERS ---
                
                if "T" in line or "FILAMENT_CHANGE" in line or "PURGE_IN_TRASH" in line:
                    if re_tool.search(line) or re_filament_change.search(line) or re_purge.search(line):
                        break_flag = "Collision limit (No safe saving)" if candidate_index == c["origin"] else "Collision in a safe zone"
                        break
                    
                e_acumulated += line_extrusions[idx]
                
                if e_acumulated > TARGET:
                    break_flag = "Target reached. Safety zone not found (0 savings)" if candidate_index == c["origin"] else "Target reached in a safe zone"
                    break
                
                current_type = line_types[idx]
                is_safe_zone = True
                
                if AVOID_IN_PIECE_CUT:
                    is_safe_zone = any((z in current_type and state) for z, state in SAFETY_ZONES.items())
                    
                # Only register candidate on lines with real extrusion (or valid retraction)
                is_retract_line = (
                    SEARCH_RETRACTIONS
                    and (("G1" in line and "E-" in line) or "G10" in line)
                    and re_retraction.search(line)
                )
                if is_safe_zone and e_acumulated > 0.0 and (line_extrusions[idx] > 0.0 or is_retract_line):
                    if is_native_gcode_tc and idx > 0:
                        px, py = state_x[idx - 1], state_y[idx - 1]
                        if (px == 0.0 and py == 0.0) or px < 0.0 or px > bed_max_xy or py < 0.0 or py > bed_max_xy:
                            continue
                    candidate_index = idx
                    candidate_saving = e_acumulated

                    if is_retract_line:
                        if (TARGET - RETRACTION_MARGIN) <= e_acumulated <= TARGET:
                            safe_insert = idx + 1

                            if safe_insert < c["origin"] and "Z" in lines[safe_insert] and re_z_hop.search(lines[safe_insert]):
                                safe_insert += 1

                            candidate_index = safe_insert
                            break_flag = "Retraction (Firmware or Standard) and Z-hop found in safety zone"
                            break
            else:
                break_flag = "Lower limit achieved without safety zones" if candidate_index == c["origin"] else "Lower limit achieved in safety zone"
                
            # Smart placement to avoid protected blocks (Backwards jump)
            original_idx = candidate_index
            moved = True
            
            while moved and candidate_index < c["origin"]:
                moved = False
                for r_start, r_end in unbreakable_ranges:
                    if is_native_gcode_tc and "; CP TOOLCHANGE WIPE" in lines[r_start] and SAFETY_ZONES.get("Prime tower", True):
                        continue
                    if r_start <= candidate_index <= r_end:
                        candidate_index = r_end + 1
                        moved = True
                        
                if candidate_index >= c["origin"]:
                    candidate_index = c["origin"]
                    break
                
                if candidate_index >= 0:
                    line_str = lines[candidate_index]
                    if "SET_VELOCITY_LIMIT" in line_str or line_str.strip() == "" or (line_str.startswith(("G1", "G2", "G3", "G0")) and "E-" in line_str and re_retraction.search(line_str)):
                        candidate_index += 1
                        moved = True
                        
            # Recalculate Volumetric Saving if index moved
            if candidate_index != original_idx:
                recalc_saving = sum(line_extrusions[k] for k in range(c["origin"] - 1, candidate_index - 1, -1))
                candidate_saving = min(recalc_saving, TARGET)
                
            # STRICT FILTER FOR MINIMUM SAVING AND ZERO SAVING
            if candidate_saving <= 0.0:
                candidate_index = c["origin"]
                candidate_saving = 0.0
                c["status_tag"] = "[OMITTED: NO SAVING]"
                c["break_flag"] = f"{break_flag} (0.00 mm)"
            elif candidate_saving < MIN_SAVING_THRESHOLD:
                raw_sav = candidate_saving
                candidate_index = c["origin"]
                candidate_saving = 0.0
                c["status_tag"] = "[OMITTED: < MIN_SAVING]"
                c["break_flag"] = f"Saving below threshold: {raw_sav:.2f}mm < {MIN_SAVING_THRESHOLD:.1f}mm (Early-cut omitted)"
            else:
                c["status_tag"] = "[PARCIAL]" if ("Limit" in break_flag or "Collision" in break_flag) else "[SUCCESS]"
                c["break_flag"] = f"{break_flag} ({candidate_saving:.2f} mm)"

        # DYNAMIC PRE-CUT RETRACTION (Klipper + Experimental Bambu Lab)
        pre_cut_retract_mm = 0.0
        if ENABLE_PRE_CUT_RETRACT and not has_long_retract and not is_init_block:
            gap_mm = max(0.0, TARGET - candidate_saving)
            pre_cut_retract_mm = min(gap_mm, MAX_PRE_CUT_RETRACT)
            if pre_cut_retract_mm < 0.5:
                pre_cut_retract_mm = 0.0

        total_change_saving = candidate_saving + pre_cut_retract_mm

        if pre_cut_retract_mm > 0.0 and candidate_saving <= 0.0:
            c["status_tag"] = "[RETRACT_ONLY]"
            c["break_flag"] = f"Early-cut omitted; Pre-Cut Retraction active ({pre_cut_retract_mm:.2f} mm)"
        elif pre_cut_retract_mm > 0.0 and candidate_saving > 0.0:
            c["break_flag"] = f"{c['break_flag']} + PreCutRet: {pre_cut_retract_mm:.2f} mm"
            
        # PHYSICOCHEMICAL MODEL INTEGRATED FOR ORCASLICER
        dia = config.diams[curr_t_idx] if hasattr(config, 'diams') and curr_t_idx < len(config.diams) else getattr(config, 'dia', 1.75)
        area = math.pi * ((dia / 2.0) ** 2)
        
        min_purge_limit = config.min_purge[curr_t_idx] if hasattr(config, 'min_purge') and curr_t_idx < len(config.min_purge) else 10.0
        
        flush_vol_mm3 = 0.0 
        if hasattr(config, 'flush_matrix') and config.flush_matrix:
            try:
                matrix_size = int(math.sqrt(len(config.flush_matrix)))
                if prev_t_idx < matrix_size and curr_t_idx < matrix_size:
                    matrix_idx = (prev_t_idx * matrix_size) + curr_t_idx
                    multiplier = getattr(config, 'flush_multiplier', 1.0)
                    base_vol = config.flush_matrix[matrix_idx] * multiplier
                    flush_vol_mm3 = max(base_vol, min_purge_limit)
            except Exception:
                flush_vol_mm3 = min_purge_limit
        else:
            flush_vol_mm3 = min_purge_limit
        
        c["flush_vol"] = flush_vol_mm3
        c["prev_t_idx"] = prev_t_idx
        
        target_flush_mm = (flush_vol_mm3 / area) if area > 0 else 0.0
        total_purge_needed_mm = max(target_flush_mm, REMAINING_LENGTH)
        c["total_purge_mm"] = total_purge_needed_mm
        
        # HYBRID VS BUCKET_ONLY LOGIC FOR ORCASLICER
        if is_native_gcode_tc and c.get("status_tag") == "[OMITTED: LONG_RETRACT]" and c.get("slicer_flush_e_mm", 0.0) > 0.0:
            calculate_quantity = c["slicer_flush_e_mm"]
        elif PURGE_TARGET == "hybrid":
            remaining_purge_mm = total_purge_needed_mm - c["tower_e_mm"] - total_change_saving
            calculate_quantity = max(0.0, remaining_purge_mm)
        else: 
            calculate_quantity = max(0.0, total_purge_needed_mm - total_change_saving)
        
        c["cut_index"] = candidate_index
        c["saving_early_cut"] = candidate_saving
        c["saving_retract"] = pre_cut_retract_mm
        c["saving"] = total_change_saving
        c["calculate_quantity"] = calculate_quantity

    if long_retract_warning:
        print(
            "WARNING [ChromaSave]: 'Long retraction when cut' is enabled in OrcaSlicer (printer or filament settings). "
            "Early-Cut has been omitted on affected toolchanges because both features compete for the same filament segment. "
            "Disable 'Long retraction when cut' in your printer/filament settings to enable ChromaSave Early-Cut.",
            file=sys.stderr
        )
        
    # CONSTRUCTION AND LABELING OF THE NEW G-CODE
    insertions = { i: [] for i in range(len(lines) + 1) }
    line_to_erase = set()
    replacement = {}
    
    total_saving_early_cut = 0.0
    total_saving_retract = 0.0
    total_saving = 0.0
    optimized_changes = 0
    omitted_min_saving = 0
    omitted_no_saving = 0
    omitted_long_retract = 0

    SKIP_PURGE_THRESHOLD = getattr(config, 'skip_purge', 2.0)
    
    for idx_change, c in enumerate(changes):
        if c["layer"] < 0: continue

        ec_sav = c.get("saving_early_cut", 0.0)
        ret_sav = c.get("saving_retract", 0.0)
        did_early_cut = False

        if c.get("cut_index") < c["origin"] and ec_sav >= MIN_SAVING_THRESHOLD:
            # --- TOOLCHANGE MANAGEMENT (Early-Cut + Optional Pre-Cut Retract) ---
            block = lines[c["origin"] : c["end_move"] + 1]
            did_early_cut = True

            if is_bambu_lab:
                prev_idx = max(0, c["cut_index"] - 1)
                cut_x = state_x[prev_idx]
                cut_y = state_y[prev_idx]
                cut_z = state_z[prev_idx]
                cut_f = state_f[prev_idx]
                cut_accel = state_accel[prev_idx]
                cut_layer = line_layers[prev_idx]
                t_num = c.get("t_idx", 0)
                prev_t_num = c.get("prev_t_idx", 0)
                safe_z = cut_z + 3.0

                restore_temp = 0.0
                if cut_layer <= 1 and prev_t_num < len(nozzle_temps_init):
                    restore_temp = nozzle_temps_init[prev_t_num]
                elif prev_t_num < len(nozzle_temps):
                    restore_temp = nozzle_temps[prev_t_num]

                filtered_block = []
                seen_m620 = False
                for b_line in block:
                    stripped = b_line.strip()
                    if stripped.startswith("M620"):
                        seen_m620 = True
                    if not seen_m620 and stripped.startswith(("G1 ", "G2 ", "G3 ")) and "Z" in stripped:
                        continue
                    filtered_block.append(b_line)

                insertions[c["cut_index"]].extend([
                    "; --- ChromaSave Bambu Early-Cut ---\n",
                    "G1 E-1.6 F1800\n",
                    f"G1 Z{safe_z:.3f} F1200\n"
                ])
                if ret_sav > 0.0:
                    insertions[c["cut_index"]].extend([
                        f"; ChromaSave Bambu Experimental Pre-Cut Retraction (-{ret_sav:.2f} mm)\n",
                        f"G1 E-{ret_sav:.2f} F1800\n",
                        "M400\n"
                    ])
                insertions[c["cut_index"]].extend(filtered_block)

                return_cmds = [
                    f"M621 S{t_num}A\n",
                    "M1007 S1\n",
                    "M220 R\n",
                    "; --- ChromaSave Return Travel ---\n",
                ]
                if restore_temp > 0:
                    return_cmds.append(f"M104 S{restore_temp:.0f}\n")
                if ret_sav > 0.0:
                    return_cmds.extend([
                        f"; ChromaSave Bambu Experimental Post-Load Recovery (+{ret_sav:.2f} mm)\n",
                        f"G1 E{ret_sav:.2f} F300\n",
                        "M400\n"
                    ])
                return_cmds.extend([
                    f"G1 Z{safe_z:.3f} F1200\n",
                    f"G1 X{cut_x:.3f} Y{cut_y:.3f} F21000\n",
                    f"G1 Z{cut_z:.3f} F1200\n",
                    "G1 E1.6 F1800\n",
                ])
                if cut_accel > 0:
                    return_cmds.append(f"M204 S{cut_accel:.0f}\n")
                return_cmds.extend([
                    f"G1 F{cut_f:.1f}\n",
                    "G92 E0\n",
                    "; --------------------------------\n"
                ])
                insertions[c["cut_index"]].extend(return_cmds)

                wiper_x = c.get("wiper_x")
                if wiper_x is not None:
                    chute_travel_cmds = [
                        f"G1 X{wiper_x + 10.0:.1f} F18000\n",
                        f"G1 X{wiper_x:.1f} F3000\n"
                    ]
                else:
                    p_ref = c["idx_purge_start"] if c["idx_purge_start"] != -1 else c["origin"]
                    chute_travel_cmds = [
                        f"G1 X{state_x[p_ref]:.1f} Y{state_y[p_ref]:.1f} F18000\n"
                    ]

                origin_z = state_z[max(0, c["origin"] - 1)]
                origin_safe_z = max(safe_z, origin_z + 3.0)

                insertions[c["origin"]].extend([
                    "; --- ChromaSave Chute Re-route ---\n",
                    "M1007 S0\n",
                    f"G1 Z{origin_safe_z:.3f} F1200\n",
                    *chute_travel_cmds,
                    f"M620 S{t_num}A\n",
                    "G92 E0\n",
                    "; ---------------------------------\n"
                ])

            elif is_sparkx_i7:
                prev_idx = max(0, c["cut_index"] - 1)
                cut_x = state_x[prev_idx]
                cut_y = state_y[prev_idx]
                cut_z = state_z[prev_idx]
                cut_f = state_f[prev_idx]
                cut_accel = state_accel[prev_idx]
                cut_fan = state_fan[prev_idx]
                cut_layer = line_layers[prev_idx]
                prev_t_num = c.get("prev_t_idx", 0)
                safe_z = cut_z + 3.0

                restore_temp = 0.0
                if cut_layer <= 1 and prev_t_num < len(nozzle_temps_init):
                    restore_temp = nozzle_temps_init[prev_t_num]
                elif prev_t_num < len(nozzle_temps):
                    restore_temp = nozzle_temps[prev_t_num]

                filtered_block = []
                seen_cut_seq = False
                injected_pre_ret = False
                injected_post_rec = False
                for b_line in block:
                    stripped = b_line.strip()
                    if re_x0_park.match(stripped) or stripped.startswith("M8200"):
                        seen_cut_seq = True
                    # Filter prime-tower spiral lift moves before G1 X0 / M8200 starts
                    if not seen_cut_seq and (stripped == "G17" or (stripped.startswith(("G1 ", "G2 ", "G3 ")) and ("Z" in stripped or "X" in stripped))):
                        continue
                    if ret_sav > 0.0 and not injected_pre_ret and re_sparkx_cut.search(stripped):
                        filtered_block.extend([
                            f"; ChromaSave SPARKX i7 Native Pre-Cut Retraction (-{ret_sav:.2f} mm)\n",
                            f"M8200 R E-{ret_sav:.2f}\n",
                            "M400\n"
                        ])
                        injected_pre_ret = True
                    filtered_block.append(b_line)
                    if ret_sav > 0.0 and not injected_post_rec and re_sparkx_load.search(stripped):
                        filtered_block.extend([
                            f"; ChromaSave SPARKX i7 Native Post-Load Recovery (+{ret_sav:.2f} mm)\n",
                            f"G1 E{ret_sav:.2f} F349\n"
                        ])
                        injected_post_rec = True

                insertions[c["cut_index"]].extend([
                    "; --- ChromaSave SPARKX i7 Early-Cut ---\n",
                    "G1 E-1.6 F1800\n",
                    f"G1 Z{safe_z:.3f} F1200\n"
                ])
                insertions[c["cut_index"]].extend(filtered_block)

                return_cmds = [
                    "; --- ChromaSave SPARKX i7 Return Travel ---\n",
                    "SET_VELOCITY_LIMIT ACCEL=5000 ACCEL_TO_DECEL=5000\n",
                    "G0 X267 F2400\n",
                    "M8200 O\n",
                ]
                if restore_temp > 0:
                    return_cmds.append(f"M104 S{restore_temp:.0f}\n")
                return_cmds.extend([
                    f"M106 S{cut_fan:.0f}\n",
                    f"G1 Z{safe_z:.3f} F1200\n",
                    f"G1 X{cut_x:.3f} Y{cut_y:.3f} F24000\n",
                    f"G1 Z{cut_z:.3f} F1200\n",
                    "G1 E1.6 F1800\n",
                ])
                if cut_accel > 0:
                    return_cmds.append(f"M204 S{cut_accel:.0f}\n")
                return_cmds.extend([
                    f"G1 F{cut_f:.1f}\n",
                    "G92 E0\n",
                    "; ------------------------------------------\n"
                ])
                insertions[c["cut_index"]].extend(return_cmds)

                origin_z = state_z[max(0, c["origin"] - 1)]
                origin_safe_z = max(safe_z, origin_z + 3.0)

                insertions[c["origin"]].extend([
                    "; --- ChromaSave SPARKX i7 Chute Re-route ---\n",
                    "G1 E-2 F1800\n",
                    f"G1 Z{origin_safe_z:.3f} F1200\n",
                    "SET_VELOCITY_LIMIT ACCEL=5000 ACCEL_TO_DECEL=5000\n",
                    "G0 Y255 F18000\n",
                    "G0 X267 F18000\n",
                    "G0 Y130 F18000\n",
                    "G0 X278 F2400\n",
                    "G92 E0\n",
                    "; -------------------------------------------\n"
                ])

            elif is_k2_cfs:
                prev_idx = max(0, c["cut_index"] - 1)
                cut_layer = line_layers[prev_idx]
                t_num = c.get("t_idx", 0)
                prev_t_num = c.get("prev_t_idx", 0)

                restore_temp = 0.0
                if cut_layer <= 1 and prev_t_num < len(nozzle_temps_init):
                    restore_temp = nozzle_temps_init[prev_t_num]
                elif prev_t_num < len(nozzle_temps):
                    restore_temp = nozzle_temps[prev_t_num]

                ret_param = f" RETRACT_BEFORE_CUT={ret_sav:.2f}" if ret_sav > 0.0 else ""
                k2_cut_cmds = [
                    "; --- ChromaSave K2 CFS Early-Cut ---\n",
                    f"SMARTPURGE_K2_CUT NEXT_EXTRUDER={t_num}{ret_param}\n",
                ]
                if restore_temp > 0:
                    k2_cut_cmds.append(f"M104 S{restore_temp:.0f}\n")
                k2_cut_cmds.append("; -----------------------------------\n")
                insertions[c["cut_index"]].extend(k2_cut_cmds)

            else:
                klipper_block = []
                for b_line in block:
                    if ret_sav > 0.0 and re_filament_change.search(b_line):
                        klipper_block.append(append_retract_param(b_line, ret_sav))
                    else:
                        klipper_block.append(b_line)
                insertions[c["cut_index"]].extend(klipper_block)

            for k in range(c["origin"], c["end_move"] + 1):
                line_to_erase.add(k)
                
            total_saving_early_cut += ec_sav
            total_saving_retract += ret_sav
            total_saving += c["saving"]
            optimized_changes += 1
            
            tag = c.get("status_tag", "[SUCCESS]")
            print(f"{tag} Layer {c['layer']} | Cut Line {c['cut_index']} | Flush: {c['total_purge_mm']:.2f}mm ({c['flush_vol']:.0f}mm3) | EarlyCut: {ec_sav:.2f}mm | PreCutRet: {ret_sav:.2f}mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")
        
        elif ret_sav > 0.0:
            # --- RETRACT-ONLY OPTIMIZATION (Early-Cut omitted, Pre-Cut Retract active) ---
            if is_bambu_lab:
                insertions[c["origin"]].extend([
                    f"; ChromaSave Bambu Experimental Pre-Cut Retraction (-{ret_sav:.2f} mm)\n",
                    f"G1 E-{ret_sav:.2f} F1800\n",
                    "M400\n"
                ])

            elif is_sparkx_i7:
                for k in range(c["origin"], c["end_move"] + 1):
                    s_line = lines[k].strip()
                    if re_sparkx_cut.search(s_line):
                        insertions[k].extend([
                            f"; ChromaSave SPARKX i7 Native Pre-Cut Retraction (-{ret_sav:.2f} mm)\n",
                            f"M8200 R E-{ret_sav:.2f}\n",
                            "M400\n"
                        ])
                    elif re_sparkx_load.search(s_line):
                        insertions[k + 1].extend([
                            f"; ChromaSave SPARKX i7 Native Post-Load Recovery (+{ret_sav:.2f} mm)\n",
                            f"G1 E{ret_sav:.2f} F349\n"
                        ])

            elif is_k2_cfs:
                pass  # Handled atomically in PURGE MANAGEMENT alongside SMARTPURGE_K2_FLUSH

            else:
                replacement[c["origin"]] = append_retract_param(lines[c["origin"]], ret_sav)

            total_saving_retract += ret_sav
            total_saving += c["saving"]
            optimized_changes += 1

            tag = c.get("status_tag", "[RETRACT_ONLY]")
            print(f"{tag} Layer {c['layer']} | Orig Line {c['origin']} | Flush: {c['total_purge_mm']:.2f}mm ({c['flush_vol']:.0f}mm3) | EarlyCut: 0.00mm | PreCutRet: {ret_sav:.2f}mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")
        
        else:
            tag = c.get("status_tag", "[OMITTED]")
            if "MIN_SAVING" in tag:
                omitted_min_saving += 1
            elif "LONG_RETRACT" in tag:
                omitted_long_retract += 1
            else:
                omitted_no_saving += 1
            print(f"{tag} Layer {c['layer']} | Orig Line {c['origin']} | Flush: {c['total_purge_mm']:.2f}mm ({c['flush_vol']:.0f}mm3) | EarlyCut: 0.00mm | PreCutRet: 0.00mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")

        # --- PURGE MANAGEMENT ---
        p_start = c.get("idx_purge_start", -1)
        p_end = c.get("idx_purge_end", -1)

        skip_native_purge = (
            is_native_gcode_tc
            and c.get("status_tag") in ("[OMITTED: LONG_RETRACT]", "[OMITTED: INIT]")
        )

        if p_start != -1 and not skip_native_purge:
            curr_t_idx = c.get("t_idx", 0)
            prev_t_idx = c.get("prev_t_idx", curr_t_idx)
            
            curr_type = config.types[curr_t_idx] if hasattr(config, 'types') and curr_t_idx < len(config.types) else "UNK"
            curr_color = hex_to_color_name(config.colors[curr_t_idx] if hasattr(config, 'colors') and curr_t_idx < len(config.colors) else "#000")
            
            prev_type = config.types[prev_t_idx] if hasattr(config, 'types') and prev_t_idx < len(config.types) else "UNK"
            prev_color = hex_to_color_name(config.colors[prev_t_idx] if hasattr(config, 'colors') and prev_t_idx < len(config.colors) else "#000")

            flush_val = c.get("flush_vol", 0.0)
            ret_info = f" | PreCutRet: {ret_sav:.2f} mm" if ret_sav > 0.0 else ""

            obs_text = f"Active: T{curr_t_idx} [{curr_type} {curr_color}] (Purging T{prev_t_idx} [{prev_type} {prev_color}] {c['calculate_quantity']:.2f} mm) | Matrix: {flush_val:.1f} mm3 ({flush_val/area:.2f} mm) | Tower: {c['tower_e_mm']:.1f} mm{ret_info}"

            if is_bambu_lab:
                flush_header_cmds = []
                first_flush_end = p_end
                for k in range(p_start + 1, p_end + 1):
                    s_line = lines[k].strip()
                    if re_flush_end.search(lines[k]):
                        first_flush_end = k
                        break
                    if s_line.startswith(("M1002 ", "M109 ", "M106 ", "M400")):
                        flush_header_cmds.append(lines[k])

                wipe_between_cmds = []
                if first_flush_end < p_end:
                    for k in range(first_flush_end + 1, p_end + 1):
                        if re_flush_start.search(lines[k]):
                            break
                        if lines[k].lstrip().startswith("M73"):
                            continue
                        wipe_between_cmds.append(lines[k])

                if not wipe_between_cmds and c.get("wiper_x") is not None:
                    wx = c["wiper_x"]
                    wipe_between_cmds = [
                        "; ChromaSave Inter-Flush Wipe\n",
                        "M400\n",
                        "G92 E0\n",
                        "G1 E-2 F1800\n",
                        "M400\n",
                        "M106 P1 S178\n",
                        "M400 S3\n",
                        f"G1 X{wx + 10.0:.1f} F18000\n",
                        f"G1 X{wx:.1f} F3000\n",
                        f"G1 X{wx + 10.0:.1f} F18000\n",
                        f"G1 X{wx:.1f} F3000\n",
                        "M400\n",
                        "M106 P1 S60\n",
                        "G1 E2 F300\n"
                    ]

                for k in range(p_start, p_end + 1):
                    line_to_erase.add(k)

                net_purge = c['calculate_quantity']
                header_str = "".join(flush_header_cmds)

                bambu_recovery_str = ""
                if ret_sav > 0.0 and not (c.get("cut_index") < c["origin"] and ec_sav >= MIN_SAVING_THRESHOLD):
                    bambu_recovery_str = (
                        f"; ChromaSave Bambu Experimental Post-Load Recovery (+{ret_sav:.2f} mm)\n"
                        f"G1 E{ret_sav:.2f} F300\n"
                        f"M400\n"
                    )

                if net_purge < SKIP_PURGE_THRESHOLD:
                    replacement[p_start] = (
                        f"; FLUSH_START\n"
                        f"; {obs_text}\n"
                        f"{header_str}"
                        f"{bambu_recovery_str}"
                        f"; ChromaSave SKIP PURGE ({net_purge:.2f}mm < {SKIP_PURGE_THRESHOLD}mm)\n"
                        f"G1 E0.5 F300\n"
                        f"; FLUSH_END\n"
                    )
                else:
                    MAX_FLUSH_CHUNK = 45.0
                    num_chunks = max(1, math.ceil(net_purge / MAX_FLUSH_CHUNK))
                    chunk_len = net_purge / num_chunks
                    wipe_str = "".join(wipe_between_cmds)

                    purge_blocks = []
                    for chunk_idx in range(num_chunks):
                        block_hdr = f"; {obs_text}\n{header_str}{bambu_recovery_str}" if chunk_idx == 0 else ""
                        purge_blocks.append(
                            f"; FLUSH_START\n"
                            f"{block_hdr}"
                            f"; ChromaSave STATIC PURGE (Chunk {chunk_idx + 1}/{num_chunks})\n"
                            f"G1 E{chunk_len:.4f} F300\n"
                            f"; FLUSH_END\n"
                        )

                    replacement[p_start] = wipe_str.join(purge_blocks)

            elif is_sparkx_i7:
                for k in range(p_start, p_end + 1):
                    line_to_erase.add(k)

                net_purge = c["calculate_quantity"]
                target_temp = 0.0
                if c["layer"] <= 1 and curr_t_idx < len(nozzle_temps_init):
                    target_temp = nozzle_temps_init[curr_t_idx]
                elif curr_t_idx < len(nozzle_temps):
                    target_temp = nozzle_temps[curr_t_idx]

                temp_cmd = f"M104 S{target_temp:.0f}\n" if target_temp > 0 else ""

                if net_purge < SKIP_PURGE_THRESHOLD:
                    replacement[p_start] = (
                        f"; FLUSH_START\n"
                        f"; {obs_text}\n"
                        f"SET_VELOCITY_LIMIT ACCEL=5000 ACCEL_TO_DECEL=5000\n"
                        f"M106 S70\n"
                        f"{temp_cmd}"
                        f"M400\n"
                        f"; ChromaSave SPARKX i7 SKIP PURGE ({net_purge:.2f}mm < {SKIP_PURGE_THRESHOLD}mm)\n"
                        f"G1 E0.5 F349\n"
                        f"M400\n"
                        f"M106 S255\n"
                        f"G4 P2500\n"
                        f"M106 S30\n"
                        f"G1 E-2 F1800\n"
                        f"; FLUSH_END\n"
                    )
                else:
                    MAX_FLUSH_CHUNK = 45.0
                    num_chunks = max(1, math.ceil(net_purge / MAX_FLUSH_CHUNK))
                    chunk_len = net_purge / num_chunks
                    sparkx_wipe_str = (
                        "; WIPE\n"
                        "SET_VELOCITY_LIMIT ACCEL=10000 ACCEL_TO_DECEL=10000\n"
                        "G0 X267 F24000\n"
                        "G0 X278 F2400\n"
                        "G0 X267 F24000\n"
                        "G0 X278 F2400\n"
                    )
                    purge_blocks = []
                    for chunk_idx in range(num_chunks):
                        block_obs = f"; {obs_text}\n" if chunk_idx == 0 else ""
                        block_temp = temp_cmd if chunk_idx == (num_chunks - 1) else ""
                        purge_blocks.append(
                            f"; FLUSH_START\n"
                            f"{block_obs}"
                            f"SET_VELOCITY_LIMIT ACCEL=5000 ACCEL_TO_DECEL=5000\n"
                            f"M106 S70\n"
                            f"{block_temp}"
                            f"M400\n"
                            f"; ChromaSave SPARKX i7 PURGE (Chunk {chunk_idx + 1}/{num_chunks})\n"
                            f"G1 E{chunk_len:.4f} F349\n"
                            f"M400\n"
                            f"M106 S255\n"
                            f"G4 P2500\n"
                            f"M106 S30\n"
                            f"G1 E-2 F1800\n"
                            f"; FLUSH_END\n"
                        )
                    replacement[p_start] = sparkx_wipe_str.join(purge_blocks)

            elif is_k2_cfs:
                net_purge = c["calculate_quantity"]
                target_temp = 0.0
                if c["layer"] <= 1 and curr_t_idx < len(nozzle_temps_init):
                    target_temp = nozzle_temps_init[curr_t_idx]
                elif curr_t_idx < len(nozzle_temps):
                    target_temp = nozzle_temps[curr_t_idx]

                temp_param = f" TEMP={target_temp:.0f}" if target_temp > 0 else ""
                k2_lines = []

                if not did_early_cut:
                    ret_param = f" RETRACT_BEFORE_CUT={ret_sav:.2f}" if ret_sav > 0.0 else ""
                    k2_lines.append("; --- ChromaSave K2 CFS Toolchange (No Early-Cut) ---\n")
                    k2_lines.append(f"SMARTPURGE_K2_CUT NEXT_EXTRUDER={curr_t_idx}{ret_param}\n")

                k2_lines.append("; --- ChromaSave K2 CFS Dynamic Flush ---\n")
                k2_lines.append(
                    f"SMARTPURGE_K2_FLUSH QUANTITY={net_purge:.4f}{temp_param} "
                    f"SKIP_THRESHOLD={SKIP_PURGE_THRESHOLD} OBS=\"{obs_text}\"\n"
                )
                k2_lines.append("; ---------------------------------------\n")
                replacement[p_start] = "".join(k2_lines)

            else:
                match_indent = re.match(r"^(\s*)", lines[p_start])
                indent = match_indent.group(1) if match_indent else ""

                replacement[p_start] = f"{indent}PURGE_IN_TRASH QUANTITY={c['calculate_quantity']:.4f} SKIP_THRESHOLD={SKIP_PURGE_THRESHOLD} OBS=\"{obs_text}\" MATERIAL=\"{prev_type}\"\n"

    new_lines = []
    for i in range(total_lines):
        if i in insertions:
            new_lines.extend(insertions[i])
        if i in replacement:
            new_lines.append(replacement[i])
        elif i not in line_to_erase:
            new_lines.append(lines[i])
            
    # KPIs, Real Impact, and Breakdown by Filament
    total_theoretical_waste_vol_mm3 = 0.0
    theoretical_waste_g = 0.0
    weight_saved_early_cut_g = 0.0
    weight_saved_retract_g = 0.0
    remaining_weight_g = 0.0
    target_weight_g = 0.0
    tool_real_waste_g = {}
    
    real_changes_count = 0
    for idx_change, c in enumerate(changes):
        if c["layer"] < 0: continue
        real_changes_count += 1
        curr_t_idx = c.get("t_idx", 0)
        flush_vol_mm3 = c.get("flush_vol", 0.0)
        ec_sav = c.get("saving_early_cut", 0.0)
        ret_sav = c.get("saving_retract", 0.0)
        quantity_mm = c.get("calculate_quantity", 0.0)
        tower_e_mm = c.get("tower_e_mm", 0.0)
        
        dia = config.diams[curr_t_idx] if hasattr(config, 'diams') and curr_t_idx < len(config.diams) else getattr(config, 'dia', 1.75)
        den = config.densities[curr_t_idx] if hasattr(config, 'densities') and curr_t_idx < len(config.densities) else getattr(config, 'den', 1.04)
        
        area = math.pi * ((dia / 2.0) ** 2)
        remaining_vol_mm3 = REMAINING_LENGTH * area
        target_vol_mm3 = TARGET * area
        
        remaining_weight_g += (remaining_vol_mm3 / 1000.0) * den
        target_weight_g += (target_vol_mm3 / 1000.0) * den
        change_theoretical_vol = max(flush_vol_mm3, remaining_vol_mm3)
        total_theoretical_waste_vol_mm3 += change_theoretical_vol
        theoretical_waste_g += (change_theoretical_vol / 1000.0) * den

        weight_saved_early_cut_g += ((ec_sav * area) / 1000.0) * den
        weight_saved_retract_g += ((ret_sav * area) / 1000.0) * den
        
        t_waste_g = (((quantity_mm + tower_e_mm) * area) / 1000.0) * den
        tool_real_waste_g[curr_t_idx] = tool_real_waste_g.get(curr_t_idx, 0.0) + t_waste_g
        
    weight_saved_g = weight_saved_early_cut_g + weight_saved_retract_g

    # KPIs (Conciliated with actual physical waste in chute + tower)
    actual_waste_g = sum(tool_real_waste_g.values())
    oce = (optimized_changes / real_changes_count) * 100 if real_changes_count > 0 else 0.0
    ofe = (weight_saved_g / theoretical_waste_g) * 100 if theoretical_waste_g > 0 else 0.0
    hfe = (weight_saved_g / remaining_weight_g) * 100 if remaining_weight_g > 0 else 0.0
    cse = (weight_saved_g / target_weight_g) * 100 if target_weight_g > 0 else 0.0
    
    # EXACT PIECE WEIGHT CALCULATION
    tool_model_e_mm = {}
    curr_t = initial_tool_idx if initial_tool_idx is not None else (changes[0]["t_idx"] if changes else 0)
    
    tc_and_purge_lines = set()
    for c in changes:
        for k in range(c["origin"], c["end_move"] + 1):
            tc_and_purge_lines.add(k)
        if c["idx_purge_start"] != -1:
            for k in range(c["idx_purge_start"], c["idx_purge_end"] + 1):
                tc_and_purge_lines.add(k)
                
    change_origins = {c["origin"]: c["t_idx"] for c in changes}
    
    for i in range(total_lines):
        if i in change_origins:
            curr_t = change_origins[i]
        if i in tc_and_purge_lines:
            continue
        t_type = line_types[i]
        if "Prime tower" in t_type or "Wipe tower" in t_type or "Toolchange" in t_type or "Custom" in t_type:
            continue
        if line_extrusions[i] > 0:
            tool_model_e_mm[curr_t] = tool_model_e_mm.get(curr_t, 0.0) + line_extrusions[i]
            
    filament_report_lines = []
    total_job_weight_g = 0.0
    total_piece_weight_g = 0.0
    max_tool = max(list(tool_real_waste_g.keys()) + list(tool_model_e_mm.keys()) + [0])

    for t in range(max_tool + 1):
        dia = config.diams[t] if hasattr(config, 'diams') and t < len(config.diams) else getattr(config, 'dia', 1.75)
        den = config.densities[t] if hasattr(config, 'densities') and t < len(config.densities) else getattr(config, 'den', 1.04)
        area_t = math.pi * ((dia / 2.0) ** 2)
        
        model_g = ((tool_model_e_mm.get(t, 0.0) * area_t) / 1000.0) * den
        waste_g = tool_real_waste_g.get(t, 0.0)
        total_g = model_g + waste_g
        
        if total_g > 0:
            t_type = config.types[t] if hasattr(config, 'types') and t < len(config.types) else "UNK"
            t_color = hex_to_color_name(config.colors[t] if hasattr(config, 'colors') and t < len(config.colors) else "#000")
            total_piece_weight_g += model_g
            total_job_weight_g += total_g
            filament_report_lines.append(
                f"   - T{t} [{t_type} {t_color}]: Piece= {model_g:.2f}g | Purge Waste= {waste_g:.2f}g | TOTAL= {total_g:.2f}g"
            )
                  
    new_filepath = config.filepath.replace('.gcode', '_ChromaSave.gcode')
    
    # REPORTS AND LOGS
    current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gcode_file_name = os.path.basename(config.filepath)
    
    total_omitted = omitted_min_saving + omitted_no_saving + omitted_long_retract

    if ENABLE_PRE_CUT_RETRACT:
        if is_bambu_lab:
            pre_cut_status = f"EXPERIMENTAL (Max {MAX_PRE_CUT_RETRACT:.1f} mm)"
        elif is_sparkx_i7:
            pre_cut_status = f"ENABLED (Native M8200 R, Max {MAX_PRE_CUT_RETRACT:.1f} mm)"
        elif is_k2_cfs:
            pre_cut_status = f"ENABLED (SmartPurge_K2, Max {MAX_PRE_CUT_RETRACT:.1f} mm)"
        else:
            pre_cut_status = f"ENABLED (Max {MAX_PRE_CUT_RETRACT:.1f} mm)"
    else:
        pre_cut_status = "DISABLED"

    log_content = (
        f"[{current_date}] Gcode File: {gcode_file_name}\n"
        f"Changes: {real_changes_count} | Optimized: {optimized_changes} | Omitted: {total_omitted} (<MinSav: {omitted_min_saving}, LongRetract: {omitted_long_retract}, Zero: {omitted_no_saving}) | OCE: {oce:.2f}% | "
        f"Baseline Waste: {theoretical_waste_g:.2f} g | "
        f"Real Waste: {actual_waste_g:.2f} g | "
        f"Saved Total: {weight_saved_g:.2f} g (EarlyCut: {weight_saved_early_cut_g:.2f} g, PreCutRet: {weight_saved_retract_g:.2f} g) | OFE: {ofe:.2f}% | HFE: {hfe:.2f}% | CSE: {cse:.2f}%\n"
        + "-" * 90 + "\n"
    )
    
    if history_log_path:
        try:
            with open(history_log_path, "a", encoding="utf-8") as log_file:
                log_file.write(log_content)
        except Exception:
            history_log_path = None

    files_str = (
        f" File saved in:\n"
        f" {new_filepath if getattr(config, 'console', False) else config.filepath}"
    )
    if history_log_path and console_log_path:
        files_str += (
            f"\n History log saved in:\n"
            f" {history_log_path}\n"
            f" Console log saved in:\n"
            f" {console_log_path}"
        )

    warning_banner = ""
    if long_retract_warning:
        warning_banner = (
            " ----------------------------------------------------------------------------------\n"
            "  [WARNING] 'Long retraction when cut' is enabled in OrcaSlicer settings.\n"
            "            Early-Cut was omitted on affected changes. Disable it to use ChromaSave.\n"
        )
    
    report_str = (
        "\n"
        " ==================================================================================\n"
        f" GLOBAL REPORT (ChromaSave v{__version__})\n"
        " ==================================================================================\n"
        f"  Printer Profile Mode:                            {printer_mode.upper()}\n"
        f"  Purge Target Mode:                               {PURGE_TARGET.upper()}\n"
        f"  Dynamic Pre-Cut Retraction:                      {pre_cut_status}\n"
        f"{warning_banner}"
        " ----------------------------------------------------------------------------------\n"
        "     Color Changes\n"
        " ----------------------------------------------------------------------------------\n"
        f"       Total Changes:                                  {real_changes_count}\n"
        f"       Optimized Changes:                              {optimized_changes}\n"
        f"       Omitted (<{MIN_SAVING_THRESHOLD:.1f}mm: {omitted_min_saving} | LongRet: {omitted_long_retract} | Zero: {omitted_no_saving}):   {total_omitted}\n"
        f"       Overall Changes Efficiency:                     {oce:.2f} %\n"
        " ----------------------------------------------------------------------------------\n"
        "     Filament Efficiency\n"
        " ----------------------------------------------------------------------------------\n"
        f"       Remaining Weight:                               {remaining_weight_g:.2f} grams\n"
        f"       Target Weight:                                  {target_weight_g:.2f} grams\n"
        f"       Slicer Baseline Waste (No Script):              {theoretical_waste_g:.2f} grams\n"
        f"       Real Waste (With ChromaSave-SmartPurge):        {actual_waste_g:.2f} grams\n"
        f"       Saved by Early-Cut:                             {weight_saved_early_cut_g:.2f} grams\n"
        f"       Saved by Pre-Cut Retraction:                    {weight_saved_retract_g:.2f} grams\n"
        f"    TOTAL PURGE SAVED:                                 {weight_saved_g:.2f} grams\n"
        "   --------------------------------------------------------------------------------\n"
        f"       Overall Filament Efficiency - OFE:              {ofe:.2f} %\n"
        f"       Hotend Filament Efficiency - HFE:               {hfe:.2f} %\n"
        f"       ChromaSave-SmartPurge Efficiency - CSE:         {cse:.2f} %\n"
        " ----------------------------------------------------------------------------------\n"
        "   TOTAL FILAMENT CONSUMPTION BREAKDOWN:\n"
        + "\n".join(filament_report_lines) + "\n"
        " ----------------------------------------------------------------------------------\n"
        f"  TOTAL PIECE WEIGHT:                              {total_piece_weight_g:.2f} grams\n"
        f"  TOTAL SPOOL CONSUMPTION:                         {total_job_weight_g:.2f} grams\n"
        " ==================================================================================\n"    
    )

    report_orca = (
            f"GLOBAL REPORT (ChromaSave v{__version__})\n"
            f"Printer Profile Mode:         {printer_mode.upper()}\n"
            f"Purge Target Mode:            {PURGE_TARGET.upper()}\n"
            f"Dynamic Pre-Cut Retraction:   {pre_cut_status}\n"
            + ("WARNING: Disable 'Long retraction when cut' in printer/filament settings for Early-Cut.\n" if long_retract_warning else "")
            + "Color Changes\n"
            f" Total Changes:               {real_changes_count}\n"
            f" Optimized Changes:           {optimized_changes}\n"
            f" Omitted (<{MIN_SAVING_THRESHOLD:.1f}mm: {omitted_min_saving} | LongRet: {omitted_long_retract} | Zero: {omitted_no_saving}): {total_omitted}\n"
            f" Overall Changes Efficiency:  {oce:.2f} %\n"
            "Filament Efficiency\n"
            f" Remaining Weight:            {remaining_weight_g:.2f} grams\n"
            f" Target Weight:               {target_weight_g:.2f} grams\n"
            f" Slicer Baseline Waste (No Script):  {theoretical_waste_g:.2f} grams\n"
            f" Real Waste (With ChromaSave-SmartPurge):    {actual_waste_g:.2f} grams\n"
            f" Saved by Early-Cut:          {weight_saved_early_cut_g:.2f} grams\n"
            f" Saved by Pre-Cut Retraction: {weight_saved_retract_g:.2f} grams\n"
            f"TOTAL PURGE SAVED:            {weight_saved_g:.2f} grams\n"
            f" Overall Filament Efficiency - OFE:      {ofe:.2f} %\n"
            f" Hotend Filament Efficiency - HFE:       {hfe:.2f} %\n"
            f" ChromaSave-SmartPurge Efficiency - CSE: {cse:.2f} %\n"
            "TOTAL FILAMENT CONSUMPTION BREAKDOWN:\n"
            + "\n".join(filament_report_lines) + "\n"
            f"TOTAL PIECE WEIGHT:           {total_piece_weight_g:.2f} grams\n"
            f"TOTAL SPOOL CONSUMPTION:      {total_job_weight_g:.2f} grams\n"    
        )
    
    report_str = "".join([report_str, files_str])
    print(report_str)
    
    commented_report = "\n" + "\n".join(f"; {r_line}" if r_line.strip() else ";" for r_line in report_str.splitlines()) + "\n"
    new_lines.append(commented_report)
    
    return {
        "new_filepath": new_filepath,
        "oce": oce,
        "ofe": ofe,
        "hfe": hfe,
        "cse": cse,
        "weight_saved_early_cut_g": weight_saved_early_cut_g,
        "weight_saved_retract_g": weight_saved_retract_g,
        "weight_saved_g": weight_saved_g,
        "total_saving_early_cut": total_saving_early_cut,
        "total_saving_retract": total_saving_retract,
        "total_saving": total_saving,
        "optimized_changes": optimized_changes,
        "total_changes": real_changes_count,
        "new_lines": new_lines,
        "report_cli": report_str,
        "report_str": report_str.replace("; ", ""),
        "report_orca": report_orca.replace("; ", "")
    }