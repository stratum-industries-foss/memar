/**
 * Machine type definitions and utilities
 */

export type MachineTypeValue =
  | 'fdm'
  | 'sla'
  | 'idex'
  | 'cnc_mill'
  | 'cnc_lathe'
  | 'cnc_router'
  | 'laser'
  | 'plasma'
  | 'waterjet'
  | 'vinyl'
  | 'pick_and_place'
  | 'embroidery'
  | 'wire_edm'

/**
 * Jog axis types
 */
export type JogAxis = 'X' | 'Y' | 'Z' | 'E'

/**
 * Motion check response from API
 */
export type MotionCheckResponse = {
  ok: boolean
  blocking_reasons?: string[]
  message?: string
}

/**
 * Motion intent for safety checks
 */
export type MotionIntent = 'jog' | 'macro' | 'print'

/**
 * Check if a machine type is CNC for jog/motion purposes
 */
export function isCncMachine(type: MachineTypeValue): boolean {
  return type.startsWith('cnc_')
}

/**
 * Get a friendly display name for a machine type
 */
export function getMachineTypeLabel(type: MachineTypeValue): string {
  const labels: Record<MachineTypeValue, string> = {
    fdm: 'FDM Printer',
    sla: 'SLA Printer',
    idex: 'IDEX Printer',
    cnc_mill: 'CNC Mill',
    cnc_lathe: 'CNC Lathe',
    cnc_router: 'CNC Router',
    laser: 'Laser Cutter',
    plasma: 'Plasma Cutter',
    waterjet: 'Waterjet',
    vinyl: 'Vinyl Cutter',
    pick_and_place: 'Pick & Place',
    embroidery: 'Embroidery Machine',
    wire_edm: 'Wire EDM',
  }
  return labels[type] || type
}


/**
 * Check if machine type is FDM/SLA (additive)
 */
export function isAdditiveMachine(type: MachineTypeValue): boolean {
  return type === 'fdm' || type === 'sla' || type === 'idex'
}

/**
 * Check if machine type is subtractive (laser, plasma, etc.)
 */
export function isSubtractiveMachine(type: MachineTypeValue): boolean {
  return (
    type === 'laser' ||
    type === 'plasma' ||
    type === 'waterjet' ||
    type === 'wire_edm'
  )
}
