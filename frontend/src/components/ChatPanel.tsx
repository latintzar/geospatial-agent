'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage, AgentLayer, StreamingState, ToolCall, ModelId } from '@/lib/types';
import { 
  Layers, 
  Copy, 
  Check, 
  Loader2, 
  ChevronDown, 
  ChevronRight,
  Sparkles,
  CheckCircle,
  XCircle,
} from 'lucide-react';

interface ChatPanelProps {
  messages: ChatMessage[];
  loading: boolean;
  onSendMessage: (message: string) => void;
  layers: AgentLayer[];
  onToggleLayer?: (layerId: string) => void;
  streamingState?: StreamingState;
  selectedModel?: ModelId;
  onSelectModel?: (model: ModelId) => void;
}

// Pretty tool names and descriptions for Cursor-style display
const TOOL_DISPLAY: Record<string, { name: string; icon: string; getIntent: (args: Record<string, unknown>) => string }> = {
  tool_define_aoi: {
    name: 'Define Area',
    icon: '📍',
    getIntent: (args) => `Setting focus area: "${args.query || 'location'}"`,
  },
  tool_query_matrix: {
    name: 'Query Strategic Data',
    icon: '🎯',
    getIntent: (args) => `Finding hotspots with filters: ${args.filters || 'all metrics'}`,
  },
  tool_search_entities: {
    name: 'Search Entities',
    icon: '🔍',
    getIntent: (args) => `Searching for "${args.query}" via ${args.source || 'athena'}`,
  },
  tool_get_population: {
    name: 'Get Population',
    icon: '👥',
    getIntent: () => 'Fetching population density from WorldPop',
  },
  tool_fetch_crops: {
    name: 'Fetch Agriculture',
    icon: '🌾',
    getIntent: (args) => `Getting ${args.crop || 'crop'} data for ${args.country || 'region'}`,
  },
  tool_fetch_wealth: {
    name: 'Fetch Wealth Index',
    icon: '💰',
    getIntent: (args) => `Loading wealth data for ${args.country_iso3 || 'region'}`,
  },
  tool_fetch_weather_risk: {
    name: 'Weather Risk',
    icon: '🌤️',
    getIntent: () => 'Checking climate and weather risk factors',
  },
  tool_calculate_route: {
    name: 'Calculate Route',
    icon: '🛣️',
    getIntent: () => 'Computing optimal driving route',
  },
  tool_fetch_trade: {
    name: 'Trade Flows',
    icon: '📦',
    getIntent: (args) => `Fetching trade data for ${args.reporter_iso3 || 'country'}`,
  },
  tool_fetch_news: {
    name: 'News & Events',
    icon: '📰',
    getIntent: (args) => `Searching news for "${args.query || 'events'}"`,
  },
  tool_spatial_join_proximity: {
    name: 'Spatial Analysis',
    icon: '📊',
    getIntent: (args) => `Finding ${args.target_category} near ${args.reference_category}`,
  },
  tool_create_plan: {
    name: 'Planning',
    icon: '🧠',
    getIntent: () => 'Creating execution plan',
  },
};

function getPrettyToolInfo(toolName: string, args: Record<string, unknown>) {
  const info = TOOL_DISPLAY[toolName];
  if (!info) {
    return {
      displayName: toolName.replace('tool_', '').replace(/_/g, ' '),
      icon: '⚙️',
      intent: `Executing ${toolName}`,
    };
  }
  return {
    displayName: info.name,
    icon: info.icon,
    intent: info.getIntent(args),
  };
}

/**
 * Parse raw response to extract tool calls
 * Handles both array format (new) and dictionary format (legacy)
 */
function extractToolCalls(rawResponse: Record<string, unknown> | undefined): ToolCall[] {
  if (!rawResponse) return [];
  
  const toolCalls: ToolCall[] = [];
  const toolsUsed = rawResponse.tools_used as string[] | undefined;
  const layersData = rawResponse.layers;
  
  // New format: layers is an array
  if (Array.isArray(layersData)) {
    for (const layer of layersData) {
      const layerObj = layer as { name?: string; args?: Record<string, unknown>; count?: number; timestamp?: string };
      toolCalls.push({
        name: layerObj.name || 'unknown',
        args: layerObj.args || {},
        result: layerObj.count !== undefined ? `${layerObj.count} records` : 'Data returned',
      });
    }
    return toolCalls;
  }
  
  // Legacy format: layers is a dictionary
  if (toolsUsed && layersData && typeof layersData === 'object') {
    const layersDict = layersData as Record<string, { args?: { args?: string; kwargs?: string }; timestamp?: string }>;
    toolsUsed.forEach((toolName) => {
      const layerData = layersDict[toolName];
      toolCalls.push({
        name: toolName,
        args: layerData?.args || {},
        result: layerData ? 'Data returned' : 'No data',
      });
    });
  }
  
  return toolCalls;
}

