import React from 'react'
import './Input.css'

export type InputSize = 'sm' | 'md' | 'lg'

export interface InputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'size'> {
  label?: string
  size?: InputSize
  error?: string
  helperText?: string
}

export const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ label, size = 'md', error, helperText, id, ...props }, ref) => {
    const inputId = id || `input-${Math.random().toString(36).substr(2, 9)}`
    const sizeClass = `input-${size}`
    const errorClass = error ? 'input-error' : ''

    return (
      <div className="input-wrapper">
        {label && (
          <label htmlFor={inputId} className="input-label">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`input ${sizeClass} ${errorClass}`}
          {...props}
        />
        {error && <div className="input-error-message">{error}</div>}
        {helperText && !error && <div className="input-helper-text">{helperText}</div>}
      </div>
    )
  }
)

Input.displayName = 'Input'
