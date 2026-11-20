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

import sys
import os
import argparse

from pathlib import Path

src_path = str(Path(__file__).resolve().parent.parent)
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from chromasave.ui_popup import show_report_popup
from core_engine import filament_change_optimizer

def report(data, filepath, console):

    # Gcode save, Report and Log
    run_console = console
    
    if run_console:
        # run in console. Gcode file saved in folder to manual upload to Mainsail
        with open(data.get("new_filepath"), 'w', encoding='utf-8') as file:
            file.writelines(data.get("new_lines"))
                     
    else:
        # run in post-processing in orcaslicer - Overwrite OrcaSlicer temporal file
        with open(filepath, 'w', encoding='utf-8') as file:
            file.writelines(data.get("new_lines"))
        
        report_result = data.get("report_cli", "Optimization successfully completed.")
        show_report_popup(report_result)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ChromaSave-SmartPurge", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--len', type=float, default=64.857, help='Remaining length in mm between the cutter and the hotend tip. ChromaHead Nozzle volume (156mm3) = 64.857mm of filament for 1.75mm diameter.')
    parser.add_argument('--sm', type=float, default=10.0, help='Safety margin in mm to prevent color mixing.')
    
    parser.add_argument('--sre', action='store_true', help='Look for a retraction command to relocate the FILAMENT_CHANGE command within the tolerance window.')
    parser.add_argument('--no-sre', action='store_false', dest='sre', help='Disable looking for retraction command.')
    parser.set_defaults(sre=True)
    
    parser.add_argument('--rem', type=float, default=5.0, help='Lock for a retraction margin in mm for safely relocating the FILAMENT_CHANGE command')
    parser.add_argument('filepath', type=str, help='Path to G-code file')

    parser.add_argument('--skip_purge', type=float, default=2.0, help='skip_purge - Minimum length in mm of purge to skip dynamic purge process')
    
    parser.add_argument('--min_saving', '--min-saving', '-ms', dest='min_saving', type=float, default=3.0, help='Minimum filament saving (mm) required to trigger an early-cut (Default: 3.0)')

    parser.add_argument('--aipc', action='store_true', help='Enable - Avoid in Piece Cut - to prevent FILAMENT_CHANGE command within aesthetic zone.')
    parser.add_argument('--no-aipc', action='store_false', dest='aipc', help='Disable - Avoid in Piece Cut -')
    parser.set_defaults(aipc=True)

    # Purge Destination ("hybrid" by default, "bucket_only" as alternative)
    parser.add_argument('--purge_target', type=str, choices=['hybrid', 'bucket_only'], default='hybrid', help='Define where the residual purge is directed (hybrid compensates with wipe tower).')

    # Dynamic Pre-Cut Retraction (Klipper)
    parser.add_argument('--pre_cut_retract', action='store_true', help='Enable dynamic pre-cut retraction in Klipper to recover the remaining gap up to TARGET.')
    parser.add_argument('--no-pre_cut_retract', action='store_false', dest='pre_cut_retract', help='Disable dynamic pre-cut retraction.')
    parser.set_defaults(pre_cut_retract=False)
    parser.add_argument('--max_pre_cut_retract', type=float, default=18.0, help='Maximum safe retraction length (mm) before cutting to prevent heatbreak clogs.')
    
    parser.add_argument('--console', action='store_true', help='Enable - Run in console - To run in console. Gcode file saved in folder to manual upload to Mainsail.')
    parser.add_argument('--no-console', action='store_false', dest='console', help='Disable - Run in console - Overwrite OrcaSlicer temporal file')
    parser.set_defaults(console=True)

    SAFETY_ZONES = {
        "Prime tower": True,
        "Wipe tower": True,             # Nomenclature of Bambu Lab          
        "Support": True,                
        "Support interface": True,      
        "Sparse infill": True,          
        "Dense infill": True,           
        "Solid infill": True,           # Standard nomenclature of Orca
        "Internal solid infill": False, 
        "Skirt": False,                
        "Brim": False,                  
        "Gap fill": False,              
        "Outer wall": False,           
        "Inner wall": False,           
        "Overhang wall": False,        
        "Top surface": False,          
        "Bottom surface": False,       
        "Internal bridge": False,       
        "Bridge": False,                
        "Custom": False                 
    }
    
    parser.add_argument(
        '--dzones',
        action='append',
        choices=list(SAFETY_ZONES.keys()),
        help="Zones that you want disable - can be several (Prime tower, Wipe tower, Support, Support interface, Sparse infill, \
            Dense infill, Solid infill, Internal solid infill, Skirt, Brim, Gap fill, Outer wall, Inner wall, Overhang wall, Top surface, \
            Bottom surface, Internal bridge, Bridge, Custom)"
    )
    
    args = parser.parse_args()

    # Executing Math Model
    results = filament_change_optimizer(args)
    
    report(results, args.filepath, getattr(args, 'console', False))