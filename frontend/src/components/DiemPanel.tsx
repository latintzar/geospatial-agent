'use client';

import { useState, useCallback } from 'react';
import { Navigation, Search, Loader2, Globe, MousePointer2, MapPin, Sparkles, Laugh } from 'lucide-react';

interface DiemPanelProps {
  onSearch: (lat: number, lng: number) => void;
  onClear: () => void;  // Clear results for new search
  isSearching: boolean;
  selectedLocation: { lat: number; lng: number } | null;  // From map click
  result?: {
    reference?: {
      hex: string;
      lat: number;
      lng: number;
      description?: string;  // AI-generated vibe description
      starter_pack?: string;  // AI-generated meme description
      top_scores?: Array<{ column: string; value: number }>;
    };
    stats?: {
      total_hexes: number;
      feature_dimensions: number;
      top_k: number;
    };
  } | null;
}

export default function DiemPanel({ onSearch, onClear, isSearching, result, selectedLocation }: DiemPanelProps) {
  const [locationError, setLocationError] = useState<string | null>(null);
  const [isGettingLocation, setIsGettingLocation] = useState(false);

  // Get user's current location
  const handleGetLocation = useCallback(() => {
    setLocationError(null);
    setIsGettingLocation(true);

    if (!navigator.geolocation) {
      setLocationError('Geolocation not supported');
      setIsGettingLocation(false);
      return;
    }

    navigator.geolocation.getCurrentPosition(
      (position) => {
        // Directly trigger search with geolocation
        onSearch(position.coords.latitude, position.coords.longitude);
        setIsGettingLocation(false);
      },
      (error) => {
        setLocationError(
          error.code === 1 ? 'Location access denied' :
          error.code === 2 ? 'Location unavailable' :
          'Location request timed out'
        );
        setIsGettingLocation(false);
      },
      { enableHighAccuracy: true, timeout: 10000 }
    );
  }, [onSearch]);

  // Trigger search when location is selected
  const handleSearch = useCallback(() => {
    if (!selectedLocation) {
      setLocationError('Click on the map to select a location first');
      return;
    }
    setLocationError(null);
    onSearch(selectedLocation.lat, selectedLocation.lng);
  }, [selectedLocation, onSearch]);

  // Check if we have a location selected
  const hasLocation = selectedLocation !== null;

  return (
    <div className="h-full flex flex-col bg-background">
      {/* Header */}
      <div className="p-4 border-b border-stone-800/50">
        <div className="flex items-center gap-2 mb-2">
          <Globe className="w-5 h-5 text-violet-400" />
          <h2 className="text-lg font-medium text-white">DIEM Search</h2>
        </div>
        <p className="text-xs text-stone-400 leading-relaxed">
          Find places with a similar <span className="text-violet-300">vibe</span> anywhere in London.
          Click to select a reference spot.
        </p>
      </div>

      {/* Location Selection */}
      <div className="p-4 space-y-4">
        {/* Status: No location selected */}
        {!hasLocation && !result && (
          <div className="p-6 border-2 border-dashed border-stone-700 rounded-xl text-center">
            <MousePointer2 className="w-8 h-8 text-violet-400 mx-auto mb-3" />
            <p className="text-sm text-white font-medium mb-1">Click anywhere on the map</p>
            <p className="text-xs text-stone-500">to select your reference location</p>
          </div>
        )}

        {/* Status: Location selected, ready to search */}
        {hasLocation && !result && (
          <div className="space-y-3">
            <div className="p-4 bg-violet-500/10 border border-violet-500/30 rounded-xl">
              <div className="flex items-center gap-2 text-violet-300 mb-2">
                <MapPin className="w-4 h-4" />
                <span className="text-sm font-medium">Location Selected</span>
              </div>
              <p className="text-xs text-stone-400">
                Ready to find the top 1,000 most similar hexes using all ~1,900 feature dimensions
              </p>
            </div>

            <button
              onClick={handleSearch}
              disabled={isSearching}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-violet-600 hover:bg-violet-500 rounded-xl text-sm text-white font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isSearching ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Analyzing {'>'}130k hexes...</span>
                </>
              ) : (
                <>
                  <Search className="w-4 h-4" />
                  <span>Find Similar Places</span>
                </>
              )}
            </button>
          </div>
        )}

        {/* My Location button */}
        {!result && (
          <button
            onClick={handleGetLocation}
            disabled={isGettingLocation || isSearching}
            className="w-full flex items-center justify-center gap-2 px-3 py-2.5 bg-stone-800/50 hover:bg-stone-700/50 border border-stone-700/50 rounded-lg text-xs text-stone-400 hover:text-white transition-colors disabled:opacity-50"
          >
            {isGettingLocation ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
            ) : (
              <Navigation className="w-3.5 h-3.5" />
            )}
            <span>Use My Location</span>
          </button>
        )}

        {/* Error message */}
        {locationError && (
          <div className="px-3 py-2 bg-red-500/10 border border-red-500/20 rounded-lg text-xs text-red-400">
            {locationError}
          </div>
        )}
      </div>

      {/* Results Section */}
      {result?.reference && (
        <div className="flex-1 overflow-auto p-4 border-t border-stone-800/50">
          <div className="space-y-4">
            {/* VIBE DESCRIPTION - Infrastructure & Access Focus */}
            <div className="p-4 bg-gradient-to-br from-violet-500/10 to-fuchsia-500/10 border border-violet-500/20 rounded-xl">
              <div className="flex items-center gap-2 mb-3">
                <Sparkles className="w-4 h-4 text-violet-400" />
                <span className="text-xs font-medium text-violet-300 uppercase tracking-wider">Location Profile</span>
              </div>
              {result.reference.description ? (
                <p className="text-sm text-white leading-relaxed">
                  {result.reference.description}
                </p>
              ) : (
                <p className="text-sm text-stone-400 italic">
                  Analyzing {result.stats?.feature_dimensions?.toLocaleString() || '~2,000'} features...
                </p>
              )}
            </div>

            {/* STARTER PACK - Hyper-local Meme */}
            <div className="p-4 bg-gradient-to-br from-amber-500/10 to-orange-500/10 border border-amber-500/20 rounded-xl">
              <div className="flex items-center gap-2 mb-3">
                <Laugh className="w-4 h-4 text-amber-400" />
                <span className="text-xs font-medium text-amber-300 uppercase tracking-wider">Starter Pack</span>
              </div>
              {result.reference.starter_pack ? (
                <div className="text-sm text-white leading-relaxed whitespace-pre-line">
                  {result.reference.starter_pack}
                </div>
              ) : (
                <p className="text-sm text-stone-400 italic">
                  Generating hyper-local meme...
                </p>
              )}
            </div>

            {/* Mini Stats Bar */}
            {result.stats && (
              <div className="flex items-center justify-center gap-4 text-[10px] text-stone-500">
                <span>{result.stats.top_k.toLocaleString()} similar</span>
                <span>•</span>
                <span>{result.stats.feature_dimensions.toLocaleString()} dimensions</span>
                <span>•</span>
                <span>{(result.stats.total_hexes / 1000).toFixed(0)}k compared</span>
              </div>
            )}

            {/* New Search Button */}
            <button
              onClick={onClear}
              className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-stone-800/50 hover:bg-stone-700/50 border border-stone-700/50 rounded-lg text-xs text-stone-400 hover:text-white transition-colors"
            >
              <MousePointer2 className="w-3.5 h-3.5" />
              <span>Pick a New Location</span>
            </button>
          </div>
        </div>
      )}

      {/* Footer */}
      <div className="mt-auto p-4 border-t border-stone-800/50">
        <div className="text-[10px] text-stone-600 text-center">
          DIEM compares ~1,900 features • cafes, transit, parks, buildings & more
        </div>
      </div>
    </div>
  );
}

