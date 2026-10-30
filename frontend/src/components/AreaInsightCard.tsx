'use client';

import { memo } from 'react';
import type { AreaCluster } from '@/lib/types';

// =============================================================================
// MAIN COMPONENT
// =============================================================================

interface AreaInsightCardProps {
  cluster: AreaCluster;
  isVisible: boolean;
}

function AreaInsightCardInner({ cluster, isVisible }: AreaInsightCardProps) {
  if (!isVisible || !cluster) {
    return null;
  }
  
  return (
    <div
      className={`
        fixed bottom-6 left-6 z-50
        w-80 max-w-[calc(100vw-3rem)]
        bg-gray-900/95 backdrop-blur-md
        border border-gray-700/50
        rounded-xl shadow-2xl
        transform transition-all duration-300 ease-out
        ${isVisible 
          ? 'translate-x-0 opacity-100' 
          : '-translate-x-4 opacity-0 pointer-events-none'
        }
      `}
    >
      {/* Description */}
      <div className="px-4 py-3">
        <p className="text-sm text-gray-200 leading-relaxed">
          {cluster.description || 'Area matching your search criteria.'}
        </p>
      </div>
      
      {/* Subtle gradient accent */}
      <div className="absolute inset-x-0 top-0 h-0.5 bg-gradient-to-r from-emerald-500/50 via-cyan-500/50 to-emerald-500/50 rounded-t-xl" />
    </div>
  );
}

export const AreaInsightCard = memo(AreaInsightCardInner);
export default AreaInsightCard;
