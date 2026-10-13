import React, { ReactNode } from 'react'
import './Button.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  icon?: ReactNode
  children: ReactNode
  loading?: boolean
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'primary', size = 'md', icon, children, loading = false, disabled, ...props }, ref) => {
    const variantClass = `btn-${variant}`
    const sizeClass = `btn-${size}`
    const disabledClass = disabled || loading ? 'btn-disabled' : ''

    return (
      <button
        ref={ref}
        className={`btn ${variantClass} ${sizeClass} ${disabledClass}`}
        disabled={disabled || loading}
        {...props}
      >
        {icon && <span className="btn-icon">{icon}</span>}
        {children}
      </button>
    )
  }
)

Button.displayName = 'Button'
