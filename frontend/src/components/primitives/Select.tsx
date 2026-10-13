import React from 'react'
import './Select.css'

export interface SelectOption {
  value: string | number
  label: string
}

export type SelectSize = 'sm' | 'md' | 'lg'

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label?: string
  size?: SelectSize
  options: SelectOption[]
  placeholder?: string
  error?: string
}

export const Select = React.forwardRef<HTMLSelectElement, SelectProps>(
  ({ label, size = 'md', options, placeholder, error, id, ...props }, ref) => {
    const selectId = id || `select-${Math.random().toString(36).substr(2, 9)}`
    const sizeClass = `select-${size}`
    const errorClass = error ? 'select-error' : ''

    return (
      <div className="select-wrapper">
        {label && (
          <label htmlFor={selectId} className="select-label">
            {label}
          </label>
        )}
        <select
          ref={ref}
          id={selectId}
          className={`select ${sizeClass} ${errorClass}`}
          {...props}
        >
          {placeholder && <option value="">{placeholder}</option>}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        {error && <div className="select-error-message">{error}</div>}
      </div>
    )
  }
)

Select.displayName = 'Select'
