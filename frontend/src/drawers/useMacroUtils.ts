/**
 * useMacroUtils.ts
 * Type definitions and utilities for Klipper macro parsing
 */

/**
 * Parse raw string macro parameters (e.g., "KEY=VALUE KEY=VALUE")
 * @param raw - Raw parameter string from user input
 * @returns Object mapping parameter names to values, or null if parse fails
 */
export function parseStringMacroParams(raw: string): Record<string, string> | null {
  const trimmed = raw.trim()
  if (!trimmed) return {}
  const out: Record<string, string> = {}
  for (const token of trimmed.split(/\s+/)) {
    const eq = token.indexOf('=')
    if (eq <= 0 || eq === token.length - 1) return null
    out[token.slice(0, eq)] = token.slice(eq + 1)
  }
  return out
}

export type MacroParamType = 'string' | 'number' | 'boolean' | 'array';

export interface MacroParam {
  name: string;
  type: MacroParamType;
  default?: string | number | boolean;
  required?: boolean;
  description?: string;
}

export interface MacroEntry {
  name: string;
  category?: string;
  description?: string;
  parameters?: MacroParam[];
}

/**
 * Parse a raw macro parameter value and infer its type
 * @param value - The raw parameter value
 * @returns Inferred type string
 */
function inferParamType(value: unknown): MacroParamType {
  if (typeof value === 'boolean') return 'boolean';
  if (typeof value === 'number') return 'number';
  if (Array.isArray(value)) return 'array';
  return 'string';
}

/**
 * Parse raw macro parameters from Klipper API response
 * Handles both simple parameter objects and complex nested structures
 * @param macro - Raw macro object from Klipper API
 * @returns Array of MacroParam objects
 */
export function parseRawMacroParams(macro: unknown): MacroParam[] {
  if (!macro || typeof macro !== 'object') {
    return [];
  }

  const macroObj = macro as Record<string, unknown>;
  const params: MacroParam[] = [];

  // Common parameter fields in Klipper macros
  const paramKeys = [
    'params',
    'parameters',
    'args',
    'arguments',
    'options',
    'config',
  ];

  for (const key of paramKeys) {
    const paramData = macroObj[key];

    if (paramData && typeof paramData === 'object') {
      if (Array.isArray(paramData)) {
        // Array of parameter definitions
        for (const item of paramData) {
          if (typeof item === 'object' && item !== null) {
            const itemObj = item as Record<string, unknown>;
            params.push({
              name: String(itemObj.name ?? itemObj.id ?? ''),
              type: (itemObj.type as MacroParamType) || 'string',
              default: itemObj.default as string | number | boolean | undefined,
              required: Boolean(itemObj.required ?? false),
              description: String(itemObj.description ?? itemObj.help ?? ''),
            });
          }
        }
      } else {
        // Object with parameter definitions
        const paramObj = paramData as Record<string, unknown>;
        for (const [paramName, paramValue] of Object.entries(paramObj)) {
          if (paramValue && typeof paramValue === 'object') {
            const paramDef = paramValue as Record<string, unknown>;
            params.push({
              name: paramName,
              type:
                (paramDef.type as MacroParamType) ||
                inferParamType(paramDef.default),
              default: paramDef.default as string | number | boolean | undefined,
              required: Boolean(paramDef.required ?? false),
              description: String(paramDef.description ?? ''),
            });
          } else {
            // Simple key-value pair; infer type from value
            params.push({
              name: paramName,
              type: inferParamType(paramValue),
              default: paramValue as string | number | boolean,
              required: false,
            });
          }
        }
      }

      // Only parse the first recognized parameter key
      if (params.length > 0) break;
    }
  }

  return params;
}

/**
 * Extract macro name and category from raw macro object
 * @param name - Macro name or full identifier
 * @param macro - Raw macro object (optional)
 * @returns MacroEntry with extracted name and category
 */
export function extractMacroMetadata(
  name: string,
  macro?: unknown
): MacroEntry {
  // Common category prefixes in macro naming conventions
  const categoryMatch = name.match(/^([A-Z_]+)_(.+)$/);
  const category = categoryMatch ? categoryMatch[1].toLowerCase() : undefined;
  const displayName = categoryMatch
    ? categoryMatch[2].replace(/_/g, ' ')
    : name.replace(/_/g, ' ');

  const entry: MacroEntry = {
    name: displayName,
    category,
  };

  // Extract description if available
  if (macro && typeof macro === 'object') {
    const macroObj = macro as Record<string, unknown>;
    if (macroObj.description) {
      entry.description = String(macroObj.description);
    } else if (macroObj.help) {
      entry.description = String(macroObj.help);
    } else if (macroObj.doc) {
      entry.description = String(macroObj.doc);
    }
  }

  // Parse parameters
  if (macro) {
    entry.parameters = parseRawMacroParams(macro);
  }

  return entry;
}

/**
 * Filter macros by category
 * @param macros - Array of MacroEntry objects
 * @param category - Category name to filter by
 * @returns Filtered array
 */
export function filterMacrosByCategory(
  macros: MacroEntry[],
  category: string
): MacroEntry[] {
  return macros.filter(
    (m) => m.category?.toLowerCase() === category.toLowerCase()
  );
}

/**
 * Group macros by category
 * @param macros - Array of MacroEntry objects
 * @returns Object with categories as keys and macro arrays as values
 */
export function groupMacrosByCategory(
  macros: MacroEntry[]
): Record<string, MacroEntry[]> {
  return macros.reduce(
    (acc, macro) => {
      const cat = macro.category || 'uncategorized';
      if (!acc[cat]) acc[cat] = [];
      acc[cat].push(macro);
      return acc;
    },
    {} as Record<string, MacroEntry[]>
  );
}

/**
 * Validate macro parameters against a MacroParam definition
 * @param params - Record of parameter name-value pairs
 * @param definition - Array of MacroParam definitions
 * @returns Object with validation results { valid: boolean, errors: string[] }
 */
export function validateMacroParams(
  params: Record<string, unknown>,
  definition: MacroParam[]
): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  for (const paramDef of definition) {
    const value = params[paramDef.name];

    // Check required parameters
    if (paramDef.required && value === undefined) {
      errors.push(`Missing required parameter: ${paramDef.name}`);
      continue;
    }

    // Type validation
    if (value !== undefined) {
      const actualType = inferParamType(value);
      if (actualType !== paramDef.type) {
        errors.push(
          `Parameter ${paramDef.name} has type ${actualType}, expected ${paramDef.type}`
        );
      }
    }
  }

  return {
    valid: errors.length === 0,
    errors,
  };
}
