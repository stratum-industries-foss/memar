; Reference Model 3: Tiny Detail (10x10mm)
; Layer height: 0.2mm
; Nozzle: 0.4mm
; Filament: PLA
; This model tests ironing on very small parts

G28 ; Home all axes
G0 F3000 ; Set speed

; Layer 0.2mm
G0 X0 Y0 Z0.2
G1 X10 Y0 Z0.2 E1 F1500 ; Bottom
G1 X10 Y10 Z0.2 E2 F1500 ; Right
G1 X0 Y10 Z0.2 E3 F1500 ; Top
G1 X0 Y0 Z0.2 E4 F1500 ; Left (close)

; Layer 0.4mm
G0 X0 Y0 Z0.4
G1 X10 Y0 Z0.4 E5 F1500
G1 X10 Y10 Z0.4 E6 F1500
G1 X0 Y10 Z0.4 E7 F1500
G1 X0 Y0 Z0.4 E8 F1500

; Layer 0.6mm
G0 X0 Y0 Z0.6
G1 X10 Y0 Z0.6 E9 F1500
G1 X10 Y10 Z0.6 E10 F1500
G1 X0 Y10 Z0.6 E11 F1500
G1 X0 Y0 Z0.6 E12 F1500

M104 S0 ; Turn off hotend
G28 ; Home all axes
M84 ; Disable motors
