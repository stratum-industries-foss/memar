import React from 'react';
import styles from './ShimmerLoader.module.css';

interface ShimmerLoaderProps {
  rows?: number;
  columns?: number;
  height?: string;
}

export const ShimmerLoader: React.FC<ShimmerLoaderProps> = ({
  rows = 3,
  columns = 2,
  height = '200px',
}) => {
  const skeletons = Array.from({ length: rows * columns });

  return (
    <div className={styles.shimmerGrid}>
      {skeletons.map((_, idx) => (
        <div
          key={idx}
          className={styles.shimmerItem}
          style={{ height }}
        >
          <div className={styles.shimmerContent}>
            <div className={styles.shimmerTitle} />
            <div className={styles.shimmerLine} />
            <div className={styles.shimmerLine} style={{ width: '80%' }} />
          </div>
        </div>
      ))}
    </div>
  );
};

export default ShimmerLoader;
