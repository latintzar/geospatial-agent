"""
Strategy Retriever - Semantic Search for JTBD Playbooks

This module provides semantic search over the strategies.json knowledge base,
allowing the Leo Agent to find the most relevant strategy for a user's query.

Uses Google's text-embedding-004 model for embeddings and cosine similarity for matching.

API Key: Uses GEMINI_API_KEY_HELLO (same as brain.py) with hardcoded fallback.
"""

import json
import os
import logging
from typing import List, Dict, Any, Optional

import numpy as np

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# API KEY CONFIGURATION (same pattern as brain.py)
# =============================================================================

# Hardcoded "Hello" key as fallback - same as brain.py uses
_HELLO_API_KEY = ""

def _get_gemini_api_key() -> str:
    """
    Get the Gemini API key with fallback to Hello key.
    
    Checks in order:
    1. GEMINI_API_KEY_HELLO env var
    2. GOOGLE_AI_API_KEY env var  
    3. Hardcoded Hello key (fallback)
    
    Returns:
        API key string
    """
    return (
        os.environ.get('GEMINI_API_KEY_HELLO') or
        os.environ.get('GOOGLE_AI_API_KEY') or
        _HELLO_API_KEY
    )


class StrategyRetriever:
    """
    Semantic search engine for retrieving relevant strategies from strategies.json.
    
    Uses Google's text-embedding-004 model to embed strategies and queries,
    then finds the best matches using cosine similarity.
    
    Embeddings are cached in memory to avoid re-embedding the database on every query.
    """
    
    def __init__(self, filepath: str = None):
        """
        Initialize the StrategyRetriever.
        
        Args:
            filepath: Path to strategies.json. Defaults to same directory as this file.
        """
        self.strategies: List[Dict[str, Any]] = []
        self.strategy_embeddings: Dict[str, np.ndarray] = {}  # Cache: strategy_id -> embedding
        self.api_available = False
        self.genai = None
        
        # Resolve filepath
        if filepath is None:
            filepath = os.path.join(os.path.dirname(__file__), 'data', 'strategies.json')
        
        # Load strategies
        self._load_strategies(filepath)
        
        # Initialize Google AI
        self._init_google_ai()
    
    def _load_strategies(self, filepath: str) -> None:
        """Load strategies from JSON file."""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.strategies = data.get('strategies', [])
                logger.info(f"✅ Loaded {len(self.strategies)} strategies from {filepath}")
        except FileNotFoundError:
            logger.error(f"❌ Strategies file not found: {filepath}")
            self.strategies = []
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in strategies file: {e}")
            self.strategies = []
    
    def _init_google_ai(self) -> None:
        """
        Initialize Google Generative AI client.
        
        Uses the same API key pattern as brain.py with Hello key fallback.
        """
        api_key = _get_gemini_api_key()
        
        try:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self.genai = genai
            self.api_available = True
            key_source = "env" if os.environ.get('GEMINI_API_KEY_HELLO') or os.environ.get('GOOGLE_AI_API_KEY') else "fallback"
            logger.info(f"✅ Google AI initialized for embeddings (key: {key_source})")
        except ImportError:
            logger.warning("⚠️ google-generativeai package not installed. Run: pip install google-generativeai")
            self.api_available = False
        except Exception as e:
            logger.warning(f"⚠️ Failed to initialize Google AI: {e}")
            self.api_available = False
    
    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """
        Get embedding for text using Google's text-embedding-004 model.
        
        Args:
            text: Text to embed
            
        Returns:
            numpy array of embedding, or None if embedding fails
        """
        if not self.api_available or self.genai is None:
            logger.warning("⚠️ Cannot get embedding: Google AI not available")
            return None
        
        try:
            result = self.genai.embed_content(
                model='models/text-embedding-004',
                content=text
            )
            embedding = np.array(result['embedding'])
            return embedding
        except Exception as e:
            logger.warning(f"⚠️ Embedding failed for text: {e}")
            return None
    
    def _build_strategy_text(self, strategy: Dict[str, Any]) -> str:
        """
        Build a rich text representation of a strategy for embedding.
        
        Combines name, category, context, tools, and example queries
        to create a comprehensive searchable text.
        """
        parts = [
            f"Strategy: {strategy.get('name', '')}",
            f"Category: {strategy.get('category', '')}",
            f"Context: {strategy.get('context', '')}",
        ]
        
        # Add tool names
        tools = strategy.get('tools', [])
        tool_names = [t.get('tool', '') for t in tools]
        if tool_names:
            parts.append(f"Tools: {', '.join(tool_names)}")
        
        # Add example queries
        examples = strategy.get('example_queries', [])
        if examples:
            parts.append(f"Example queries: {'; '.join(examples)}")
        
        return ' | '.join(parts)
    
    def _ensure_embeddings_cached(self) -> bool:
        """
        Ensure all strategy embeddings are cached.
        
        Returns:
            True if embeddings are available, False otherwise
        """
        if not self.api_available:
            return False
        
        # Check if already cached
        if len(self.strategy_embeddings) == len(self.strategies):
            return True
        
        logger.info(f"🔄 Generating embeddings for {len(self.strategies)} strategies...")
        
        for strategy in self.strategies:
            strategy_id = strategy.get('id')
            if not strategy_id:
                continue
            
            # Skip if already cached
            if strategy_id in self.strategy_embeddings:
                continue
            
            # Build text and get embedding
            strategy_text = self._build_strategy_text(strategy)
            embedding = self._get_embedding(strategy_text)
            
            if embedding is not None:
                self.strategy_embeddings[strategy_id] = embedding
                logger.debug(f"  ✓ Embedded: {strategy_id}")
            else:
                logger.warning(f"  ✗ Failed to embed: {strategy_id}")
        
        cached_count = len(self.strategy_embeddings)
        logger.info(f"✅ Cached {cached_count}/{len(self.strategies)} strategy embeddings")
        
        return cached_count > 0
    
    def _cosine_similarity(self, a: np.ndarray, b: np.ndarray) -> float:
        """
        Compute cosine similarity between two vectors.
        
        Args:
            a: First vector
            b: Second vector
            
        Returns:
            Cosine similarity score between -1 and 1
        """
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    def find_relevant_strategies(
        self, 
        query: str, 
        top_k: int = 1
    ) -> List[Dict[str, Any]]:
        """
        Find the most relevant strategies for a user query.
        
        Args:
            query: User's natural language query
            top_k: Number of top matches to return (default: 1)
            
        Returns:
            List of matching strategies with title, description, reasoning plan, and score.
            Returns empty list if embeddings unavailable or query fails.
        """
        # Guard: No strategies loaded
        if not self.strategies:
            logger.warning("⚠️ No strategies loaded")
            return []
        
        # Guard: API not available
        if not self.api_available:
            logger.warning("⚠️ API not available, cannot perform semantic search")
            return []
        
        # Ensure embeddings are cached
        if not self._ensure_embeddings_cached():
            logger.warning("⚠️ Failed to cache strategy embeddings")
            return []
        
        # Embed the query
        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            logger.warning("⚠️ Failed to embed query")
            return []
        
        # Compute similarities
        similarities: List[tuple] = []
        
        for strategy in self.strategies:
            strategy_id = strategy.get('id')
            if strategy_id not in self.strategy_embeddings:
                continue
            
            strategy_embedding = self.strategy_embeddings[strategy_id]
            similarity = self._cosine_similarity(query_embedding, strategy_embedding)
            similarities.append((strategy, similarity))
        
        # Sort by similarity (descending)
        similarities.sort(key=lambda x: x[1], reverse=True)
        
        # Return top_k results
        results = []
        for strategy, score in similarities[:top_k]:
            # Build reasoning plan from reasoning_chain
            reasoning_chain = strategy.get('reasoning_chain', [])
            reasoning_plan = [
                f"Step {step.get('step', i+1)}: {step.get('action', 'Unknown')} - {step.get('description', '')}"
                for i, step in enumerate(reasoning_chain)
            ]
            
            result = {
                'id': strategy.get('id'),
                'title': strategy.get('name'),
                'category': strategy.get('category'),
                'description': strategy.get('context'),
                'tools': [t.get('tool') for t in strategy.get('tools', [])],
                'reasoning_plan': reasoning_plan,
                'similarity_score': round(score, 4)
            }
            results.append(result)
            
            logger.info(f"🎯 Match: {result['title']} (score: {result['similarity_score']})")
        
        return results
    
    def get_strategy_by_id(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a strategy by its ID.
        
        Args:
            strategy_id: The strategy ID (e.g., 'blank_street_protocol')
            
        Returns:
            Full strategy dict or None if not found
        """
        for strategy in self.strategies:
            if strategy.get('id') == strategy_id:
                return strategy
        return None
    
    def list_strategies(self) -> List[Dict[str, str]]:
        """
        List all available strategies (summary only).
        
        Returns:
            List of strategy summaries with id, name, and category
        """
        return [
            {
                'id': s.get('id'),
                'name': s.get('name'),
                'category': s.get('category')
            }
            for s in self.strategies
        ]


# =============================================================================
# CLI for testing
# =============================================================================

if __name__ == '__main__':
    import sys
    
    print("=" * 60)
    print("Strategy Retriever - Test CLI")
    print("=" * 60)
    
    # Initialize retriever
    retriever = StrategyRetriever()
    
    # List strategies
    print("\n📋 Available Strategies:")
    for s in retriever.list_strategies():
        print(f"  - {s['id']}: {s['name']} ({s['category']})")
    
    # Test query
    test_queries = [
        "Where should I open a coffee shop?",
        "What's the cocoa supply risk from Africa?",
        "Find undervalued neighborhoods for real estate investment",
        "Is Lisbon a good place to live?",
        "Check my shipping route for disruptions"
    ]
    
    print("\n🔍 Test Queries:")
    for query in test_queries:
        print(f"\n  Query: \"{query}\"")
        results = retriever.find_relevant_strategies(query, top_k=1)
        
        if results:
            match = results[0]
            print(f"  → Match: {match['title']} (score: {match['similarity_score']})")
            print(f"  → Category: {match['category']}")
        else:
            print("  → No match (API unavailable or error)")
    
    print("\n" + "=" * 60)
