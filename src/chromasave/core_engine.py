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

def filament_change_optimizer(config):
    try:
        with open(config.filepath, 'r', encoding='utf-8') as file:
            lines = file.readlines()
    except FileNotFoundError:
        print(f"Post-Processing Error: The file dosen't exist in the path {config.filepath}", file=sys.stderr)
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
    TARGET = REMAINING_LENGTH - SAFETY_MARGIN
    
    SEARCH_RETRACTIONS = getattr(config, 'sre', True)
    RETRACTION_MARGIN = getattr(config, 'rem', 5.0)
    AVOID_IN_PIECE_CUT = getattr(config, 'aipc', True)
    PURGE_TARGET = getattr(config, 'purge_target', 'hybrid').strip().lower()
    MIN_SAVING_THRESHOLD = getattr(config, 'min_saving', 3.0)
    
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
    re_purge = re.compile(r"^\s*PURGE_IN_TRASH")
    re_type = re.compile(r"^;\s*(?:TYPE|FEATURE|_EXTRUSION_ROLE):\s*(.+)", re.IGNORECASE)
    re_wipe_start = re.compile(r"^;\s*(?:CP TOOLCHANGE WIPE|WIPE_TOWER_START)", re.IGNORECASE)
    re_wipe_end = re.compile(r"^;\s*(?:CP TOOLCHANGE END|WIPE_TOWER_END)", re.IGNORECASE)
    re_e_reset = re.compile(r"E(-?[0-9]*\.?[0-9]+)")
    
    re_fmatrix = re.compile(r"^\s*; flush_volumes_matrix = (.+)")
    re_gmultiplier = re.compile(r"^\s*; flush_multiplier = (.+)")
    re_gdiams = re.compile(r"^\s*; filament_diameter = (.+)")
    re_gdens = re.compile(r"^\s*; filament_density = (.+)")
    re_gcolor = re.compile(r"^\s*; filament_colour = (.+)")
    re_gtype = re.compile(r"^\s*; filament_type = (.+)")
    re_gmin_purge = re.compile(r"^\s*; filament_minimal_purge_on_wipe_tower = (.+)")
    re_gprime_volume = re.compile(r"^\s*; prime_volume = (.+)")
    
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
    
    current_x, current_y, current_z, current_f = 0.0, 0.0, 0.0, 0.0
    is_bambu_lab = False
    initial_tool_idx = None
    first_tc_seen = False

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
                elif "; CHANGE_LAYER" in line and not saw_explicit_layer:
                    current_layer += 1
        line_layers[i] = current_layer
        
        # Topology Tracking: In Bambu Lab, all the events that occur after FLUSH_END or CP TOOLCHANGE WIPE
        # until another FEATURE of the piece begins is considered a Prime tower (allows Early-Cut and exact counting)
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

        if line.startswith("M620 S"):
            is_bambu_lab = True

        # Capture initial tool loaded in Start G-code before the first change
        if not first_tc_seen:
            if "; CP TOOLCHANGE START" in line or line.startswith("FILAMENT_CHANGE"):
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
        
        if mx: current_x = float(mx.group(1))
        if my: current_y = float(my.group(1))
        if mz: current_z = float(mz.group(1))
        if mf: current_f = float(mf.group(1))
        
        state_x[i] = current_x
        state_y[i] = current_y
        state_z[i] = current_z
        state_f[i] = current_f
                
        # API Fallback
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
            
        if "M82" in line:
            is_absolute_e = True
        elif "M83" in line:
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
    
    # IDENTIFYING BLOCKS AND TOOLS 
    changes = []
    i = 0
    while i < total_lines:
        line = lines[i]
        
        match_klipper = re_filament_change.search(line) if not is_bambu_lab else None
        match_bambu = re_bambu_tc_start.search(line) if is_bambu_lab else None
        
        if match_klipper or match_bambu:
            origin = i
            end_move = i
            layer_num = int(match_klipper.group(1)) if match_klipper else line_layers[i]
            
            t_idx = 0
            current_tool = "T?"
            
            tc_block_end = i
            wipe_sub_start = -1
            search_limit = min(i + 400, total_lines)
            for j in range(i, search_limit):
                match_tool = re_tool.search(lines[j])
                if match_tool:
                    current_tool = match_tool.group(1)
                    if current_tool[1:].isdigit():
                        t_idx = int(current_tool[1:])
                elif is_bambu_lab:
                    m_bt = re_bambu_tool.search(lines[j])
                    if m_bt and int(m_bt.group(1)) != 255:
                        t_idx = int(m_bt.group(1))
                        current_tool = f"T{t_idx}"
                
                if is_bambu_lab:
                    if "; CP TOOLCHANGE WIPE" in lines[j] and wipe_sub_start == -1:
                        wipe_sub_start = j
                    if re_bambu_tc_end.search(lines[j]):
                        tc_block_end = j
                        break
                elif not is_bambu_lab and match_tool:
                    tc_block_end = j
                    break
            
            # Capture ALL purge pulses (from the FIRST FLUSH_START to the LAST FLUSH_END)
            idx_purge_start = -1
            idx_purge_end = -1
            if is_bambu_lab:
                for j in range(origin, min(tc_block_end + 50, total_lines)):
                    if "; CP TOOLCHANGE WIPE" in lines[j]:
                        break
                    if re_flush_start.search(lines[j]):
                        if idx_purge_start == -1:
                            idx_purge_start = j
                    elif re_flush_end.search(lines[j]):
                        idx_purge_end = j
                # In Bambu Lab, the tool change/cut block ends right before FLUSH_START or WIPE
                if idx_purge_start != -1:
                    end_move = idx_purge_start - 1
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

            changes.append({
                "layer": layer_num,
                "origin": origin,
                "end_move": end_move,
                "tc_block_end": tc_block_end,
                "wipe_sub_start": wipe_sub_start,
                "idx_purge_start": idx_purge_start,
                "idx_purge_end": idx_purge_end,
                "tool": current_tool,
                "t_idx": t_idx,
                "tower_e_mm": 0.0
            })
            
            i = max(tc_block_end, idx_purge_end)
            
        i += 1

    # EXACT TOWER CALCULATION (Only sums extrusions in the tower within the bed, excluding the chute)
    for idx_change, c in enumerate(changes):
        if is_bambu_lab:
            # Start searching always after the last FLUSH_END (to capture both CP TOOLCHANGE WIPE and the outer fill)
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
                if is_bambu_lab:
                    # Geometric filter: ignore any residual extrusion in the chute coordinate
                    if abs(state_x[j] - chute_x) < 1.0 and abs(state_y[j] - chute_y) < 1.0:
                        continue
                    if state_x[j] < 0.0 or state_x[j] > 256.0 or state_y[j] < 0.0 or state_y[j] > 256.0:
                        continue
                tower_e_mm += line_extrusions[j]
                
        c["tower_e_mm"] = tower_e_mm
        
    # BACKTRACKING WITH CHRONOLOGICAL PROTECTION
    for idx_change, c in enumerate(changes):
        if idx_change < 1:
            candidate_index = c["origin"]
            candidate_saving = 0.0
            c["break_flag"] = "Blocked by initialization (0.00 mm)"
            c["status_tag"] = "[OMITTED: INIT]"
        else:
            e_acumulated = 0.0
            candidate_index = c["origin"]
            candidate_saving = 0.0
            break_flag = "Unknown"
            
            lower_limit = 0
            previous_change = changes[idx_change - 1]
            if is_bambu_lab:
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
                    
                if line.startswith(("M620", "M621", "M622", "M628", "M629", "M1002", "M1004", "M1006", "M1007", "M971")):
                    continue
                    
                if line.startswith(("G1", "G0")) and "X" in line:
                    mx = re_coord_x.search(line)
                    if mx and (float(mx.group(1)) > 256.0 or float(mx.group(1)) < 0.0):
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
                    
                # Only register candidate if there is already accumulated real extrusion (> 0.0 mm)
                if is_safe_zone and e_acumulated > 0.0:
                    candidate_index = idx
                    candidate_saving = e_acumulated
                    
                    if SEARCH_RETRACTIONS and (("G1" in line and "E-" in line) or "G10" in line) and re_retraction.search(line):
                        
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
                    if is_bambu_lab and "; CP TOOLCHANGE WIPE" in lines[r_start] and SAFETY_ZONES.get("Prime tower", True):
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
                recalc_saving = sum(line_extrusions[i] for i in range(c["origin"] - 1, candidate_index - 1, -1))
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
            
        # PHYSICOCHEMICAL MODEL INTEGRATED FOR ORCASLICER
        curr_t_idx = c.get("t_idx", 0)
        fallback_prev = initial_tool_idx if initial_tool_idx is not None else curr_t_idx
        prev_t_idx = changes[idx_change - 1].get("t_idx", 0) if idx_change > 0 else fallback_prev
        
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
        
        target_flush_mm = (flush_vol_mm3 / area) if area > 0 else 0.0
        total_purge_needed_mm = max(target_flush_mm, REMAINING_LENGTH)
        c["total_purge_mm"] = total_purge_needed_mm
        
        # HYBRID VS BUCKET_ONLY LOGIC FOR ORCASLICER
        if PURGE_TARGET == "hybrid":
            remaining_purge_mm = total_purge_needed_mm - c["tower_e_mm"] - candidate_saving
            calculate_quantity = max(0.0, remaining_purge_mm)
        else: 
            calculate_quantity = max(0.0, total_purge_needed_mm - candidate_saving)
        
        c["cut_index"] = candidate_index
        c["saving"] = candidate_saving
        c["calculate_quantity"] = calculate_quantity
        
    # CONSTRUCTION AND LABELING OF THE NEW G-CODE
    insertions = { i: [] for i in range(len(lines) + 1) }
    line_to_erase = set()
    replacement = {}
    
    total_saving = 0.0
    optimized_changes = 0
    omitted_min_saving = 0
    omitted_no_saving = 0

    SKIP_PURGE_THRESHOLD = getattr(config, 'skip_purge', 2.0)
    
    for idx_change, c in enumerate(changes):
        if c["layer"] < 0: continue

        if c.get("cut_index") < c["origin"] and c.get("saving", 0.0) >= MIN_SAVING_THRESHOLD:
            # --- TOOLCHANGE MANAGEMENT (Early-Cut) ---
            block = lines[c["origin"] : c["end_move"] + 1]

            if is_bambu_lab:
                cut_x = state_x[c["cut_index"]]
                cut_y = state_y[c["cut_index"]]
                cut_z = state_z[c["cut_index"]]
                cut_f = state_f[c["cut_index"]]
                t_num = c.get("t_idx", 0)
                safe_z = cut_z + 3.0
                
                # 1. In cut_index: Execute filament change and close temporary state to print the remainder
                insertions[c["cut_index"]].extend([
                    "; --- ChromaSave Bambu Early-Cut ---\n",
                    f"G1 Z{safe_z:.3f} F1200\n"
                ])
                insertions[c["cut_index"]].extend(block)
                insertions[c["cut_index"]].extend([
                    f"M621 S{t_num}A\n",
                    "M220 R\n",
                    "; --- ChromaSave Return Travel ---\n",
                    f"G1 Z{safe_z:.3f} F1200\n",
                    f"G1 X{cut_x:.3f} Y{cut_y:.3f} F21000\n",
                    f"G1 Z{cut_z:.3f} F1200\n",
                    f"G1 F{cut_f:.1f}\n",
                    "G92 E0\n",
                    "; --------------------------------\n"
                ])
                
                # 2. In origin: Travel safely to the chute and reopen M620 to purge and clean the nozzle
                insertions[c["origin"]].extend([
                    "; --- ChromaSave Chute Re-route ---\n",
                    f"G1 Z{safe_z:.3f} F1200\n",
                    "G1 X267 Y128 F18000\n",
                    f"M620 S{t_num}A\n",
                    "G92 E0\n",
                    "; ---------------------------------\n"
                ])
                
            else:
                insertions[c["cut_index"]].extend(block)

            for k in range(c["origin"], c["end_move"] + 1):
                line_to_erase.add(k)
                
            total_saving += c["saving"]
            optimized_changes += 1
            
            tag = c.get("status_tag", "[SUCCESS]")
            print(f"{tag} Layer {c['layer']} | Cut Line {c['cut_index']} | Flush: {c['total_purge_mm']:.2f}mm ({c['flush_vol']:.0f}mm3) | Sav: {c['saving']:.2f}mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")
        
        else:
            tag = c.get("status_tag", "[OMITTED]")
            if "MIN_SAVING" in tag:
                omitted_min_saving += 1
            else:
                omitted_no_saving += 1
            print(f"{tag} Layer {c['layer']} | Orig Line {c['origin']} | Flush: {c['total_purge_mm']:.2f}mm ({c['flush_vol']:.0f}mm3) | Sav: 0.00mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")

        # --- PUERGE MANAGEMENT ---
        p_start = c.get("idx_purge_start", -1)
        p_end = c.get("idx_purge_end", -1)

        if p_start != -1:

            curr_t_idx = c.get("t_idx", 0)
            fallback_prev = initial_tool_idx if initial_tool_idx is not None else curr_t_idx
            prev_t_idx = changes[idx_change - 1].get("t_idx", 0) if idx_change > 0 else fallback_prev
            
            curr_type = config.types[curr_t_idx] if hasattr(config, 'types') and curr_t_idx < len(config.types) else "UNK"
            curr_color = hex_to_color_name(config.colors[curr_t_idx] if hasattr(config, 'colors') and curr_t_idx < len(config.colors) else "#000")
            
            prev_type = config.types[prev_t_idx] if hasattr(config, 'types') and prev_t_idx < len(config.types) else "UNK"
            prev_color = hex_to_color_name(config.colors[prev_t_idx] if hasattr(config, 'colors') and prev_t_idx < len(config.colors) else "#000")

            flush_val = c.get("flush_vol", 0.0)

            obs_text = f"Active: T{curr_t_idx} [{curr_type} {curr_color}] (Purging T{prev_t_idx} [{prev_type} {prev_color}] {c['calculate_quantity']:.2f} mm) | Matrix: {flush_val:.1f} mm3 ({flush_val/area:.2f} mm) | Tower: {c['tower_e_mm']:.1f} mm"

            if is_bambu_lab:
                for k in range(p_start, p_end + 1):
                    line_to_erase.add(k)
                    
                net_purge = c['calculate_quantity']
                if net_purge < SKIP_PURGE_THRESHOLD:
                    replacement[p_start] = f"; FLUSH_START\n; {obs_text}\n; ChromaSave SKIP PURGE ({net_purge:.2f}mm < {SKIP_PURGE_THRESHOLD}mm)\nG1 E0.5 F300\n; FLUSH_END\n"
                else:
                    replacement[p_start] = f"; FLUSH_START\n; {obs_text}\n; ChromaSave STATIC PURGE\nG1 E{net_purge:.4f} F300\n; FLUSH_END\n"
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
    weight_saved_g = 0.0
    remaining_weight_g = 0.0
    target_weight_g = 0.0
    tool_real_waste_g = {}
    
    for idx_change, c in enumerate(changes):
        if c["layer"] < 0: continue
        curr_t_idx = c.get("t_idx", 0)
        flush_vol_mm3 = c.get("flush_vol", 0.0)
        saving = c.get("saving", 0.0)
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
        weight_saved_g += ((saving * area) / 1000.0) * den
        
        t_waste_g = (((quantity_mm + tower_e_mm) * area) / 1000.0) * den
        tool_real_waste_g[curr_t_idx] = tool_real_waste_g.get(curr_t_idx, 0.0) + t_waste_g
        
    # KPI's
    actual_waste_g = max(0.0, theoretical_waste_g - weight_saved_g)
    oce = (optimized_changes / len(changes)) * 100 if len(changes) > 0 else 0.0
    ofe = (weight_saved_g / theoretical_waste_g) * 100 if theoretical_waste_g > 0 else 0.0
    hfe = (weight_saved_g / remaining_weight_g) * 100 if remaining_weight_g > 0 else 0.0
    cse = (weight_saved_g / target_weight_g) * 100 if target_weight_g > 0 else 0.0
    
    # EXACT PIECE WEIGHT CALCULATION (Without double counting of Flushed or Tower)
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
    file_dir = os.path.dirname(config.filepath)
    log_dir = os.path.join(file_dir, "chromasave_history.log")
    
    total_omitted = omitted_min_saving + omitted_no_saving
    
    log_content = (
        f"[{current_date}] Gcode File: {gcode_file_name}\n"
        f"Changes: {len(changes)} | Optimized: {optimized_changes} | Omitted: {total_omitted} (<MinSav: {omitted_min_saving}, Zero: {omitted_no_saving}) | OCE: {oce:.2f}% | "
        f"Baseline Waste: {theoretical_waste_g:.2f} g | "
        f"Real Waste: {actual_waste_g:.2f} g | "
        f"Saved: {weight_saved_g:.2f} g | OFE: {ofe:.2f}% | HFE: {hfe:.2f}% | CSE: {cse:.2f}%\n"
        + "-" * 90 + "\n"
    )
    
    try:
        with open(log_dir, "a", encoding="utf-8") as log_file:
            log_file.write(log_content)
    except Exception as e:
        print(f"Alert: The log file could not be written. ({e})")
          
    files_str = (
        f" File saved in:\n"
        f" {new_filepath if getattr(config, 'console', False) else config.filepath}\n"
        f" Log saved in:\n"
        f" {log_dir}"
    )
    
    report_str = (
        "\n"
        " ==================================================================================\n"
        " GLOBAL REPORT (ChromaSave v1.1.0-beta)\n"
        " ==================================================================================\n"
        f"  Purge Target Mode:                               {PURGE_TARGET.upper()}\n"
        " ----------------------------------------------------------------------------------\n"
        "     Color Changes\n"
        " ----------------------------------------------------------------------------------\n"
        f"       Total Changes:                                  {len(changes)}\n"
        f"       Optimized Changes:                              {optimized_changes}\n"
        f"       Omitted Changes (<{MIN_SAVING_THRESHOLD:.1f}mm: {omitted_min_saving} | Zero/Init: {omitted_no_saving}):   {total_omitted}\n"
        f"       Overall Changes Efficiency:                     {oce:.2f} %\n"
        " ----------------------------------------------------------------------------------\n"
        "     Filament Efficiency\n"
        " ----------------------------------------------------------------------------------\n"
        f"       Remaining Weight:                               {remaining_weight_g:.2f} grams\n"
        f"       Target Weight:                                  {target_weight_g:.2f} grams\n"
        f"       Slicer Baseline Waste (No Script):              {theoretical_waste_g:.2f} grams\n"
        f"       Real Waste (With ChromaSave-SmartPurge):        {actual_waste_g:.2f} grams\n"
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
            " GLOBAL REPORT (ChromaSave v1.1.0)\n"
            f"Purge Target Mode:            {PURGE_TARGET.upper()}\n"
            "Color Changes\n"
            f" Total Changes:               {len(changes)}\n"
            f" Optimized Changes:           {optimized_changes}\n"
            f" Omitted Changes (<{MIN_SAVING_THRESHOLD:.1f}mm: {omitted_min_saving} | Zero: {omitted_no_saving}): {total_omitted}\n"
            f" Overall Changes Efficiency:  {oce:.2f} %\n"
            "Filament Efficiency\n"
            f" Remaining Weight:            {remaining_weight_g:.2f} grams\n"
            f" Target Weight:               {target_weight_g:.2f} grams\n"
            f" Slicer Baseline Waste (No Script):  {theoretical_waste_g:.2f} grams\n"
            f" Real Waste (With ChromaSave-SmartPurge):    {actual_waste_g:.2f} grams\n"
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
        "weight_saved_g": weight_saved_g,
        "total_saving": total_saving,
        "optimized_changes": optimized_changes,
        "total_changes": len(changes),
        "new_lines": new_lines,
        "report_cli": report_str,
        "report_str": report_str.replace("; ", ""),
        "report_orca": report_orca.replace("; ", "")
    }