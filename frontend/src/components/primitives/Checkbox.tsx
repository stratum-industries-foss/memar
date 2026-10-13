import React from 'react'
import './Checkbox.css'

export interface CheckboxProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string
}

export const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
  ({ label, id, ...props }, ref) => {
    const checkboxId = id || `checkbox-${Math.random().toString(36).substr(2, 9)}`

    return (
      <div className="checkbox-wrapper">
        <input
          ref={ref}
          type="checkbox"
          id={checkboxId}
          className="checkbox"
          {...props}
        />
        {label && (
          <label htmlFor={checkboxId} className="checkbox-label">
            {label}
          </label>
        )}
      </div>
    )
  }
)

Checkbox.displayName = 'Checkbox'
