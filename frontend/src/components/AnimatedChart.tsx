import React from 'react';
import { motion } from 'framer-motion';

interface AnimatedChartProps {
  children: React.ReactNode;
  delay?: number;
}

/**
 * Wraps Recharts components with fade-in animation.
 * Use this to animate chart entrance.
 *
 * Usage:
 * <AnimatedChart>
 *   <LineChart data={data}>
 *     ...
 *   </LineChart>
 * </AnimatedChart>
 */
export const AnimatedChart: React.FC<AnimatedChartProps> = ({ children, delay = 0 }) => {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{
        duration: 0.6,
        delay,
        ease: 'easeOut',
        type: 'tween',
      }}
    >
      {children}
    </motion.div>
  );
};

export default AnimatedChart;
