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

import sys
import tkinter as tk
import tkinter.font as tkfont

def show_report_popup(report_text):
    """ Shows a native popup window with the ChromaSave report and scroll."""
    try:
        root = tk.Tk()
        root.title("ChromaSave - Optimization Report")
        
        # --- FORMAT ---
        window_width = 800
        window_height = 600 
        
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        center_x = int(screen_width/2 - window_width / 2)
        center_y = int(screen_height/2 - window_height / 2)
        
        root.geometry(f'{window_width}x{window_height}+{center_x}+{center_y}')
        
        # --- COLOR AND BEHAVIOR ---
        root.attributes('-topmost', True)
        root.configure(bg="#f8f9fa")
        root.resizable(False, False)
        
        # --- FONTS ---
        title_font = tkfont.Font(family="Helvetica", size=14, weight="bold")
        body_font = tkfont.Font(family="Helvetica", size=11)
        
        # --- WIDGETS ---
        # TITLE
        lbl_title = tk.Label(root, text="📊 Optimization Report", font=title_font, bg="#f8f9fa", fg="#212529")
        lbl_title.pack(pady=(20, 10))
        
        # Text container
        frame_body = tk.Frame(root, bg="#f8f9fa")
        frame_body.pack(padx=20, pady=5, fill="both", expand=True)
        
        # scrollbar
        scrollbar = tk.Scrollbar(frame_body)
        scrollbar.pack(side="right", fill="y")
        
        # Text area (replaces the Label)
        # wrap="word" ensures words are not cut in half
        txt_body = tk.Text(frame_body, font=body_font, bg="#f8f9fa", fg="#495057", 
                           bd=0, highlightthickness=0, yscrollcommand=scrollbar.set, wrap="word")
        txt_body.pack(side="left", fill="both", expand=True)
        
        scrollbar.config(command=txt_body.yview)
        
        # Report insertion
        txt_body.insert("1.0", report_text)
        txt_body.config(state="disabled") # Read only - Makes it read-only like a Label
        
        # Button to close the popup
        btn_close = tk.Button(root, text="Accept", command=root.destroy, width=15, font=tkfont.Font(family="Helvetica", size=10, weight="bold"))
        btn_close.pack(side="bottom", pady=20)
        
        # Show the popup
        root.mainloop()
        
    except Exception as e:
        print(f"[ChromaSave LOG] Alert: The graphical interface could not be loaded. ({e})", file=sys.stderr)