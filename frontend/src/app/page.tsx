'use client';

import { useState, useCallback } from 'react';
import dynamic from 'next/dynamic';
import ChatPanel from '@/components/ChatPanel';
import DiemPanel from '@/components/DiemPanel';
import ThoughtDrawer from '@/components/ThoughtDrawer';
import ProcessIndicator from '@/components/ProcessIndicator';
import PlanCard from '@/components/PlanCard';
import { useLeoClient } from '@/hooks/useLeoClient';
import { useDiemSearch } from '@/hooks/useDiemSearch';
import type { StreamingState } from '@/lib/types';
import { Brain, Database, Globe } from 'lucide-react';

// Dynamic import for MapPanel to avoid SSR issues with Mapbox
const MapPanel = dynamic(() => import('@/components/MapPanel'), {
  ssr: false,
  loading: () => (
    <div className="w-full h-full bg-background flex items-center justify-center">
      <div className="animate-pulse text-gray-600">Loading map...</div>
    </div>
  ),
});

// Backend API URL (for display)
const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

// Search modes
type SearchMode = 'cascade' | 'diem';

// =============================================================================
// MAIN COMPONENT
// =============================================================================

export default function LeoPage() {
  // Search mode state
  const [searchMode, setSearchMode] = useState<SearchMode>('cascade');
  
  // Use the SSE streaming hook for CASCADE mode
  const {
    messages,
    mapLayers: cascadeLayers,
    viewState: cascadeViewState,
    thinkingLog,
    isThinking,
    currentMessage,
    statusMessage: cascadeStatus,
    selectedModel,
    processSteps,
    isRequestComplete,
    planSteps,
    currentPlanStepId,
    isPlanActive,
    areaClusters,
    sendMessage,
    setSelectedModel,
    clearLayers: clearCascadeLayers,
    toggleLayer: toggleCascadeLayer,
    setViewState: setCascadeViewState,
    clearProcessSteps,
    clearPlan,
  } = useLeoClient();

  // Use the DIEM search hook for DIEM mode
  const {
    isSearching: isDiemSearching,
    result: diemResult,
    layers: diemLayers,
    viewState: diemViewState,
    statusMessage: diemStatus,
    search: runDiemSearch,
    clearResults: clearDiemResults,
    setViewState: setDiemViewState,
    setSelectedLocation: setDiemSelectedPin,  // Shows pin on map
  } = useDiemSearch();

  // Thought drawer state
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);
  
  // DIEM: Selected location from map click
  const [diemSelectedLocation, setDiemSelectedLocation] = useState<{ lat: number; lng: number } | null>(null);

  // Get active layers/viewState based on mode
  const mapLayers = searchMode === 'cascade' ? cascadeLayers : diemLayers;
  const viewState = searchMode === 'cascade' ? cascadeViewState : diemViewState;
  const statusMessage = searchMode === 'cascade' ? cascadeStatus : diemStatus;
  const isProcessing = searchMode === 'cascade' ? isThinking : isDiemSearching;

  // Send message - cascade mode
  const handleSendMessage = useCallback(async (content: string) => {
    await sendMessage(content);
  }, [sendMessage]);

  // DIEM search handler
  const handleDiemSearch = useCallback((lat: number, lng: number) => {
    runDiemSearch(lat, lng);
  }, [runDiemSearch]);

  // Map click handler for DIEM mode - sets the reference location AND shows pin
  const handleMapClick = useCallback((lat: number, lng: number) => {
    if (searchMode === 'diem') {
      setDiemSelectedLocation({ lat, lng });
      setDiemSelectedPin(lat, lng);  // Show pin immediately on map
    }
  }, [searchMode, setDiemSelectedPin]);

  // View state change handler
  const handleViewStateChange = useCallback((vs: typeof viewState) => {
    if (searchMode === 'cascade') {
      setCascadeViewState(vs);
    } else {
      setDiemViewState(vs);
    }
  }, [searchMode, setCascadeViewState, setDiemViewState]);

  // Layer toggle handler
  const handleToggleLayer = useCallback((layerId: string) => {
    if (searchMode === 'cascade') {
      toggleCascadeLayer(layerId);
    }
    // DIEM layers don't have toggle yet
  }, [searchMode, toggleCascadeLayer]);

  // Clear all handler
  const handleClearAll = useCallback(() => {
    if (searchMode === 'cascade') {
      clearCascadeLayers();
    } else {
      clearDiemResults();
      setDiemSelectedLocation(null);
    }
  }, [searchMode, clearCascadeLayers, clearDiemResults]);

  // Clear DIEM results for new search
  const handleClearDiem = useCallback(() => {
    clearDiemResults();
    setDiemSelectedLocation(null);
  }, [clearDiemResults]);

  // Build streaming state for ChatPanel compatibility
  const streamingState: StreamingState = {
    isStreaming: isThinking,
    thinkingMessage: thinkingLog.length > 0 ? thinkingLog[thinkingLog.length - 1].message : 'Processing...',
    activeToolCalls: thinkingLog
      .filter(t => t.type === 'tool')
      .map((t) => ({
        name: t.message,
        args: {},
        status: 'success' as const,
        startTime: t.timestamp.getTime(),
      })),
    streamedText: currentMessage,
  };

  // ==========================================================================
  // RENDER
  // ==========================================================================
  return (
    <div className="h-screen w-screen flex flex-col bg-background overflow-hidden">
      {/* Header */}
      <header className="h-12 px-5 flex items-center justify-between border-b border-stone-800/50 bg-background z-10">
        <a 
          href="https://atelierneyra.com" 
          target="_blank" 
          rel="noopener noreferrer"
          className="font-serif text-lg font-medium tracking-tight text-white hover:text-stone-300 transition-colors"
        >
          Leo
        </a>

        <div className="flex items-center gap-3">
          {/* Mode Toggle */}
          <div className="flex items-center bg-stone-800/50 rounded-lg p-0.5 border border-stone-700/50">
            <button
              onClick={() => setSearchMode('cascade')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
                searchMode === 'cascade'
                  ? 'bg-emerald-500/20 border border-emerald-500/40 text-emerald-300'
                  : 'text-stone-400 hover:text-white'
              }`}
            >
              <Database className="w-3.5 h-3.5" />
              <span>Example results</span>
            </button>
            {process.env.NEXT_PUBLIC_EXAMPLE_MODE !== 'true' && (
            <button
              onClick={() => setSearchMode('diem')}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition-all ${
                searchMode === 'diem'
                  ? 'bg-violet-500/20 border border-violet-500/40 text-violet-300'
                  : 'text-stone-400 hover:text-white'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>Location search</span>
            </button>
            )}
          </div>

          {/* Status Message - Shows current processing step */}
          {isProcessing && statusMessage && (
            <div className="flex items-center gap-2 px-3 py-1 bg-blue-500/10 border border-blue-500/20 rounded-lg">
              <div className="w-1.5 h-1.5 bg-blue-400 rounded-full animate-pulse" />
              <span className="text-xs text-blue-300 max-w-[200px] truncate">
                {statusMessage}
              </span>
            </div>
          )}

          {/* Thinking Indicator Button */}
          <button
            onClick={() => setIsDrawerOpen(true)}
            className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all ${
              isProcessing 
                ? 'bg-purple-500/10 border border-purple-500/30 text-purple-300' 
                : 'bg-stone-800/50 border border-stone-700/50 text-stone-400 hover:text-white hover:border-stone-600'
            }`}
            aria-label="Open thinking drawer"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && setIsDrawerOpen(true)}
          >
            <Brain className={`w-3.5 h-3.5 ${isProcessing ? 'animate-pulse' : ''}`} />
            <span>{isProcessing ? 'Processing...' : 'View Process'}</span>
            {isProcessing && (
              <div className="w-1.5 h-1.5 bg-purple-400 rounded-full animate-pulse" />
            )}
          </button>

          {mapLayers.length > 0 && (
            <button
              onClick={handleClearAll}
              className="text-xs text-stone-500 hover:text-white transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
      </header>

      {/* Main Content */}
      <div className="px-4 py-2 text-xs text-emerald-200 bg-emerald-950">Authored example · synthetic features · retained scorer result · no model call</div>
      <main className="flex-1 flex overflow-hidden">
        {/* Left Panel - switches based on mode */}
        <div className="w-[45%] sm:w-[400px] flex-shrink-0 border-r border-stone-800/50">
          {searchMode === 'cascade' ? (
            <ChatPanel
              messages={messages}
              loading={isThinking}
              onSendMessage={handleSendMessage}
              layers={cascadeLayers}
              onToggleLayer={toggleCascadeLayer}
              streamingState={streamingState}
              selectedModel={selectedModel}
              onSelectModel={setSelectedModel}
            />
          ) : (
            <DiemPanel
              onSearch={handleDiemSearch}
              onClear={handleClearDiem}
              isSearching={isDiemSearching}
              result={diemResult}
              selectedLocation={diemSelectedLocation}
            />
          )}
        </div>

        {/* Map Panel */}
        <div className="flex-1">
          <MapPanel
            layers={mapLayers}
            viewState={viewState}
            onViewStateChange={handleViewStateChange}
            onToggleLayer={handleToggleLayer}
            mapControl={null}
            focusGeometry={null}
            areaClusters={searchMode === 'cascade' ? areaClusters : []}
            onMapClick={searchMode === 'diem' ? handleMapClick : undefined}
            clickMode={searchMode === 'diem'}
          />
        </div>
      </main>

      {/* Cursor-Style Plan Card (Primary - when plan is available) */}
      {planSteps.length > 0 && (
        <PlanCard
          steps={planSteps}
          currentStepId={currentPlanStepId}
          isActive={isPlanActive}
          isComplete={isRequestComplete}
          onClose={clearPlan}
        />
      )}
      
      {/* Fallback: Process Indicator (when no plan, only step events) */}
      {planSteps.length === 0 && processSteps.length > 0 && (
        <ProcessIndicator
          steps={processSteps}
          isRequestComplete={isRequestComplete}
          onClear={clearProcessSteps}
        />
      )}

      {/* Thought Drawer */}
      <ThoughtDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        thinkingLog={thinkingLog}
        isThinking={isThinking}
        currentMessage={currentMessage}
      />

      {/* Footer */}
      <footer className="h-5 px-4 flex items-center justify-between text-[10px] text-stone-600 bg-background border-t border-stone-800/50">
        <span>{mapLayers.length} layer{mapLayers.length !== 1 ? 's' : ''} • {mapLayers.filter(l => l.visible).length} visible</span>
        <div className="flex items-center gap-3">
          <span className={`flex items-center gap-1 ${isThinking ? 'text-purple-400' : ''}`}>
            {isThinking && <span className="w-1 h-1 bg-purple-400 rounded-full animate-pulse" />}
            {process.env.NEXT_PUBLIC_EXAMPLE_MODE === 'true' ? 'Retained example' : 'SSE Streaming'}
          </span>
          {process.env.NEXT_PUBLIC_EXAMPLE_MODE !== 'true' && <span className="text-stone-700">{API_URL}</span>}
        </div>
      </footer>
    </div>
  );
}
