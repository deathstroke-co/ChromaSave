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
            lines = file.readlines() # Reading the file and store the gcode lines.
    except FileNotFoundError:
        # OrcaSlicer Show the error on screen.
        print(f"Post-Processing Error: The file dosen't exist in the path {config.filepath}", file=sys.stderr)
        sys.exit(1) # Aborts the lamination process.
    
    except PermissionError:
        print(f"Post-Processing Error: No permission to open the file: {config.filepath}", file=sys.stderr)
        sys.exit(1) # Aborts the lamination process.
    
    except Exception as e:
        print(f"Unexpected Post-Processing Error: {e}", file=sys.stderr)
        sys.exit(1) # Aborts the lamination process.
    
    
    # CONSTANTS & PARAMETERS (Safe Extraction for both Plugin and Client)
    REMAINING_LENGTH = getattr(config, 'len', 64.857)
    SAFETY_MARGIN = getattr(config, 'sm', 10.0)
    TARGET = REMAINING_LENGTH - SAFETY_MARGIN
    
    SEARCH_RETRACTIONS = getattr(config, 'sre', True)
    RETRACTION_MARGIN = getattr(config, 'rem', 5.0)
    AVOID_IN_PIECE_CUT = getattr(config, 'aipc', True)
    PURGE_TARGET = getattr(config, 'purge_target', 'hybrid').strip().lower()
    
    SAFETY_ZONES = {
        # === Non-critical areas ===
        "Prime tower": True,            # Wipe Tower (Safe Waste)
        "Support": True,                # Standard Supports (Discarded)
        "Support interface": True,      # Support Interface (Discarded)
        "Sparse infill": True,          # Standard Internal Fill
        "Dense infill": True,           # ORCA: Dense Fill under Solid Layers (Hidden)
        
        # === Critical areas ===
        "Internal solid infill": True, # Avoids color transparency in sub-surface layers
        "Skirt": True,                 # Outline line (Protects initial pressure)
        "Brim": True,                  # Adhesion flap (Prevents the piece from detaching)
        "Gap fill": True,              # ORCA: Fill for small gaps between walls (Visible/Structural)
        "Outer wall": True,            # ORCA: Visible outer wall (Pure aesthetics)
        "Inner wall": True,            # ORCA: Internal walls (If cut here, it may bleed to the outside)
        "Overhang wall": True,         # ORCA: Overhang walls (Require perfect flow to prevent collapse)
        "Top surface": True,           # ORCA: Top surface of the piece
        "Bottom surface": True,        # ORCA: Bottom surface in contact with the bed
        "Internal bridge": True,       # ORCA: Internal bridges (Require constant filament tension)
        "Bridge": True,                # ORCA: External bridges (Visible)
        "Custom": True                 # ORCA: Custom G-code inserted by the user
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
    re_extrusion = re.compile(r"^G1\b.*?[XYxy].*?\b[Ee](([0-9]*\.?[0-9]+))")
    # re_retraction = re.compile(r"^G1\b.*?\b[Ee](-[0-9]*\.?[0-9]+)")
    re_retraction = re.compile(r"^(?:G1\b.*?\b[Ee](-[0-9]*\.?[0-9]+)|G10\b)")
    re_z_hop = re.compile(r"^G1\b.*?[Zz]([0-9]*\.?[0-9]+)")
    re_filament_change = re.compile(r"^FILAMENT_CHANGE LAYER_NUM=(-?\d+)")
    re_tool = re.compile(r"^(T\d+)")
    re_purge = re.compile(r"^\s*PURGE_IN_TRASH")
    re_type = re.compile(r"^;TYPE:(.+)")
    re_wipe_start = re.compile(r"^;(?: CP TOOLCHANGE WIPE|WIPE_TOWER_START|_EXTRUSION_ROLE:Wipe tower)")
    re_wipe_end = re.compile(r"^;(?: CP TOOLCHANGE END|WIPE_TOWER_END|_EXTRUSION_ROLE)")
    re_e_reset = re.compile(r"E([0-9]*\.?[0-9]+)")
    
    re_fmatrix = re.compile(r"^\s*; flush_volumes_matrix = (.+)")
    re_gmultiplier = re.compile(r"^\s*; flush_multiplier = (.+)")
    re_gdiams = re.compile(r"^\s*; filament_diameter = (.+)")
    re_gdens = re.compile(r"^\s*; filament_density = (.+)")
    re_gcolor = re.compile(r"^\s*; filament_colour = (.+)")
    re_gtype = re.compile(r"^\s*; filament_type = (.+)")
    re_gmin_purge = re.compile(r"^\s*; filament_minimal_purge_on_wipe_tower = (.+)")
    re_gprime_volume = re.compile(r"^\s*; prime_volume = (.+)")
    
    # PRE-PROCESSING: M82/M83 tracking and exact extrusion mm calculation
    total_lines = len(lines)
    line_extrusions = [0.0] * total_lines
    line_types = ["unknown"] * total_lines
    unbreakable_ranges = []
    active_blocks = {start: -1 for start, end in PROTECTED_BLOCKS}
    
    current_type = "unknown"
    is_absolute_e = False
    last_e = 0.0
    
    # PERFORMANCE CACHE
    search_type = re_type.search
    search_ext = re_extrusion.search
    search_e_reset = re_e_reset.search
    
    area = 0.0

    for i in range(total_lines):
        line = lines[i]
        
        # Topology
        if ";TYPE:" in line:
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
                
        # API Fallback for OrcaSlicer (Fast text check prior to regex)
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
            
        # Volumetric Mode Tracking (M82/M83)
        if "M82" in line:
            is_absolute_e = True
        elif "M83" in line:
            is_absolute_e = False
            
        # G92 E0 Handling
        if "G92" in line and "E" in line:
            m_e_reset = search_e_reset(line)
            last_e = float(m_e_reset.group(1)) if m_e_reset else 0.0
        
        # Extrusion Extraction
        if "G1" in line and "E" in line:
            match_ext = search_ext(line)
            if match_ext:
                e_val = float(match_ext.group(1))
                if is_absolute_e:
                    delta_e = e_val - last_e
                    last_e = e_val
                else:
                    delta_e = e_val
                line_extrusions[i] = max(0.0, delta_e)
    
    # IDENTIFYING BLOCKS AND TOOLS 
    changes = []
    i = 0
    while i < total_lines:
        match_filament_change = re_filament_change.search(lines[i])
        if match_filament_change:
            layer_num = int(match_filament_change.group(1))
            origin = i
            end_move = i
            idx_purge = -1
            current_tool = "T?"
            t_idx = 0

            # Tool search
            for j in range(i, min(i + 15, total_lines)):
                match_tool = re_tool.search(lines[j])
                if match_tool:
                    end_move = j
                    current_tool = match_tool.group(1)
                    if current_tool.startswith("T") and current_tool[1:].isdigit():
                        t_idx = int(current_tool[1:])
                    break

            # Purge search
            for j in range(end_move, min(end_move + 25, total_lines)):
                if re_purge.search(lines[j]):
                    idx_purge = j
                    #end_move = j
                    break
            
            # Wipe Tower volume calculation
            tower_e_mm = 0.0
            in_wipe_tower = False
            found_wipe_end = False
            temp_end_move = end_move

            # 3. Safe parsing of the Wipe Tower block
            for j in range(end_move, min(end_move + 2000, total_lines)):
                if re_wipe_start.search(lines[j]):
                    in_wipe_tower = True
                if in_wipe_tower and re_wipe_end.search(lines[j]) and "Wipe tower" not in lines[j]:
                    in_wipe_tower = False
                    found_wipe_end = True
                    temp_end_move = j
                    break
                
                if in_wipe_tower:
                    tower_e_mm += line_extrusions[j]
                
            if not found_wipe_end:
                tower_e_mm = 0.0

            changes.append({
                "layer": layer_num,
                "origin": origin,
                "end_move": end_move,
                "idx_purge": idx_purge,
                "tool": current_tool,
                "t_idx": t_idx,
                "tower_e_mm": tower_e_mm
            })
            i = end_move
        i += 1
        
    # BACKTRACKING WITH CHRONOLOGICAL PROTECTION
    for idx_change, c in enumerate(changes):
        if idx_change < 1:
            c["cut_index"] = c["origin"]
            c["saving"] = 0.0
            c["calculate_quantity"] = REMAINING_LENGTH
            c["break_flag"] = "Blocked by initialization"
            c["flush_vol"] = 0.0
            continue
        
        e_acumulated = 0.0
        candidate_index = c["origin"]
        candidate_saving = 0.0
        break_flag = "Unknown"
        
        lower_limit = 0
        if idx_change > 0:
            previous_change = changes[idx_change - 1]
            lower_limit = max(previous_change["origin"], previous_change["end_move"], previous_change["idx_purge"]) + 1
            
        for idx in range(c["origin"] - 1, lower_limit - 1, -1):
            line = lines[idx]
            
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
                
            if is_safe_zone:
                candidate_index = idx
                candidate_saving = e_acumulated
                
                if SEARCH_RETRACTIONS and (("G1" in line and "E-" in line) or "G10" in line) and re_retraction.search(line):
                    
                    if (TARGET - RETRACTION_MARGIN) <= e_acumulated <= TARGET:
                        safe_insert = idx + 1
                        
                        # Si la siguiente línea es un Z-hop (G1 Z...), lo saltamos para insertar después
                        if safe_insert < c["origin"] and "Z" in lines[safe_insert] and re_z_hop.search(lines[safe_insert]):
                            safe_insert += 1
                        
                        candidate_index = safe_insert
                        break_flag = "Retraction (Firmware or Standard) and Z-hop found in safety zone"
                        break
        else:
            break_flag = "Lower limit achieved without safety zones" if candidate_index == c["origin"] else f"Lower limit achieved in safety zone ({candidate_saving:.2f} mm)"
            
        # Smart placement to avoid protected blocks (Backwards jump)
        original_idx = candidate_index
        moved = True
        
        while moved and candidate_index < c["origin"]:
            moved = False
            for r_start, r_end in unbreakable_ranges:
                if r_start <= candidate_index <= r_end:
                    candidate_index = r_end + 1
                    moved = True
                    
            if candidate_index >= c["origin"]:
                candidate_index = c["origin"]
                break
            
            if candidate_index >= 0:
                line_str = lines[candidate_index]
                if "SET_VELOCITY_LIMIT" in line_str or line_str.strip() == "" or ("G1" in line_str and "E-" in line_str and re_retraction.search(line_str)):
                    candidate_index += 1
                    moved = True
                    
        # Recalculate Volumetric Saving if index moved
        if candidate_index != original_idx:
            recalc_saving = sum(line_extrusions[i] for i in range(c["origin"] - 1, candidate_index - 1, -1))
            candidate_saving = min(recalc_saving, TARGET)
            
        # PHYSICOCHEMICAL MODEL INTEGRATED FOR ORCASLICER
        curr_t_idx = c.get("t_idx", 0)
        prev_t_idx = changes[idx_change - 1].get("t_idx", 0) if idx_change > 0 else curr_t_idx
        
        
        dia = config.diams[curr_t_idx] if hasattr(config, 'diams') and curr_t_idx < len(config.diams) else getattr(config, 'dia', 1.75)
        area = math.pi * ((dia / 2.0) ** 2)
        
        # Extract Minimal Purge limit per filament (OrcaSlicer standard)
        min_purge_limit = config.min_purge[curr_t_idx] if hasattr(config, 'min_purge') and curr_t_idx < len(config.min_purge) else 10.0
        prime_volume = config.prime_volume if hasattr(config, 'prime_volume') else 25.0  
        
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
        
        # HYBRID VS BUCKET_ONLY LOGIC FOR ORCASLICER
        if PURGE_TARGET == "hybrid":
            remaining_purge_mm = total_purge_needed_mm - c["tower_e_mm"] - candidate_saving
            calculate_quantity = max(0.0, remaining_purge_mm)
        else: 
            calculate_quantity = max(0.0, total_purge_needed_mm - candidate_saving)
        
        c["cut_index"] = candidate_index
        c["saving"] = candidate_saving
        c["calculate_quantity"] = calculate_quantity
        c["break_flag"] = f"{break_flag} ({candidate_saving:.2f} mm)"
        
    # CONSTRUCTION AND LABELING OF THE NEW G-CODE
    insertions = { i: [] for i in range(len(lines) + 1) }
    line_to_erase = set()
    replacement = {}
    
    total_saving = 0.0
    optimized_changes = 0
    
    for idx_change, c in enumerate(changes):
        if c["layer"] < 0:
            continue
        
        if c.get("cut_index") < c["origin"]:
            block = lines[c["origin"] : c["end_move"] + 1]
            insertions[c["cut_index"]].extend(block)
            for k in range(c["origin"], c["end_move"] + 1):
                line_to_erase.add(k)
                
            total_saving += c["saving"]
            optimized_changes += 1
            
            state = "[PARCIAL]" if "Limit" in c["break_flag"] or "not found" in c["break_flag"] else "[SUCCESS]"
            print(f"{state} Layer {c['layer']} | Cut Line {c['cut_index']} | Sav: {c['saving']:.2f}mm | Tow: {c['tower_e_mm']:.2f}mm | Trash: {c['calculate_quantity']:.2f}mm | {c['break_flag']}")
            
        elif idx_change == 1:
            print(f"[PASSED] Layer {c['layer']} | {c['break_flag']} | Trash: {c['calculate_quantity']:.2f} mm")
            
        if c["idx_purge"] != -1:
            match_indent = re.match(r"^(\s*)", lines[c["idx_purge"]])
            indent = match_indent.group(1) if match_indent else ""
            
            curr_t_idx = c.get("t_idx", 0)
            prev_t_idx = changes[idx_change - 1].get("t_idx", 0) if idx_change > 0 else curr_t_idx
            
            curr_type = config.types[curr_t_idx] if hasattr(config, 'types') and curr_t_idx < len(config.types) else "UNK"
            curr_color = hex_to_color_name(config.colors[curr_t_idx] if hasattr(config, 'colors') and curr_t_idx < len(config.colors) else "#000")
            
            prev_type = config.types[prev_t_idx] if hasattr(config, 'types') and prev_t_idx < len(config.types) else "UNK"
            prev_color = hex_to_color_name(config.colors[prev_t_idx] if hasattr(config, 'colors') and prev_t_idx < len(config.colors) else "#000")
            
            flush_val = c.get("flush_vol", 0.0)
            obs_text = f"Active: T{curr_t_idx} [{curr_type} {curr_color}] (Purging T{prev_t_idx} [{prev_type} {prev_color}] {c['calculate_quantity']:.2f} mm) | Matrix: {flush_val:.1f} mm3 ({flush_val/area:.2f} mm) | Tower: {c['tower_e_mm']:.1f} mm"
            replacement[c["idx_purge"]] = f"{indent}PURGE_IN_TRASH QUANTITY={c['calculate_quantity']:.4f} OBS=\"{obs_text}\" MATERIAL=\"{prev_type}\"\n"
        
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
        
        remaining_weight_g += (remaining_vol_mm3 / 1000) * den
        target_weight_g += (target_vol_mm3 / 1000) * den
        change_theoretical_vol = max(flush_vol_mm3, remaining_vol_mm3)
        total_theoretical_waste_vol_mm3 += change_theoretical_vol
        theoretical_waste_g += (change_theoretical_vol / 1000.0) * den
        weight_saved_g += ((saving * area) / 1000.0) * den
        
        tool_real_waste_g[curr_t_idx] = tool_real_waste_g.get(curr_t_idx, 0.0) + (((quantity_mm + tower_e_mm) * area) / 1000.0) * den
        
    # KPI's
    actual_waste_g = max(0.0, theoretical_waste_g - weight_saved_g)
    oce = (optimized_changes / len(changes)) * 100 if len(changes) > 0 else 0.0
    ofe = (weight_saved_g / theoretical_waste_g) * 100 if theoretical_waste_g > 0 else 0.0
    hfe = (weight_saved_g / remaining_weight_g) * 100 if remaining_weight_g > 0 else 0.0
    cse = (weight_saved_g / target_weight_g) * 100 if target_weight_g > 0 else 0.0
    
    # PART + TOWER WEIGHT
    base_weights_g = []
    re_used_g = re.compile(r"^;\s*filament used \[g\]\s*=\s*(.*)")
    for line in reversed(lines):
        if "filament used [g]" in line:
            match_used = re_used_g.match(line)
            if match_used:
                base_weights_g = [float(x.strip()) for x in match_used.group(1).split(',')]
                break
            
    filament_report_lines = []
    total_job_weight_g = 0.0
    max_tool = max(tool_real_waste_g.keys()) if tool_real_waste_g else 0
    max_tool = max(max_tool, len(base_weights_g) - 1)

    
    for t in range(max_tool + 1):
        base_g = base_weights_g[t] if t < len(base_weights_g) else 0.0
        waste_g = tool_real_waste_g.get(t, 0.0)
        total_g = base_g + waste_g
        
        if total_g > 0:
            t_type = config.types[t] if hasattr(config, 'types') and t < len(config.types) else "UNK"
            t_color = hex_to_color_name(config.colors[t] if hasattr(config, 'colors') and t < len(config.colors) else "#000")
            total_job_weight_g += total_g
            filament_report_lines.append(
                f"   - T{t} [{t_type} {t_color}]: Piece= {base_g:.2f}g | Purge Waste= {waste_g:.2f}g | TOTAL= {total_g:.2f}g"
            )
                  
    new_filepath = config.filepath.replace('.gcode', '_ChromaSave.gcode')
    
    # REPORTS AND LOGS
    current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    gcode_file_name = os.path.basename(config.filepath)
    file_dir = os.path.dirname(config.filepath)
    log_dir = os.path.join(file_dir, "chromasave_history.log")
    
    log_content = (
        f"[{current_date}] Gcode File: {gcode_file_name}\n"
        f"Changes: {len(changes)} | Optimized: {optimized_changes} | OCE: {oce:.2f}% | "
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
    
    total_piece_weight_g = sum(base_weights_g) if base_weights_g else 0.0
    
    report_str = (
        "\n"
        " ==================================================================================\n"
        " GLOBAL REPORT (ChromaSave v1.0.0)\n"
        " ==================================================================================\n"
        f"  Purge Target Mode:                               {PURGE_TARGET.upper()}\n"
        " ----------------------------------------------------------------------------------\n"
        "     Color Changes\n"
        " ----------------------------------------------------------------------------------\n"
        f"       Total Changes:                                  {len(changes)}\n"
        f"       Optimized Changes:                              {optimized_changes}\n"
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
            " GLOBAL REPORT (ChromaSave v1.0.0)\n"
            f"Purge Target Mode:            {PURGE_TARGET.upper()}\n"
            "Color Changes\n"
            f" Total Changes:               {len(changes)}\n"
            f" Optimized Changes:           {optimized_changes}\n"
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
    
    new_lines.append(report_str)
    
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