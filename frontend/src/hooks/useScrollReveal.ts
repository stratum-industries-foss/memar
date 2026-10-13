import { useInView } from 'framer-motion';
import { useRef } from 'react';

export const useScrollReveal = () => {
  const ref = useRef(null);
  const isInView = useInView(ref, {
    once: true,
    amount: 0.1, // Trigger when 10% of element is visible
    margin: '0px 0px -50px 0px' // Start animation 50px before element enters viewport
  });

  return { ref, isInView };
};

// Variant definitions for scroll reveal animations
export const revealVariants = {
  hidden: {
    opacity: 0,
    y: 30,
  },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.6,
      ease: 'easeOut',
      type: 'tween',
    },
  },
};

// Staggered children animation for card grids
export const containerVariants = {
  hidden: { opacity: 0 },
  visible: {
    opacity: 1,
    transition: {
      staggerChildren: 0.08,
      delayChildren: 0.1,
    },
  },
};

export const childVariants = {
  hidden: { opacity: 0, y: 20 },
  visible: {
    opacity: 1,
    y: 0,
    transition: {
      duration: 0.5,
      ease: 'easeOut',
      type: 'tween',
    },
  },
};
