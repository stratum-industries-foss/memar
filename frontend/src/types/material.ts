/**
 * Material types and presets for MEMAR printer/machine fleet
 */

export type Material = {
  id?: string
  name: string
  nozzle_temp_c: number
  bed_temp_c: number
  print_speed_mm_s: number
  retraction_distance_mm: number
  retraction_speed_mm_s: number
  description?: string
  color?: string
}

export const DEFAULT_MATERIALS: Material[] = [
  {
    name: 'PLA',
    nozzle_temp_c: 200,
    bed_temp_c: 60,
    print_speed_mm_s: 50,
    retraction_distance_mm: 5,
    retraction_speed_mm_s: 45,
    description: 'Standard thermoplastic',
    color: '#E0E0E0',
  },
  {
    name: 'PETG',
    nozzle_temp_c: 235,
    bed_temp_c: 80,
    print_speed_mm_s: 35,
    retraction_distance_mm: 5,
    retraction_speed_mm_s: 35,
    description: 'Engineering plastic',
    color: '#FFC107',
  },
  {
    name: 'ABS',
    nozzle_temp_c: 240,
    bed_temp_c: 100,
    print_speed_mm_s: 40,
    retraction_distance_mm: 7,
    retraction_speed_mm_s: 50,
    description: 'High-strength plastic',
    color: '#000000',
  },
  {
    name: 'TPU',
    nozzle_temp_c: 220,
    bed_temp_c: 60,
    print_speed_mm_s: 20,
    retraction_distance_mm: 3,
    retraction_speed_mm_s: 30,
    description: 'Flexible filament',
    color: '#FF6B6B',
  },
  {
    name: 'Nylon',
    nozzle_temp_c: 250,
    bed_temp_c: 85,
    print_speed_mm_s: 30,
    retraction_distance_mm: 4,
    retraction_speed_mm_s: 25,
    description: 'Durable engineering material',
    color: '#4A4A4A',
  },
]
