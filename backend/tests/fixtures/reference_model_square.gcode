; Reference Model 1: Simple Square (100x100mm)
; Layer height: 0.2mm
; Nozzle: 0.4mm
; Filament: PLA

G28 ; Home all axes
G0 F3000 ; Set speed

; Layer 0.2mm
G0 X10 Y10 Z0.2
G1 X110 Y10 Z0.2 E50 F1500 ; Bottom line
G1 X110 Y110 Z0.2 E100 F1500 ; Right line
G1 X10 Y110 Z0.2 E150 F1500 ; Top line
G1 X10 Y10 Z0.2 E200 F1500 ; Left line back to start

; Layer 0.4mm
G0 X10 Y10 Z0.4
G1 X110 Y10 Z0.4 E250 F1500
G1 X110 Y110 Z0.4 E300 F1500
G1 X10 Y110 Z0.4 E350 F1500
G1 X10 Y10 Z0.4 E400 F1500

M104 S0 ; Turn off hotend
G28 ; Home all axes
M84 ; Disable motors