/**
 * Cursor-style Compact Inline Streaming Indicator
 * Shows tool calls INLINE as they happen - compact, always expanded, scrolls with messages
 */
function LiveStreamingIndicator({ 
  streamingState 
}: { 
  streamingState: StreamingState;
}) {
  const [startTime] = useState(Date.now());
  const [elapsed, setElapsed] = useState(0);

  // Update elapsed time
  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [startTime]);

  const toolCount = streamingState.activeToolCalls.length;
  const currentThinking = streamingState.thinkingMessage || 'Processing...';

  return (
    <div className="space-y-1">
      {/* Compact process log - Cursor style */}
      <div className="text-[11px] text-gray-500 space-y-0.5 font-mono">
        {/* Current status line */}
        <div className="flex items-center gap-1.5">
          <Loader2 className="w-3 h-3 text-blue-400 animate-spin flex-shrink-0" />
          <span className="text-gray-400">{currentThinking}</span>
          <span className="text-gray-600 ml-auto">{elapsed}s</span>
        </div>
        
        {/* Tool calls log - compact inline list */}
        {toolCount > 0 && (
          <div className="pl-4 border-l border-gray-800 ml-1.5 space-y-0.5">
            {streamingState.activeToolCalls.map((tool, index) => {
              const { icon, intent } = getPrettyToolInfo(tool.name, tool.args);
              
              return (
                <div 
                  key={`${tool.name}-${index}`}
                  className="flex items-center gap-1.5 text-[10px] animate-fadeIn"
                >
                  <span className="text-xs flex-shrink-0">{icon}</span>
                  <span className="text-gray-500 truncate">{intent}</span>
                  {tool.status === 'running' && (
                    <Loader2 className="w-2.5 h-2.5 text-blue-400 animate-spin ml-auto flex-shrink-0" />
                  )}
                  {tool.status === 'success' && (
                    <CheckCircle className="w-2.5 h-2.5 text-emerald-500 ml-auto flex-shrink-0" />
                  )}
                  {tool.status === 'error' && (
                    <XCircle className="w-2.5 h-2.5 text-red-500 ml-auto flex-shrink-0" />
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
      
      {/* Streamed text preview (as it comes in) */}
      {streamingState.streamedText && (
        <div className="mt-2 text-gray-200 text-sm">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>
            {streamingState.streamedText}
          </ReactMarkdown>
          <span className="inline-block w-1 h-3.5 bg-emerald-400 ml-0.5 animate-pulse rounded-sm" />
        </div>
      )}
    </div>
  );
}

/**
 * Cursor-style Thinking Indicator (for completed messages)
 */
function ThinkingIndicator({ 
  toolCalls, 
  isExpanded, 
  onToggle,
  thinkingTime 
}: { 
  toolCalls: ToolCall[];
  isExpanded: boolean;
  onToggle: () => void;
  thinkingTime?: number;
}) {
  const hasTools = toolCalls.length > 0;
  
  return (
    <div className="mb-3">
      <button 
        onClick={onToggle}
        className="flex items-center gap-2 text-sm text-gray-400 hover:text-gray-300 transition-colors"
      >
        {isExpanded ? (
          <ChevronDown className="w-4 h-4 text-gray-500" />
        ) : (
          <ChevronRight className="w-4 h-4 text-gray-500" />
        )}
        <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
        <span className="text-gray-300">Thought</span>
        {thinkingTime && <span className="text-gray-500">for {thinkingTime}s</span>}
        {hasTools && <span className="text-gray-500">• {toolCalls.length} tool{toolCalls.length > 1 ? 's' : ''} used</span>}
      </button>
      
      {isExpanded && hasTools && (
        <div className="ml-6 mt-2 space-y-1.5 border-l-2 border-gray-800 pl-3">
          {toolCalls.map((tool, index) => {
            const { displayName, icon, intent } = getPrettyToolInfo(tool.name, tool.args);
            
            return (
            <div 
              key={index}
                className="flex items-start gap-2 text-xs py-1"
            >
                <span className="text-sm mt-0.5">{icon}</span>
              <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-gray-300 font-medium">{displayName}</span>
                    <CheckCircle className="w-3 h-3 text-emerald-400" />
                  </div>
                  <div className="text-gray-500 text-[11px]">{intent}</div>
                {tool.result && (
                    <div className="text-emerald-600 text-[10px] mt-0.5">→ {tool.result}</div>
                )}
              </div>
            </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/**
 * Markdown renderer with custom styling
 */
function MarkdownContent({ content }: { content: string }) {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        // Headers
        h1: ({ children }) => <h1 className="text-xl font-bold text-white mt-4 mb-2">{children}</h1>,
        h2: ({ children }) => <h2 className="text-lg font-semibold text-white mt-3 mb-2">{children}</h2>,
        h3: ({ children }) => <h3 className="text-base font-semibold text-gray-200 mt-2 mb-1">{children}</h3>,
        
        // Paragraphs
        p: ({ children }) => <p className="text-gray-300 leading-relaxed mb-3 last:mb-0">{children}</p>,
        
        // Lists
        ul: ({ children }) => <ul className="list-disc list-inside space-y-1 mb-3 text-gray-300">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal list-inside space-y-1 mb-3 text-gray-300">{children}</ol>,
        li: ({ children }) => <li className="text-gray-300">{children}</li>,
        
        // Code
        code: ({ className, children, ...props }) => {
          const isInline = !className;
          if (isInline) {
            return (
              <code className="px-1.5 py-0.5 bg-[#1a1a1a] text-emerald-400 rounded text-sm font-mono" {...props}>
                {children}
              </code>
            );
          }
          return (
            <code className="block p-3 bg-[#111] rounded-lg text-sm font-mono text-gray-300 overflow-x-auto my-3" {...props}>
              {children}
            </code>
          );
        },
        pre: ({ children }) => <pre className="my-3">{children}</pre>,
        
        // Links
        a: ({ href, children }) => (
          <a href={href} className="text-emerald-400 hover:text-emerald-300 underline" target="_blank" rel="noopener noreferrer">
            {children}
          </a>
        ),
        
        // Bold/Italic
        strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
        em: ({ children }) => <em className="italic text-gray-200">{children}</em>,
        
        // Blockquotes
        blockquote: ({ children }) => (
          <blockquote className="border-l-2 border-emerald-500/50 pl-4 my-3 text-gray-400 italic">
            {children}
          </blockquote>
        ),
        
        // Tables
        table: ({ children }) => (
          <div className="overflow-x-auto my-3">
            <table className="min-w-full text-sm">{children}</table>
          </div>
        ),
        th: ({ children }) => (
          <th className="px-3 py-2 bg-[#111] text-left text-gray-400 font-medium border-b border-gray-800">{children}</th>
        ),
        td: ({ children }) => (
          <td className="px-3 py-2 text-gray-300 border-b border-gray-800/50">{children}</td>
        ),
        
        // Horizontal rule
        hr: () => <hr className="my-4 border-gray-800" />,
      }}
    >
      {content}
    </ReactMarkdown>
  );
}

export default function ChatPanel({
  messages,
  loading,
  onSendMessage,
  layers,
  onToggleLayer,
  streamingState,
  selectedModel = 'gemini-3-flash-preview',
  onSelectModel,
}: ChatPanelProps) {
  const [input, setInput] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Copy raw response to clipboard
  const handleCopyRaw = useCallback(async (message: ChatMessage) => {
    if (!message.rawResponse) return;
    try {
      await navigator.clipboard.writeText(JSON.stringify(message.rawResponse, null, 2));
      setCopiedId(message.id);
      setTimeout(() => setCopiedId(null), 2000);
    } catch (err) {
      console.error('Failed to copy:', err);
    }
  }, []);

  // Toggle tool expansion
  const toggleToolExpansion = useCallback((messageId: string) => {
    setExpandedTools(prev => {
      const next = new Set(prev);
      if (next.has(messageId)) {
        next.delete(messageId);
      } else {
        next.add(messageId);
      }
      return next;
    });
  }, []);

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.style.height = 'auto';
      inputRef.current.style.height = Math.min(inputRef.current.scrollHeight, 120) + 'px';
    }
  }, [input]);

  const handleSubmit = () => {
    if (!input.trim() || loading) return;
    onSendMessage(input.trim());
    setInput('');
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Get layers created by a specific message
  const getMessageLayers = useCallback((message: ChatMessage): AgentLayer[] => {
    if (!message.layers) return [];
    return layers.filter(l => message.layers?.includes(l.id));
  }, [layers]);

  // Compute thinking time (mock based on tools used)
  const getThinkingTime = useCallback((message: ChatMessage): number => {
    const toolCalls = extractToolCalls(message.rawResponse);
    return Math.max(1, Math.round(toolCalls.length * 1.5 + Math.random() * 2));
  }, []);

  return (
    <div className="flex flex-col h-full bg-background">
      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto">
        {/* Empty State */}
        {messages.length === 0 && !loading && (
          <div className="h-full flex items-center justify-center p-8">
            <div className="text-center max-w-md">
              <div className="w-16 h-16 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-teal-600/20 flex items-center justify-center">
                <span className="text-3xl">🌍</span>
              </div>
              <h2 className="text-xl font-semibold text-white mb-2">Welcome to Leo</h2>
              <p className="text-gray-500 text-sm mb-6">
                Explore an authored example using the Leo scorer and synthetic location features.
              </p>
              <div className="space-y-2 text-sm">
                <button 
                  onClick={() => onSendMessage("Find locations similar to Covent Garden")}
                  className="w-full px-4 py-2.5 bg-[#141414] hover:bg-[#1a1a1a] border border-gray-800/50 rounded-xl text-gray-400 hover:text-white text-left transition-colors"
                >
                  &quot;Find locations similar to Covent Garden&quot;
                </button>
                <button 
                  onClick={() => onSendMessage("Show synthetic retail location matches")}
                  className="w-full px-4 py-2.5 bg-[#141414] hover:bg-[#1a1a1a] border border-gray-800/50 rounded-xl text-gray-400 hover:text-white text-left transition-colors"
                >
                  &quot;Show synthetic retail location matches&quot;
                </button>
                <button 
                  onClick={() => onSendMessage("Explain the synthetic location example")}
                  className="w-full px-4 py-2.5 bg-[#141414] hover:bg-[#1a1a1a] border border-gray-800/50 rounded-xl text-gray-400 hover:text-white text-left transition-colors"
                >
                  &quot;Explain the synthetic location example&quot;
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Messages */}
        {messages.length > 0 && (
          <div className="divide-y divide-gray-800/30">
            {messages.map((message) => {
              const isUser = message.role === 'user';
              const toolCalls = extractToolCalls(message.rawResponse);
              const messageLayers = getMessageLayers(message);
              const isToolsExpanded = expandedTools.has(message.id);

              // User messages: bubble style (right-aligned)
              if (isUser) {
                return (
                  <div key={message.id} className="px-6 py-4 bg-background">
                    <div className="flex justify-end">
                      <div className="max-w-[80%] bg-gradient-to-r from-emerald-600 to-teal-600 text-white px-4 py-3 rounded-2xl rounded-br-md">
                        <p className="text-sm">{message.content}</p>
                      </div>
                    </div>
                  </div>
                );
              }

              // Assistant messages: flat rich text (ChatGPT style)
              return (
                <div 
                  key={message.id} 
                  className="px-6 py-5 bg-[#0d0d0d]"
                >
                  {/* Assistant Icon */}
                  <div className="flex items-start gap-4">
                    <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0">
                      <Sparkles className="w-4 h-4 text-white" />
                    </div>

                    <div className="flex-1 min-w-0">
                      {/* Role Label */}
                      <div className="text-xs font-medium text-gray-500 mb-2">Leo</div>

                      {/* Thinking Indicator */}
                      {toolCalls.length > 0 && (
                        <ThinkingIndicator
                          toolCalls={toolCalls}
                          isExpanded={isToolsExpanded}
                          onToggle={() => toggleToolExpansion(message.id)}
                          thinkingTime={getThinkingTime(message)}
                        />
                      )}

                      {/* Message Content */}
                      <div className="prose prose-invert prose-sm max-w-none">
                        <MarkdownContent content={message.content} />
                      </div>

                      {/* Map Layers */}
                      {messageLayers.length > 0 && (
                        <div className="mt-4 pt-4 border-t border-gray-800/50">
                          <div className="flex items-center gap-2 text-xs text-gray-500 mb-3">
                            <Layers className="w-3 h-3" />
                            <span>Added to map</span>
                          </div>
                          <div className="flex flex-wrap gap-2">
                            {messageLayers.map((layer) => (
                              <button
                                key={layer.id}
                                onClick={() => onToggleLayer?.(layer.id)}
                                className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all ${
                                  layer.visible
                                    ? 'bg-white/10 text-white border border-white/20 hover:bg-white/15'
                                    : 'bg-gray-900 text-gray-500 border border-gray-800 hover:border-gray-700'
                                }`}
                              >
                                <div
                                  className="w-2 h-2 rounded-full"
                                  style={{ backgroundColor: layer.visible ? layer.color : '#555' }}
                                />
                                <span>{layer.name}</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Actions */}
                      {message.rawResponse && (
                        <div className="mt-4 flex items-center gap-2">
                          <button
                            onClick={() => handleCopyRaw(message)}
                            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-all ${
                              copiedId === message.id
                                ? 'bg-emerald-500/10 text-emerald-400'
                                : 'text-gray-600 hover:text-gray-400 hover:bg-white/5'
                            }`}
                          >
                            {copiedId === message.id ? (
                              <>
                                <Check className="w-3 h-3" />
                                <span>Copied</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3" />
                                <span>Copy JSON</span>
                              </>
                            )}
                          </button>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}

            {/* Loading State - Compact inline streaming (Cursor-style) */}
            {loading && (
              <div className="px-6 py-4 bg-[#0d0d0d]">
                <div className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <Sparkles className="w-3 h-3 text-white" />
                  </div>
                  <div className="flex-1 min-w-0">
                    {/* Show live streaming state if available */}
                    {streamingState?.isStreaming ? (
                      <LiveStreamingIndicator streamingState={streamingState} />
                    ) : (
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        <Loader2 className="w-3 h-3 text-emerald-500 animate-spin" />
                        <span>Thinking...</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div className="p-4 border-t border-stone-800/50 bg-background">
        <div className="relative max-w-3xl mx-auto">
          {/* Suggestion Chips - shown when no messages */}
          {messages.length === 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              <button
                onClick={() => onSendMessage("Find locations similar to Covent Garden")}
                className="px-3 py-1.5 text-xs bg-stone-800/50 border border-stone-700/50 text-stone-400 rounded-lg hover:bg-stone-700/50 hover:text-white hover:border-stone-600 transition-all"
              >
                🎨 Find locations similar to Covent Garden
              </button>
              <button
                onClick={() => onSendMessage("Show synthetic retail location matches")}
                className="px-3 py-1.5 text-xs bg-stone-800/50 border border-stone-700/50 text-stone-400 rounded-lg hover:bg-stone-700/50 hover:text-white hover:border-stone-600 transition-all"
              >
                🌳 Show synthetic retail location matches
              </button>
            </div>
          )}
          
          {/* Input Container */}
          <div className="relative bg-background-panel border border-stone-800 rounded-xl focus-within:border-stone-600 transition-colors">
            <textarea
              ref={inputRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Try the supported example..."
              rows={1}
              className="w-full px-4 py-3 pr-24 bg-transparent text-white placeholder-stone-600 focus:outline-none resize-none text-sm"
            />
            
            {/* Bottom Bar with Model Selector and Send */}
            <div className="flex items-center justify-between px-3 pb-2">
              {/* Model Selector */}
              {process.env.NEXT_PUBLIC_EXAMPLE_MODE !== 'true' ? (
              <select
                value={selectedModel}
                onChange={(e) => onSelectModel?.(e.target.value as ModelId)}
                className="text-xs bg-transparent text-stone-500 hover:text-stone-300 cursor-pointer focus:outline-none border-none appearance-none pr-4"
                style={{ backgroundImage: `url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' fill='none' viewBox='0 0 20 20'%3e%3cpath stroke='%236b6b6b' stroke-linecap='round' stroke-linejoin='round' stroke-width='1.5' d='M6 8l4 4 4-4'/%3e%3c/svg%3e")`, backgroundPosition: 'right 0 center', backgroundRepeat: 'no-repeat', backgroundSize: '16px' }}
              >
                <option value="gemini-3-flash-preview">Gemini 3 Flash</option>
                <option value="gemini-3-pro-preview">Gemini 3 Pro</option>
              </select>
              ) : <span className="text-xs text-stone-500">Retained example</span>}
              
              {/* Send Button - Cursor style */}
              <button
                onClick={handleSubmit}
                disabled={!input.trim() || loading}
                className={`w-7 h-7 rounded-lg flex items-center justify-center transition-all ${
                  loading 
                    ? 'bg-stone-700 cursor-wait' 
                    : input.trim() 
                      ? 'bg-white text-black hover:bg-stone-200' 
                      : 'bg-stone-800 text-stone-600 cursor-not-allowed'
                }`}
                aria-label="Send message"
              >
                {loading ? (
                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                ) : (
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 2L11 13" />
                    <path d="M22 2L15 22L11 13L2 9L22 2Z" />
                  </svg>
                )}
              </button>
            </div>
          </div>
          
          {/* Context indicator */}
          <div className="flex items-center justify-between mt-2 px-1">
            <span className="text-[10px] text-stone-600">
              {messages.length > 0 ? `${messages.length} messages` : 'New conversation'}
            </span>
            {loading && (
              <span className="text-[10px] text-stone-500 flex items-center gap-1">
                <span className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-pulse" />
                Processing...
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
