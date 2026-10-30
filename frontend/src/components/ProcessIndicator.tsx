'use client';

import { useState, useEffect, useCallback, forwardRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Loader2, CheckCircle, XCircle, ChevronDown, ChevronUp } from 'lucide-react';
import type { ProcessStep, ProcessStepStatus } from '@/hooks/useLeoClient';

// =============================================================================
// TYPES
// =============================================================================

interface ProcessIndicatorProps {
  steps: ProcessStep[];
  isRequestComplete: boolean;
  onClear?: () => void;
}

// =============================================================================
// STEP ICON COMPONENT
// =============================================================================

const StepIcon = ({ status }: { status: ProcessStepStatus }) => {
  switch (status) {
    case 'running':
      return <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />;
    case 'done':
      return <CheckCircle className="w-4 h-4 text-emerald-400" />;
    case 'error':
      return <XCircle className="w-4 h-4 text-red-400" />;
    case 'pending':
    default:
      return <div className="w-4 h-4 rounded-full border-2 border-gray-600" />;
  }
};

// =============================================================================
// STEP ITEM COMPONENT (wrapped with forwardRef for framer-motion)
// =============================================================================

const StepItem = forwardRef<HTMLDivElement, { step: ProcessStep; index: number }>(
  ({ step, index }, ref) => {
    const isRunning = step.status === 'running';
    const isDone = step.status === 'done';
    const isError = step.status === 'error';

    return (
      <motion.div
        ref={ref}
        initial={{ opacity: 0, x: -20, height: 0 }}
        animate={{ opacity: 1, x: 0, height: 'auto' }}
        exit={{ opacity: 0, x: 20, height: 0 }}
        transition={{ 
          duration: 0.3,
          delay: index * 0.05,
          ease: [0.25, 0.1, 0.25, 1]
        }}
        className={`flex items-center gap-3 px-3 py-2 rounded-lg transition-all duration-300 ${
          isRunning 
            ? 'bg-blue-500/10 border border-blue-500/20' 
            : isDone 
              ? 'bg-emerald-500/5 border border-emerald-500/10' 
              : isError
                ? 'bg-red-500/10 border border-red-500/20'
                : 'bg-gray-500/5 border border-gray-500/10'
        }`}
      >
        <StepIcon status={step.status} />
        
        <motion.span 
          className={`text-sm flex-1 transition-colors duration-300 ${
            isRunning 
              ? 'text-white' 
              : isDone 
                ? 'text-gray-400' 
                : isError
                  ? 'text-red-300'
                  : 'text-gray-500'
          }`}
          animate={{ opacity: isDone ? 0.7 : 1 }}
        >
          {step.message}
        </motion.span>
        
        {/* Elapsed time indicator for running steps */}
        {isRunning && (
          <motion.div 
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="flex gap-0.5"
          >
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
            <span className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
          </motion.div>
        )}
      </motion.div>
    );
  }
);

StepItem.displayName = 'StepItem';

// =============================================================================
// COLLAPSED BADGE COMPONENT
// =============================================================================

const CompleteBadge = ({ stepCount, onClick }: { stepCount: number; onClick: () => void }) => (
  <motion.button
    initial={{ opacity: 0, scale: 0.9, y: -10 }}
    animate={{ opacity: 1, scale: 1, y: 0 }}
    exit={{ opacity: 0, scale: 0.9, y: -10 }}
    transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
    onClick={onClick}
    className="flex items-center gap-2 px-4 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-full backdrop-blur-xl hover:bg-emerald-500/20 transition-colors cursor-pointer"
  >
    <CheckCircle className="w-4 h-4 text-emerald-400" />
    <span className="text-sm text-emerald-300 font-medium">
      Request Complete
    </span>
    <span className="text-xs text-emerald-500">
      {stepCount} steps
    </span>
    <ChevronDown className="w-3 h-3 text-emerald-400" />
  </motion.button>
);

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function ProcessIndicator({ 
  steps, 
  isRequestComplete,
  onClear 
}: ProcessIndicatorProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [showSteps, setShowSteps] = useState(true);
  
  // Auto-collapse after request completes
  useEffect(() => {
    if (isRequestComplete && steps.length > 0) {
      const timer = setTimeout(() => {
        setIsCollapsed(true);
      }, 5000); // 5 seconds delay before collapsing
      
      return () => clearTimeout(timer);
    }
  }, [isRequestComplete, steps.length]);
  
  // Reset collapsed state when new steps come in
  useEffect(() => {
    if (steps.some(s => s.status === 'running')) {
      setIsCollapsed(false);
      setShowSteps(true);
    }
  }, [steps]);
  
  // Handle expand from badge
  const handleExpand = useCallback(() => {
    setIsCollapsed(false);
    setShowSteps(true);
  }, []);
  
  // Handle collapse toggle
  const handleToggle = useCallback(() => {
    if (isCollapsed) {
      handleExpand();
    } else {
      setIsCollapsed(true);
    }
  }, [isCollapsed, handleExpand]);
  
  // Don't render if no steps
  if (steps.length === 0) return null;
  
  const runningCount = steps.filter(s => s.status === 'running').length;
  const completedCount = steps.filter(s => s.status === 'done').length;

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-auto">
      <AnimatePresence mode="wait">
        {isCollapsed ? (
          <CompleteBadge 
            key="badge"
            stepCount={steps.length} 
            onClick={handleExpand} 
          />
        ) : (
          <motion.div
            key="panel"
            initial={{ opacity: 0, y: -20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ duration: 0.3, ease: [0.25, 0.1, 0.25, 1] }}
            className="min-w-[320px] max-w-[420px] bg-black/60 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-white/[0.02]">
              <div className="flex items-center gap-3">
                {runningCount > 0 ? (
                  <motion.div 
                    animate={{ rotate: 360 }}
                    transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
                    className="w-5 h-5 rounded-full border-2 border-transparent border-t-blue-400 border-r-blue-400"
                  />
                ) : (
                  <CheckCircle className="w-5 h-5 text-emerald-400" />
                )}
                <span className="text-sm font-medium text-white">
                  {runningCount > 0 ? 'Processing...' : 'Complete'}
                </span>
              </div>
              
              <div className="flex items-center gap-2">
                {/* Progress indicator */}
                <span className="text-xs text-gray-500">
                  {completedCount}/{steps.length}
                </span>
                
                {/* Collapse button */}
                <button
                  onClick={handleToggle}
                  className="p-1 rounded-md hover:bg-white/10 transition-colors"
                  aria-label={isCollapsed ? 'Expand' : 'Collapse'}
                >
                  <ChevronUp className="w-4 h-4 text-gray-400" />
                </button>
              </div>
            </div>
            
            {/* Steps List */}
            <AnimatePresence>
              {showSteps && (
                <motion.div 
                  initial={{ height: 0 }}
                  animate={{ height: 'auto' }}
                  exit={{ height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="p-3 space-y-2 max-h-[300px] overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
                    <AnimatePresence mode="popLayout">
                      {steps.map((step, index) => (
                        <StepItem key={step.id} step={step} index={index} />
                      ))}
                    </AnimatePresence>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            
            {/* Footer with clear button when complete */}
            {isRequestComplete && onClear && (
              <motion.div 
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="px-4 py-2 border-t border-white/5 bg-white/[0.02]"
              >
                <button
                  onClick={onClear}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                >
                  Clear
                </button>
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}