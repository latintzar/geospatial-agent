'use client';

import { useState, useCallback, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { 
  Loader2, 
  CheckCircle, 
  XCircle, 
  Circle, 
  ChevronDown, 
  ChevronRight,
  Brain,
  Sparkles,
} from 'lucide-react';
import type { PlanStep } from '@/hooks/useLeoClient';
import type { PlanStepLog } from '@/lib/types';

// =============================================================================
// TYPES
// =============================================================================

interface PlanCardProps {
  steps: PlanStep[];
  currentStepId: string | null;
  isActive: boolean;
  isComplete: boolean;
  onClose?: () => void;
}

// =============================================================================
// STEP STATUS ICON
// =============================================================================

const StepStatusIcon = ({ status }: { status: PlanStep['status'] }) => {
  switch (status) {
    case 'running':
      return (
        <motion.div
          animate={{ rotate: 360 }}
          transition={{ duration: 1, repeat: Infinity, ease: 'linear' }}
        >
          <Loader2 className="w-5 h-5 text-blue-400" />
        </motion.div>
      );
    case 'completed':
      return <CheckCircle className="w-5 h-5 text-emerald-400" />;
    case 'failed':
      return <XCircle className="w-5 h-5 text-red-400" />;
    case 'pending':
    default:
      return <Circle className="w-5 h-5 text-gray-600" />;
  }
};

// =============================================================================
// LOG TYPE ICON
// =============================================================================

const LogTypeIcon = ({ type }: { type: PlanStepLog['type'] }) => {
  switch (type) {
    case 'tool_start':
      return <span className="text-blue-400">▶</span>;
    case 'success':
      return <span className="text-emerald-400">✓</span>;
    case 'error':
      return <span className="text-red-400">✗</span>;
    case 'thinking':
    default:
      return <span className="text-gray-500">•</span>;
  }
};

// =============================================================================
// SINGLE STEP COMPONENT
// =============================================================================

interface StepItemProps {
  step: PlanStep;
  isCurrentStep: boolean;
  stepIndex: number;
}

const StepItem = ({ step, isCurrentStep, stepIndex }: StepItemProps) => {
  const [isExpanded, setIsExpanded] = useState(isCurrentStep || step.status === 'running');
  const hasLogs = step.logs.length > 0;
  
  // Auto-expand running steps, auto-collapse completed steps
  useEffect(() => {
    if (step.status === 'running') {
      setIsExpanded(true);
    } else if (step.status === 'completed' && !isCurrentStep) {
      // Give a brief delay before collapsing
      const timer = setTimeout(() => setIsExpanded(false), 500);
      return () => clearTimeout(timer);
    }
  }, [step.status, isCurrentStep]);
  
  const handleToggle = useCallback(() => {
    if (hasLogs) {
      setIsExpanded(prev => !prev);
    }
  }, [hasLogs]);
  
  const isRunning = step.status === 'running';
  const isCompleted = step.status === 'completed';
  const isFailed = step.status === 'failed';

  return (
    <motion.div
      initial={{ opacity: 0, x: -10 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: stepIndex * 0.1 }}
      className="relative"
    >
      {/* Vertical Connection Line */}
      {stepIndex > 0 && (
        <div 
          className={`absolute left-[10px] -top-3 w-0.5 h-3 ${
            isCompleted || isRunning ? 'bg-emerald-500/50' : 'bg-gray-700'
          }`}
        />
      )}
      
      {/* Step Header */}
      <button
        onClick={handleToggle}
        className={`w-full flex items-center gap-3 py-2 px-1 rounded-lg transition-all ${
          hasLogs ? 'cursor-pointer hover:bg-white/5' : 'cursor-default'
        }`}
      >
        {/* Status Icon */}
        <StepStatusIcon status={step.status} />
        
        {/* Step Title */}
        <span className={`flex-1 text-left text-sm font-medium transition-colors ${
          isRunning 
            ? 'text-white' 
            : isCompleted 
              ? 'text-gray-400' 
              : isFailed
                ? 'text-red-300'
                : 'text-gray-500'
        }`}>
          {step.title}
        </span>
        
        {/* Expand/Collapse Chevron */}
        {hasLogs && (
          <motion.div
            animate={{ rotate: isExpanded ? 90 : 0 }}
            transition={{ duration: 0.2 }}
          >
            <ChevronRight className="w-4 h-4 text-gray-500" />
          </motion.div>
        )}
        
        {/* Running Indicator Dots */}
        {isRunning && (
          <div className="flex gap-0.5">
            <motion.span 
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.5, repeat: Infinity, delay: 0 }}
              className="w-1 h-1 bg-blue-400 rounded-full"
            />
            <motion.span 
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.5, repeat: Infinity, delay: 0.2 }}
              className="w-1 h-1 bg-blue-400 rounded-full"
            />
            <motion.span 
              animate={{ opacity: [0.3, 1, 0.3] }}
              transition={{ duration: 1.5, repeat: Infinity, delay: 0.4 }}
              className="w-1 h-1 bg-blue-400 rounded-full"
            />
          </div>
        )}
      </button>
      
      {/* Nested Logs (Collapsible) */}
      <AnimatePresence>
        {isExpanded && hasLogs && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="overflow-hidden"
          >
            <div className="ml-6 pl-4 border-l-2 border-gray-700/50 space-y-1 py-1">
              {step.logs.map((log, logIndex) => (
                <motion.div
                  key={log.id}
                  initial={{ opacity: 0, x: -5 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: logIndex * 0.05 }}
                  className="flex items-start gap-2 text-xs font-mono"
                >
                  <LogTypeIcon type={log.type} />
                  <span className={`flex-1 ${
                    log.type === 'success' 
                      ? 'text-emerald-400/70' 
                      : log.type === 'error'
                        ? 'text-red-400/70'
                        : log.type === 'tool_start'
                          ? 'text-blue-300/70'
                          : 'text-gray-500'
                  }`}>
                    {log.message}
                  </span>
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

// =============================================================================
// MAIN PLAN CARD COMPONENT
// =============================================================================

export default function PlanCard({ 
  steps, 
  currentStepId, 
  isActive,
  isComplete,
  onClose 
}: PlanCardProps) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  
  // Auto-collapse after completion (with delay)
  useEffect(() => {
    if (isComplete && steps.length > 0) {
      const timer = setTimeout(() => {
        setIsCollapsed(true);
      }, 8000); // 8 seconds delay
      return () => clearTimeout(timer);
    }
  }, [isComplete, steps.length]);
  
  // Reset collapsed state when new plan starts
  useEffect(() => {
    if (isActive && steps.some(s => s.status === 'running')) {
      setIsCollapsed(false);
    }
  }, [isActive, steps]);
  
  // Don't render if no steps
  if (steps.length === 0) return null;
  
  const completedCount = steps.filter(s => s.status === 'completed').length;
  const totalSteps = steps.length;
  const progress = (completedCount / totalSteps) * 100;

  return (
    <div className="fixed top-4 left-1/2 -translate-x-1/2 z-50 pointer-events-auto">
      <AnimatePresence mode="wait">
        {isCollapsed ? (
          // Collapsed Badge View
          <motion.button
            key="collapsed"
            initial={{ opacity: 0, scale: 0.9, y: -10 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.9, y: -10 }}
            onClick={() => setIsCollapsed(false)}
            className="flex items-center gap-3 px-4 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-full backdrop-blur-xl hover:bg-emerald-500/20 transition-colors"
          >
            <CheckCircle className="w-4 h-4 text-emerald-400" />
            <span className="text-sm text-emerald-300 font-medium">Plan Complete</span>
            <span className="text-xs text-emerald-500/70">{totalSteps} steps</span>
            <ChevronDown className="w-3 h-3 text-emerald-400" />
          </motion.button>
        ) : (
          // Expanded Card View
          <motion.div
            key="expanded"
            initial={{ opacity: 0, y: -20, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            className="min-w-[360px] max-w-[480px] bg-black/70 backdrop-blur-xl border border-white/10 rounded-2xl shadow-2xl shadow-black/50 overflow-hidden"
          >
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gradient-to-r from-purple-500/10 to-blue-500/10">
              <div className="flex items-center gap-3">
                {isActive ? (
                  <motion.div
                    animate={{ rotate: 360 }}
                    transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
                  >
                    <Brain className="w-5 h-5 text-purple-400" />
                  </motion.div>
                ) : (
                  <Sparkles className="w-5 h-5 text-emerald-400" />
                )}
                <span className="text-sm font-semibold text-white">
                  {isActive ? 'Executing Plan' : 'Plan Complete'}
                </span>
              </div>
              
              <div className="flex items-center gap-3">
                {/* Progress */}
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-gray-800 rounded-full overflow-hidden">
                    <motion.div 
                      className="h-full bg-gradient-to-r from-purple-500 to-emerald-500"
                      initial={{ width: 0 }}
                      animate={{ width: `${progress}%` }}
                      transition={{ duration: 0.3 }}
                    />
                  </div>
                  <span className="text-xs text-gray-500">{completedCount}/{totalSteps}</span>
                </div>
                
                {/* Collapse Button */}
                {isComplete && (
                  <button
                    onClick={() => setIsCollapsed(true)}
                    className="p-1 rounded-md hover:bg-white/10 transition-colors"
                  >
                    <ChevronDown className="w-4 h-4 text-gray-400" />
                  </button>
                )}
              </div>
            </div>
            
            {/* Steps List */}
            <div className="p-4 space-y-1 max-h-[400px] overflow-y-auto scrollbar-thin scrollbar-thumb-gray-700 scrollbar-track-transparent">
              {steps.map((step, index) => (
                <StepItem 
                  key={step.id} 
                  step={step} 
                  isCurrentStep={step.id === currentStepId}
                  stepIndex={index}
                />
              ))}
            </div>
            
            {/* Footer (Optional - shows when complete) */}
            {isComplete && onClose && (
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="px-4 py-2 border-t border-white/5 bg-white/[0.02] flex justify-end"
              >
                <button
                  onClick={onClose}
                  className="text-xs text-gray-500 hover:text-gray-300 transition-colors"
                >
                  Dismiss
                </button>
              </motion.div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
