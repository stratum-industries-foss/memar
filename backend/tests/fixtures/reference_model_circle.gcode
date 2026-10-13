; Reference Model 2: Complex Circle (80mm diameter)
; Layer height: 0.2mm
; Nozzle: 0.4mm
; Filament: PLA

G28 ; Home all axes
G0 F3000 ; Set speed

; Layer 0.2mm - Approximate circle using line segments
G0 X60 Y50 Z0.2
G1 X70 Y55 Z0.2 E10 F1500 ; 1 o'clock
G1 X75 Y65 Z0.2 E20 F1500 ; 2 o'clock
G1 X70 Y75 Z0.2 E30 F1500 ; 3 o'clock
G1 X60 Y80 Z0.2 E40 F1500 ; 4 o'clock
G1 X50 Y75 Z0.2 E50 F1500 ; 5 o'clock
G1 X45 Y65 Z0.2 E60 F1500 ; 6 o'clock
G1 X50 Y55 Z0.2 E70 F1500 ; 7 o'clock
G1 X60 Y50 Z0.2 E80 F1500 ; 8 o'clock (back to start)

; Inner circle (fill)
G0 X60 Y55 Z0.2
G1 X65 Y57 Z0.2 E85 F1500
G1 X65 Y63 Z0.2 E90 F1500
G1 X60 Y65 Z0.2 E95 F1500
G1 X55 Y63 Z0.2 E100 F1500
G1 X55 Y57 Z0.2 E105 F1500
G1 X60 Y55 Z0.2 E110 F1500

; Layer 0.4mm
G0 X60 Y50 Z0.4
G1 X70 Y55 Z0.4 E120 F1500
G1 X75 Y65 Z0.4 E130 F1500
G1 X70 Y75 Z0.4 E140 F1500
G1 X60 Y80 Z0.4 E150 F1500
G1 X50 Y75 Z0.4 E160 F1500
G1 X45 Y65 Z0.4 E170 F1500
G1 X50 Y55 Z0.4 E180 F1500
G1 X60 Y50 Z0.4 E190 F1500

M104 S0 ; Turn off hotend
G28 ; Home all axes
M84 ; Disable motors
