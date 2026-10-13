import React, { ReactNode } from 'react'
import './Badge.css'

export type BadgeVariant = 'success' | 'danger' | 'warning' | 'info'
export type BadgeSize = 'sm' | 'md'

export interface BadgeProps {
  variant?: BadgeVariant
  size?: BadgeSize
  children: ReactNode
}

export const Badge: React.FC<BadgeProps> = ({ variant = 'info', size = 'md', children }) => {
  const variantClass = `badge-${variant}`
  const sizeClass = `badge-${size}`

  return (
    <span className={`badge ${variantClass} ${sizeClass}`}>
      {children}
    </span>
  )
}
