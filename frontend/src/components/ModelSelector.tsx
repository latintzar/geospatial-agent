'use client';

import { useState, useRef, useEffect } from 'react';
import { ChevronDown, Zap, Sparkles } from 'lucide-react';
import { AVAILABLE_MODELS, type ModelId } from '@/lib/types';

interface ModelSelectorProps {
  selectedModel: ModelId;
  onSelectModel: (model: ModelId) => void;
}

// Icons for supported models (must match backend/agent.py SUPPORTED_MODELS)
const MODEL_ICONS: Record<string, React.ReactNode> = {
  'gemini-3-flash-preview': <Zap className="w-3.5 h-3.5 text-yellow-500" />,
  'gemini-3-pro-preview': <Sparkles className="w-3.5 h-3.5 text-emerald-500" />,
};

export default function ModelSelector({ selectedModel, onSelectModel }: ModelSelectorProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    };

    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selectedModelData = AVAILABLE_MODELS.find((m) => m.id === selectedModel) || AVAILABLE_MODELS[0];

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-3 py-1.5 bg-[#141414] border border-gray-800/50 rounded-lg text-sm text-gray-300 hover:border-gray-700 hover:bg-[#1A1A1A] transition-all"
      >
        {MODEL_ICONS[selectedModel]}
        <span className="hidden sm:inline">{selectedModelData.name}</span>
        <span className="sm:hidden text-xs">{selectedModel.split('-').slice(-1)[0]}</span>
        <ChevronDown className={`w-3.5 h-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
      </button>

      {isOpen && (
        <div className="absolute top-full right-0 mt-2 w-64 bg-[#0A0A0A] border border-gray-800/50 rounded-xl shadow-xl shadow-black/50 overflow-hidden z-50">
          <div className="p-2 border-b border-gray-800/50">
            <p className="text-[10px] uppercase tracking-wider text-gray-600 px-2">Select Model</p>
          </div>
          <div className="p-1">
            {AVAILABLE_MODELS.map((model) => (
              <button
                key={model.id}
                onClick={() => {
                  onSelectModel(model.id);
                  setIsOpen(false);
                }}
                className={`w-full flex items-start gap-3 px-3 py-2.5 rounded-lg text-left transition-all ${
                  selectedModel === model.id
                    ? 'bg-emerald-500/10 border border-emerald-500/20'
                    : 'hover:bg-white/5'
                }`}
              >
                <div className="mt-0.5">{MODEL_ICONS[model.id]}</div>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${selectedModel === model.id ? 'text-emerald-400' : 'text-gray-200'}`}>
                    {model.name}
                  </p>
                  <p className="text-xs text-gray-500 truncate">{model.description}</p>
                </div>
                {selectedModel === model.id && (
                  <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 mt-2" />
                )}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

