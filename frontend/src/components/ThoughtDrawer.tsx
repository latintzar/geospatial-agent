'use client';

import { useEffect, useRef } from 'react';
import { X, Brain, Loader2, MapPin, Database, AlertCircle, CheckCircle2 } from 'lucide-react';
import type { ThoughtLogEntry } from '@/hooks/useLeoClient';

// =============================================================================
// PROPS
// =============================================================================

interface ThoughtDrawerProps {
  isOpen: boolean;
  onClose: () => void;
  thinkingLog: ThoughtLogEntry[];
  isThinking: boolean;
  currentMessage?: string;
}

// =============================================================================
// ICON MAPPING
// =============================================================================

const getThoughtIcon = (message: string, type: ThoughtLogEntry['type']) => {
  if (type === 'error') return <AlertCircle className="w-3.5 h-3.5 text-red-400" />;
  
  // Parse message content for specific icons
  const lowerMessage = message.toLowerCase();
  
  if (lowerMessage.includes('flying') || lowerMessage.includes('📍')) {
    return <MapPin className="w-3.5 h-3.5 text-cyan-400" />;
  }
  if (lowerMessage.includes('layer') || lowerMessage.includes('📊')) {
    return <Database className="w-3.5 h-3.5 text-emerald-400" />;
  }
  if (lowerMessage.includes('complete') || lowerMessage.includes('✅')) {
    return <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />;
  }
  if (lowerMessage.includes('fetching') || lowerMessage.includes('searching')) {
    return <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />;
  }
  if (lowerMessage.includes('analyzing') || lowerMessage.includes('targeting')) {
    return <Brain className="w-3.5 h-3.5 text-purple-400" />;
  }
  
  return <Brain className="w-3.5 h-3.5 text-gray-400" />;
};

// Clean emoji prefixes from messages for cleaner display
const cleanMessage = (message: string): string => {
  return message.replace(/^[📍📊❌✅🔍🎯👥🌾💰🛣️📦📰]\s*/, '');
};

// =============================================================================
// COMPONENT
// =============================================================================

export const ThoughtDrawer = ({
  isOpen,
  onClose,
  thinkingLog,
  isThinking,
  currentMessage,
}: ThoughtDrawerProps) => {
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevLogLength = useRef(thinkingLog.length);

  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    if (thinkingLog.length > prevLogLength.current && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
    prevLogLength.current = thinkingLog.length;
  }, [thinkingLog.length]);

  // Don't render if not open and not thinking
  if (!isOpen && !isThinking) return null;

  return (
    <>
      {/* Backdrop */}
      <div 
        className={`fixed inset-0 bg-black/50 backdrop-blur-sm z-40 transition-opacity duration-300 ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        onClick={onClose}
        aria-hidden="true"
      />
      
      {/* Drawer */}
      <div 
        className={`fixed right-0 top-0 h-full w-[380px] bg-[#0a0a0a] border-l border-stone-800/50 z-50 flex flex-col transform transition-transform duration-300 ease-out ${
          isOpen ? 'translate-x-0' : 'translate-x-full'
        }`}
        role="dialog"
        aria-label="Agent Thinking Process"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-stone-800/50">
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-purple-500/20 to-blue-500/20 flex items-center justify-center">
              <Brain className="w-3.5 h-3.5 text-purple-400" />
            </div>
            <span className="font-medium text-white text-sm">Thinking Process</span>
            {isThinking && (
              <div className="flex items-center gap-1.5 px-2 py-0.5 bg-blue-500/10 rounded-full">
                <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
                <span className="text-[10px] text-blue-400 font-medium">LIVE</span>
              </div>
            )}
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg hover:bg-stone-800 flex items-center justify-center transition-colors"
            aria-label="Close drawer"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && onClose()}
          >
            <X className="w-4 h-4 text-stone-400" />
          </button>
        </div>

        {/* Content */}
        <div 
          ref={scrollRef}
          className="flex-1 overflow-y-auto px-4 py-3 space-y-2"
        >
          {thinkingLog.length === 0 && !isThinking ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center text-stone-500 text-sm">
                <Brain className="w-8 h-8 mx-auto mb-2 opacity-50" />
                <p>No thoughts yet</p>
                <p className="text-xs mt-1">Send a message to see the agent&apos;s thinking process</p>
              </div>
            </div>
          ) : (
            <>
              {/* Thought entries */}
              {thinkingLog.map((entry, index) => (
                <div 
                  key={entry.id}
                  className={`flex items-start gap-2.5 py-2 px-3 rounded-lg animate-fadeIn ${
                    entry.type === 'error' 
                      ? 'bg-red-500/10 border border-red-500/20' 
                      : entry.type === 'tool'
                        ? 'bg-stone-800/50'
                        : 'bg-stone-900/50'
                  }`}
                  style={{ animationDelay: `${index * 50}ms` }}
                >
                  <div className="mt-0.5 flex-shrink-0">
                    {getThoughtIcon(entry.message, entry.type)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className={`text-sm ${
                      entry.type === 'error' ? 'text-red-300' : 'text-stone-300'
                    }`}>
                      {cleanMessage(entry.message)}
                    </p>
                    <p className="text-[10px] text-stone-600 mt-0.5">
                      {entry.timestamp.toLocaleTimeString()}
                    </p>
                  </div>
                </div>
              ))}
              
              {/* Current thinking indicator */}
              {isThinking && (
                <div className="flex items-start gap-2.5 py-2 px-3 rounded-lg bg-blue-500/5 border border-blue-500/20">
                  <div className="mt-0.5 flex-shrink-0">
                    <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm text-blue-300">Processing...</p>
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Streamed Text Preview */}
        {currentMessage && (
          <div className="border-t border-stone-800/50 px-4 py-3 max-h-[200px] overflow-y-auto">
            <div className="text-xs text-stone-500 mb-2 flex items-center gap-1.5">
              <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
              Generating response...
            </div>
            <p className="text-sm text-stone-300 whitespace-pre-wrap">
              {currentMessage}
              <span className="inline-block w-1.5 h-4 bg-emerald-400 ml-0.5 animate-pulse rounded-sm" />
            </p>
          </div>
        )}

        {/* Footer */}
        <div className="px-4 py-2 border-t border-stone-800/50">
          <div className="flex items-center justify-between text-[10px] text-stone-600">
            <span>{thinkingLog.length} step{thinkingLog.length !== 1 ? 's' : ''}</span>
            <span>SSE Streaming</span>
          </div>
        </div>
      </div>
    </>
  );
};

export default ThoughtDrawer;
