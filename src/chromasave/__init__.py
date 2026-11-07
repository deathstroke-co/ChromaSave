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

import os
import json
import sys

try:
    import orca
except ImportError:
    orca = None

from .core_engine import filament_change_optimizer

# Plugin configuration Class
class ChromaSaveConfig:
    def __init__(self, filepath, ui_config, ctx=None):
        self.filepath = filepath

        # Extract the numeric and boolean variables from ui_config.
        self.len = float(ui_config.get("len", 64.857))
        self.sm = float(ui_config.get("sm", 10.0))
        self.dia = 1.75
        self.den = 1.04
        self.sre = bool(ui_config.get("sre", True))
        self.rem = float(ui_config.get("rem", 5.0))
        self.aipc = bool(ui_config.get("aipc", True))
        
        # Purge Destination ("hybrid" by default, "bucket_only" as alternative)
        self.purge_target = str(ui_config.get("purge_target", "hybrid")).strip().lower()
        
        # Default values for safety zones
        self.default_zones = {
            #
            "Prime tower": True,            
            "Support": True,                
            "Support interface": True,      
            "Sparse infill": True,          
            "Dense infill": True,           
            
            # 
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
        
        # Extract "SAFETY_ZONES" and match the actual values.
        raw_zones = ui_config.get("SAFETY_ZONES")
        self.dzones = []
        if isinstance(raw_zones, dict):
            for zone in self.default_zones.keys():
                if zone in raw_zones:
                    self.default_zones[zone] = bool(raw_zones[zone])
                    if not self.default_zones[zone]:
                        self.dzones.append(zone)

        # DIAGNOSTICS 1: Prints all key parameters to the logs.
        print(f"[ChromaSave LOG] ¡Configuration loaded successfully!", file=sys.stderr)
        print(f"[ChromaSave LOG] -> len: {self.len}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> sm : {self.sm}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> dia: {self.dia}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> rem: {self.rem}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> den: {self.den}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> sre: {self.sre}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> aipc: {self.aipc}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> purge_target: {self.purge_target}", file=sys.stderr)
        print(f"[ChromaSave LOG] -> Safety_Zones: {self.dzones}", file=sys.stderr)

        # Extracting Filaments Info from API
        self.diams = [self.dia] * 15
        self.densities = [self.den] * 15
        self.min_purge = [10.0] * 15 # Default safe minimal purge
        self.prime_volume = 25.0
        self.flush_matrix = []
        self.flush_multiplier = 1.0
        self.colors = ["#000000"] * 15
        self.types = ["Unknown"] * 15
        
        # Detecting firmware_retraction
        self.fr_enable = 0

        if ctx is not None and hasattr(ctx, "config_value"):
            try:
                def parse_api_value(val, default_val, is_str=False):
                    if val is None: return [default_val] * 15
                    if isinstance(val, str):
                        import re
                        parts = [v.strip() for v in re.split(r'[,;]', val) if v.strip()]
                        if len(parts) > 1:
                            return parts if is_str else [float(v) for v in parts]
                        else:
                            return [val] * 15 if is_str else [float(val)] * 15
                    if isinstance(val, (list, tuple)): 
                        return [str(v) for v in val] if is_str else [float(v) for v in val]
                    return [str(val)] * 15 if is_str else [float(val)] * 15

                # Diameters, densities, minimal purge and flush matrix
                self.diams = parse_api_value(ctx.config_value("filament_diameter"), self.dia)
                self.densities = parse_api_value(ctx.config_value("filament_density"), self.den)
                self.min_purge = parse_api_value(ctx.config_value("filament_minimal_purge_on_wipe_tower"), 10.0)
                self.flush_matrix = parse_api_value(ctx.config_value("flush_volumes_matrix"), 0.0)
                self.prime_volume = parse_api_value(ctx.config_value("prime_volume"), 25.0)

                # Filament types and colors
                self.colors = parse_api_value(ctx.config_value("filament_colour"), "#000000", is_str=True)
                self.types = parse_api_value(ctx.config_value("filament_type"), "UNK", is_str=True)
                
                # Flush multiplier
                raw_mult = ctx.config_value("flush_multiplier")
                if raw_mult is not None:
                    self.flush_multiplier = float(raw_mult)
                    
                # firmware_retraction
                self.fr_enable = parse_api_value(ctx.config_value("use_firmware_retraction"), 0)

                # DIAGNOSTICS 2: Prints all filaments info
                print(f"[ChromaSave LOG] Min Purge Limits: {self.min_purge}", file=sys.stderr)
                print(f"[ChromaSave LOG] Flush Matrix loaded ({len(self.flush_matrix)} values)", file=sys.stderr)
                print(f"[ChromaSave LOG] Flush Matrix: {self.flush_matrix}", file=sys.stderr)
                print(f"[ChromaSave LOG] Flush Multiplier: {self.flush_multiplier}", file=sys.stderr)
                print(f"[ChromaSave LOG] Prime Volume: {self.prime_volume}", file=sys.stderr)
                print(f"[ChromaSave LOG] Firmware Retraction: {self.fr_enable}", file=sys.stderr)
            except Exception as e:
                print(f"[ChromaSave LOG] Error reading the OrcaSlicer API: {e}", file=sys.stderr)


# CAPACITY CLASS (The Executor)
if orca is not None and hasattr(orca, "slicing"):
    class ChromaSavePostProcessor(orca.slicing.SlicingPipelineCapabilityBase):
        def get_name(self):
            return "ChromaSave SmartPurge"
            
        def execute(self, ctx):
            if ctx.step != orca.slicing.Step.psGCodePostProcess:
                return orca.ExecutionResult.success()
            
            gcode_path = ctx.gcode_path
            if not gcode_path or not os.path.exists(gcode_path):
                print(f"[ChromaSave LOG] Error: Temporary G-code path not detected.", file=sys.stderr)
                return orca.ExecutionResult.failure("Non-existent G-code file path.")
            
            ui_config = {}
            if hasattr(self, 'get_config'):
                try:
                    raw_config = self.get_config()
                    if isinstance(raw_config, str) and raw_config.strip():
                        ui_config = json.loads(raw_config)
                    elif isinstance(raw_config, dict):
                        ui_config = raw_config
                except Exception as e:
                    print(f"[ChromaSave LOG] Internal error processing UI config: {e}", file=sys.stderr)

            config = ChromaSaveConfig(gcode_path, ui_config, ctx)
            
            try:
                data = filament_change_optimizer(config)
                
                with open(config.filepath, 'w', encoding='utf-8') as file:
                    file.writelines(data.get("new_lines"))
                    
                report_result = data.get("report_orca", "Optimization successfully completed.")
                
                # Attempt to show a native notification in OrcaSlicer
                try:
                    if hasattr(orca, "host") and hasattr(orca.host, "ui") and hasattr(orca.host.ui, "push_notification"):
                        
                        # Searching for the correct enumerator to avoid typing errors
                        notif_level = None
                        for attr in dir(orca.host.ui.NotificationLevel):
                            if "info" in attr.lower():
                                notif_level = getattr(orca.host.ui.NotificationLevel, attr)
                                break
                        
                        if notif_level is None:
                            for attr in dir(orca.host.ui.NotificationLevel):
                                if not attr.startswith("__"):
                                    notif_level = getattr(orca.host.ui.NotificationLevel, attr)
                                    break
                                    
                        # Clear emojis from the original report to avoid '?' characters in OrcaSlicer
                        clean_report= report_result.replace("✅", "").replace("📊", "")
                        
                        # Inject the notification using the entire text of the report
                        orca.host.ui.push_notification(notif_level, clean_report)
                    else:
                        import sys
                        print("[ChromaSave LOG] La API orca.host.ui.push_notification is not available.", file=sys.stderr)
                except Exception as ui_error:
                    import sys
                    print(f"[ChromaSave LOG] Error showing native notification: {ui_error}", file=sys.stderr)
                    
                return orca.ExecutionResult.success(report_result)
            
            except Exception as e:
                # API actualizada: orca.ExecutionResult.failure(status, message)
                status = getattr(orca.PluginResult, "failure", 0) # Fallback seguro
                return orca.ExecutionResult.failure(status, f"Internal script error: {str(e)}")
            
    # PACKAGE CLASS (The Registrar)
    @orca.plugin
    class ChromaSavePackage(orca.base):
        def register_capabilities(self):
            orca.register_capability(ChromaSavePostProcessor)
