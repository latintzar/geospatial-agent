"""
Leo Tools - Semantic Engine (Vibe Check)
========================================

Semantic understanding for subjective queries using embeddings.

This module allows the Agent to understand QUALITATIVE queries:
- "Nice beach" → Rank beaches by semantic similarity to "nice"
- "Hipster cafe" → Find cafes that match the "hipster" vibe
- "Safe neighborhood" → Rank areas by semantic match to "safe"
- "Romantic dinner spot" → Find restaurants with romantic vibes

HOW IT WORKS:
-------------
1. FETCH: Get broad set of candidates from Athena (e.g., all cafes in area)
2. DESCRIBE: Generate text description for each candidate
3. EMBED: Create embeddings for descriptions AND user query
4. RANK: Calculate cosine similarity, return sorted list

USE CASES:
----------
| User Query               | Athena Fetch         | Semantic Filter      |
|--------------------------|----------------------|----------------------|
| "Quiet study spot"       | All cafes            | Rerank by "quiet"    |
| "Family-friendly beach"  | All beaches          | Rerank by "family"   |
| "Upscale bar"            | All bars             | Rerank by "upscale"  |
| "Artsy neighborhood"     | All neighborhoods    | Rerank by "artsy"    |

EMBEDDING MODEL:
---------------
Uses Google's Gemini embedding model (text-embedding-004) which provides:
- 768-dimensional vectors
- Multilingual support
- Fast inference

Prerequisites:
-------------
- GOOGLE_AI_API_KEY or GEMINI_API_KEY in .env
- google-generativeai package

Usage:
------
    from tools_semantic import SemanticEngine, semantic_rerank
    
    engine = SemanticEngine()
    
    # Rerank cafes by "quiet study spot" vibe
    candidates = [
        {"name": "Quiet Library Cafe", "category": "cafe"},
        {"name": "Loud Sports Bar", "category": "bar"},
        {"name": "Cozy Reading Corner", "category": "cafe"},
    ]
    
    ranked = engine.semantic_rerank(candidates, "quiet study spot")
    # Returns: [Reading Corner, Library Cafe, Sports Bar]
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass, field
from dotenv import load_dotenv

import numpy as np

# Google Generative AI for embeddings
try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False
    genai = None

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

# Embedding model configuration
EMBEDDING_MODEL = "text-embedding-004"  # Google's latest embedding model
EMBEDDING_DIMENSION = 768

# Task types for embeddings (affects how embeddings are generated)
TASK_RETRIEVAL_QUERY = "retrieval_query"      # For user queries
TASK_RETRIEVAL_DOCUMENT = "retrieval_document"  # For place descriptions

# Default fields to use for description generation
DEFAULT_DESCRIPTION_FIELDS = ['name', 'category', 'tags', 'description', 'address']

# Cache for embeddings (in-memory, cleared on restart)
_embedding_cache: Dict[str, List[float]] = {}


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SemanticMatch:
    """A candidate with its semantic similarity score."""
    
    candidate: Dict[str, Any]
    similarity: float
    description: str
    rank: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            **self.candidate,
            '_semantic_similarity': round(self.similarity, 4),
            '_semantic_rank': self.rank,
            '_description': self.description,
        }


@dataclass
class SemanticRerankResult:
    """Result from semantic_rerank operation."""
    
    ranked_candidates: List[SemanticMatch]
    query: str
    original_count: int
    processing_time_ms: int = 0
    
    def to_list(self) -> List[Dict[str, Any]]:
        """Return ranked candidates as list of dicts."""
        return [m.to_dict() for m in self.ranked_candidates]
    
    def top(self, n: int = 10) -> List[Dict[str, Any]]:
        """Get top N candidates."""
        return [m.to_dict() for m in self.ranked_candidates[:n]]


# =============================================================================
# SEMANTIC ENGINE CLASS
# =============================================================================

class SemanticEngine:
    """
    Semantic Engine for "Vibe Check" queries.
    
    Uses Google's Gemini embeddings to understand subjective qualities
    and rerank places/locations based on semantic similarity.
    
    Example:
        >>> engine = SemanticEngine()
        >>> 
        >>> # Fetch cafes from Athena (broad query)
        >>> cafes = athena.fetch_infrastructure_sql(bbox, category="cafe")
        >>> 
        >>> # Rerank by "quiet study spot" vibe
        >>> ranked = engine.semantic_rerank(cafes, "quiet study spot")
        >>> 
        >>> # Top match is most semantically similar to "quiet study spot"
        >>> print(ranked.top(5))
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = EMBEDDING_MODEL,
    ):
        """
        Initialize the Semantic Engine.
        
        Args:
            api_key: Google AI API key (defaults to env vars)
            model: Embedding model to use
        """
        self.model = model
        
        # Get API key
        self.api_key = api_key or os.getenv('GOOGLE_AI_API_KEY') or os.getenv('GEMINI_API_KEY')
        
        if not GENAI_AVAILABLE:
            logger.warning("⚠️ google-generativeai not installed. Semantic features disabled.")
            logger.warning("   Install with: pip install google-generativeai")
            self._enabled = False
            return
        
        if not self.api_key:
            logger.warning("⚠️ No Google AI API key found. Semantic features disabled.")
            logger.warning("   Set GOOGLE_AI_API_KEY or GEMINI_API_KEY in .env")
            self._enabled = False
            return
        
        # Configure Google AI
        genai.configure(api_key=self.api_key)
        self._enabled = True
        
        logger.info(f"🧠 SemanticEngine initialized")
        logger.info(f"   Model: {model}")
    
    @property
    def enabled(self) -> bool:
        """Check if semantic features are available."""
        return self._enabled
    
    # =========================================================================
    # CORE METHOD: semantic_rerank
    # =========================================================================
    
    def semantic_rerank(
        self,
        candidates: List[Dict[str, Any]],
        query: str,
        description_fields: List[str] = None,
        min_similarity: float = 0.0,
        top_k: Optional[int] = None,
    ) -> SemanticRerankResult:
        """
        Rerank candidates by semantic similarity to a query.
        
        This is the core "Vibe Check" function. Given a list of places/locations
        and a qualitative query, it ranks them by how well they match the vibe.
        
        Args:
            candidates: List of place dicts (from Athena, Overture, etc.)
                Each should have 'name' and ideally 'category', 'tags', etc.
            query: The "vibe" to match (e.g., "quiet study spot", "romantic")
            description_fields: Fields to use for generating descriptions
                Default: ['name', 'category', 'tags', 'description', 'address']
            min_similarity: Filter out candidates below this threshold
            top_k: Return only top K candidates (None = all)
            
        Returns:
            SemanticRerankResult with:
                - ranked_candidates: List of SemanticMatch objects, sorted by similarity
                - query: The original query
                - original_count: Number of input candidates
                - processing_time_ms: Time taken
                
        Example:
            >>> # Find "hipster" cafes
            >>> cafes = [
            ...     {"name": "Starbucks", "category": "cafe", "tags": ["chain", "corporate"]},
            ...     {"name": "Third Wave Coffee", "category": "cafe", "tags": ["artisan", "local"]},
            ...     {"name": "Industrial Roast", "category": "cafe", "tags": ["vintage", "exposed brick"]},
            ... ]
            >>> 
            >>> ranked = engine.semantic_rerank(cafes, "hipster coffee spot")
            >>> print(ranked.top(2))
            >>> # [Industrial Roast, Third Wave Coffee]
        """
        import time
        start_time = time.time()
        
        if not self._enabled:
            logger.warning("Semantic engine disabled - returning original order")
            return SemanticRerankResult(
                ranked_candidates=[
                    SemanticMatch(c, 0.0, self._generate_description(c, description_fields), i)
                    for i, c in enumerate(candidates)
                ],
                query=query,
                original_count=len(candidates),
            )
        
        if not candidates:
            return SemanticRerankResult(
                ranked_candidates=[],
                query=query,
                original_count=0,
            )
        
        logger.info(f"🧠 semantic_rerank: '{query}' over {len(candidates)} candidates")
        
        # Use default fields if not specified
        if description_fields is None:
            description_fields = DEFAULT_DESCRIPTION_FIELDS
        
        # Step 1: Generate descriptions for each candidate
        descriptions = []
        for candidate in candidates:
            desc = self._generate_description(candidate, description_fields)
            descriptions.append(desc)
        
        logger.info(f"   Generated {len(descriptions)} descriptions")
        
        # Step 2: Embed all descriptions
        description_embeddings = self._batch_embed(
            descriptions, 
            task_type=TASK_RETRIEVAL_DOCUMENT
        )
        
        # Step 3: Embed the query
        query_embedding = self._embed_single(query, task_type=TASK_RETRIEVAL_QUERY)
        
        # Step 4: Calculate cosine similarities
        similarities = []
        for i, desc_emb in enumerate(description_embeddings):
            if desc_emb is None:
                sim = 0.0
            else:
                sim = self._cosine_similarity(query_embedding, desc_emb)
            similarities.append(sim)
        
        # Step 5: Create ranked results
        matches = []
        for i, (candidate, desc, sim) in enumerate(zip(candidates, descriptions, similarities)):
            matches.append(SemanticMatch(
                candidate=candidate,
                similarity=sim,
                description=desc,
            ))
        
        # Sort by similarity (descending)
        matches.sort(key=lambda m: m.similarity, reverse=True)
        
        # Assign ranks
        for i, match in enumerate(matches):
            match.rank = i + 1
        
        # Filter by minimum similarity
        if min_similarity > 0:
            matches = [m for m in matches if m.similarity >= min_similarity]
            logger.info(f"   Filtered to {len(matches)} above min_similarity={min_similarity}")
        
        # Limit to top K
        if top_k is not None:
            matches = matches[:top_k]
        
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        logger.info(f"   ✅ Ranked in {processing_time_ms}ms")
        if matches:
            logger.info(f"   Top match: {matches[0].candidate.get('name', 'N/A')} (sim={matches[0].similarity:.3f})")
        
        return SemanticRerankResult(
            ranked_candidates=matches,
            query=query,
            original_count=len(candidates),
            processing_time_ms=processing_time_ms,
        )
    
    def filter_by_vibe(
        self,
        candidates: List[Dict[str, Any]],
        positive_vibes: List[str] = None,
        negative_vibes: List[str] = None,
        threshold: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Filter candidates by positive and negative vibes.
        
        More flexible than semantic_rerank - allows multiple vibes
        and can exclude items that match negative vibes.
        
        Args:
            candidates: List of place dicts
            positive_vibes: Vibes to match (e.g., ["quiet", "cozy"])
            negative_vibes: Vibes to exclude (e.g., ["loud", "crowded"])
            threshold: Similarity threshold for inclusion/exclusion
            
        Returns:
            Filtered list of candidates
            
        Example:
            >>> filtered = engine.filter_by_vibe(
            ...     cafes,
            ...     positive_vibes=["quiet", "spacious"],
            ...     negative_vibes=["loud", "cramped"],
            ...     threshold=0.3
            ... )
        """
        if not self._enabled:
            return candidates
        
        positive_vibes = positive_vibes or []
        negative_vibes = negative_vibes or []
        
        if not positive_vibes and not negative_vibes:
            return candidates
        
        logger.info(f"🧠 filter_by_vibe: +{positive_vibes} -{negative_vibes}")
        
        # Generate descriptions once
        descriptions = [self._generate_description(c) for c in candidates]
        description_embeddings = self._batch_embed(descriptions, TASK_RETRIEVAL_DOCUMENT)
        
        # Embed positive vibes
        positive_scores = []
        for vibe in positive_vibes:
            vibe_emb = self._embed_single(vibe, TASK_RETRIEVAL_QUERY)
            scores = [
                self._cosine_similarity(vibe_emb, d_emb) if d_emb else 0
                for d_emb in description_embeddings
            ]
            positive_scores.append(scores)
        
        # Embed negative vibes
        negative_scores = []
        for vibe in negative_vibes:
            vibe_emb = self._embed_single(vibe, TASK_RETRIEVAL_QUERY)
            scores = [
                self._cosine_similarity(vibe_emb, d_emb) if d_emb else 0
                for d_emb in description_embeddings
            ]
            negative_scores.append(scores)
        
        # Filter candidates
        filtered = []
        for i, candidate in enumerate(candidates):
            # Check positive vibes (any match above threshold)
            pos_match = not positive_vibes or any(
                scores[i] >= threshold for scores in positive_scores
            )
            
            # Check negative vibes (none match above threshold)
            neg_match = not negative_vibes or all(
                scores[i] < threshold for scores in negative_scores
            )
            
            if pos_match and neg_match:
                filtered.append(candidate)
        
        logger.info(f"   Filtered {len(candidates)} → {len(filtered)} candidates")
        return filtered
    
    def cluster_by_vibe(
        self,
        candidates: List[Dict[str, Any]],
        vibes: List[str],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Cluster candidates by which vibe they best match.
        
        Args:
            candidates: List of place dicts
            vibes: List of vibe categories (e.g., ["cozy", "modern", "rustic"])
            
        Returns:
            Dict mapping vibe → list of matching candidates
            
        Example:
            >>> clusters = engine.cluster_by_vibe(
            ...     restaurants,
            ...     vibes=["romantic", "casual", "upscale"]
            ... )
            >>> print(clusters["romantic"])  # Romantic restaurants
        """
        if not self._enabled:
            return {vibe: candidates for vibe in vibes}
        
        logger.info(f"🧠 cluster_by_vibe: {vibes}")
        
        # Generate descriptions and embed
        descriptions = [self._generate_description(c) for c in candidates]
        description_embeddings = self._batch_embed(descriptions, TASK_RETRIEVAL_DOCUMENT)
        
        # Embed each vibe
        vibe_embeddings = {
            vibe: self._embed_single(vibe, TASK_RETRIEVAL_QUERY)
            for vibe in vibes
        }
        
        # Assign each candidate to best-matching vibe
        clusters = {vibe: [] for vibe in vibes}
        
        for i, candidate in enumerate(candidates):
            if description_embeddings[i] is None:
                continue
            
            # Find best matching vibe
            best_vibe = None
            best_sim = -1
            
            for vibe, vibe_emb in vibe_embeddings.items():
                sim = self._cosine_similarity(vibe_emb, description_embeddings[i])
                if sim > best_sim:
                    best_sim = sim
                    best_vibe = vibe
            
            if best_vibe:
                clusters[best_vibe].append({
                    **candidate,
                    '_matched_vibe': best_vibe,
                    '_vibe_similarity': round(best_sim, 4),
                })
        
        for vibe, items in clusters.items():
            logger.info(f"   {vibe}: {len(items)} candidates")
        
        return clusters
    
    # =========================================================================
    # EMBEDDING METHODS
    # =========================================================================
    
    def _embed_single(
        self,
        text: str,
        task_type: str = TASK_RETRIEVAL_DOCUMENT,
    ) -> List[float]:
        """
        Embed a single text string.
        
        Uses caching to avoid re-embedding identical texts.
        """
        cache_key = f"{task_type}:{text}"
        
        if cache_key in _embedding_cache:
            return _embedding_cache[cache_key]
        
        try:
            result = genai.embed_content(
                model=f"models/{self.model}",
                content=text,
                task_type=task_type,
            )
            embedding = result['embedding']
            
            # Cache it
            _embedding_cache[cache_key] = embedding
            
            return embedding
        except Exception as e:
            logger.error(f"Embedding failed for '{text[:50]}...': {e}")
            return None
    
    def _batch_embed(
        self,
        texts: List[str],
        task_type: str = TASK_RETRIEVAL_DOCUMENT,
        batch_size: int = 100,
    ) -> List[List[float]]:
        """
        Embed multiple texts efficiently.
        
        Uses batching to reduce API calls.
        """
        embeddings = []
        
        # Check cache first
        uncached_indices = []
        uncached_texts = []
        
        for i, text in enumerate(texts):
            cache_key = f"{task_type}:{text}"
            if cache_key in _embedding_cache:
                embeddings.append(_embedding_cache[cache_key])
            else:
                embeddings.append(None)  # Placeholder
                uncached_indices.append(i)
                uncached_texts.append(text)
        
        if not uncached_texts:
            return embeddings
        
        # Batch embed uncached texts
        logger.debug(f"   Embedding {len(uncached_texts)} uncached texts...")
        
        for batch_start in range(0, len(uncached_texts), batch_size):
            batch = uncached_texts[batch_start:batch_start + batch_size]
            batch_indices = uncached_indices[batch_start:batch_start + batch_size]
            
            try:
                result = genai.embed_content(
                    model=f"models/{self.model}",
                    content=batch,
                    task_type=task_type,
                )
                
                for i, embedding in zip(batch_indices, result['embedding']):
                    embeddings[i] = embedding
                    # Cache it
                    cache_key = f"{task_type}:{texts[i]}"
                    _embedding_cache[cache_key] = embedding
                    
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
        
        return embeddings
    
    # =========================================================================
    # HELPER METHODS
    # =========================================================================
    
    def _generate_description(
        self,
        candidate: Dict[str, Any],
        fields: List[str] = None,
    ) -> str:
        """
        Generate a text description from a candidate's fields.
        
        Creates a natural language description for embedding.
        """
        if fields is None:
            fields = DEFAULT_DESCRIPTION_FIELDS
        
        parts = []
        
        # Name is primary
        name = candidate.get('name', '')
        if name:
            parts.append(name)
        
        # Category
        category = candidate.get('category', '') or candidate.get('categories', {}).get('primary', '')
        if category:
            parts.append(f"({category})")
        
        # Tags (list)
        tags = candidate.get('tags', [])
        if isinstance(tags, list) and tags:
            parts.append(f"[{', '.join(tags[:5])}]")
        elif isinstance(tags, str) and tags:
            parts.append(f"[{tags}]")
        
        # Description
        description = candidate.get('description', '')
        if description:
            parts.append(description[:200])
        
        # Address
        address = candidate.get('address', '')
        if address:
            parts.append(f"at {address}")
        
        return ' '.join(parts) if parts else 'Unknown place'
    
    def _cosine_similarity(
        self,
        vec1: List[float],
        vec2: List[float],
    ) -> float:
        """Calculate cosine similarity between two vectors."""
        if vec1 is None or vec2 is None:
            return 0.0
        
        a = np.array(vec1)
        b = np.array(vec2)
        
        dot_product = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(dot_product / (norm_a * norm_b))
    
    def clear_cache(self):
        """Clear the embedding cache."""
        global _embedding_cache
        _embedding_cache = {}
        logger.info("Embedding cache cleared")


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def semantic_rerank(
    candidates: List[Dict[str, Any]],
    query: str,
    **kwargs,
) -> List[Dict[str, Any]]:
    """
    Convenience function for semantic reranking.
    
    Returns list of dicts for compatibility.
    
    Example:
        >>> cafes = [{"name": "Cafe A"}, {"name": "Cafe B"}]
        >>> ranked = semantic_rerank(cafes, "quiet study spot")
    """
    engine = SemanticEngine()
    result = engine.semantic_rerank(candidates, query, **kwargs)
    return result.to_list()


def filter_by_vibe(
    candidates: List[Dict[str, Any]],
    positive_vibes: List[str] = None,
    negative_vibes: List[str] = None,
    **kwargs,
) -> List[Dict[str, Any]]:
    """Convenience function for vibe filtering."""
    engine = SemanticEngine()
    return engine.filter_by_vibe(candidates, positive_vibes, negative_vibes, **kwargs)


def cluster_by_vibe(
    candidates: List[Dict[str, Any]],
    vibes: List[str],
) -> Dict[str, List[Dict[str, Any]]]:
    """Convenience function for vibe clustering."""
    engine = SemanticEngine()
    return engine.cluster_by_vibe(candidates, vibes)


# =============================================================================
# TEST SUITE
# =============================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🧠 SemanticEngine Test Suite")
    print("=" * 70)
    
    engine = SemanticEngine()
    
    if not engine.enabled:
        print("\n⚠️ Semantic engine not enabled (missing API key)")
        print("   Set GOOGLE_AI_API_KEY in .env to run tests")
        print("=" * 70)
        exit(0)
    
    # Test 1: Basic semantic rerank
    print("\n🎯 Test 1: Semantic Rerank - 'Quiet Study Spot'")
    print("-" * 50)
    
    test_cafes = [
        {"name": "Loud Sports Bar", "category": "bar", "tags": ["sports", "TV", "noisy"]},
        {"name": "Quiet Corner Library", "category": "cafe", "tags": ["books", "quiet", "wifi"]},
        {"name": "Party Central Club", "category": "nightclub", "tags": ["dancing", "music", "loud"]},
        {"name": "Cozy Reading Nook", "category": "cafe", "tags": ["books", "tea", "comfortable"]},
        {"name": "Generic Coffee Shop", "category": "cafe", "tags": []},
    ]
    
    result = engine.semantic_rerank(test_cafes, "quiet study spot")
    print(f"   Query: 'quiet study spot'")
    print(f"   Results ({result.processing_time_ms}ms):")
    for match in result.ranked_candidates:
        print(f"     {match.rank}. {match.candidate['name']}: {match.similarity:.3f}")
    
    # Test 2: Filter by vibe
    print("\n🔍 Test 2: Filter by Vibe")
    print("-" * 50)
    
    filtered = engine.filter_by_vibe(
        test_cafes,
        positive_vibes=["quiet", "cozy"],
        negative_vibes=["loud", "party"],
        threshold=0.3,
    )
    print(f"   Positive: ['quiet', 'cozy']")
    print(f"   Negative: ['loud', 'party']")
    print(f"   Filtered: {[c['name'] for c in filtered]}")
    
    # Test 3: Cluster by vibe
    print("\n📊 Test 3: Cluster by Vibe")
    print("-" * 50)
    
    test_restaurants = [
        {"name": "Candlelit Italian", "category": "restaurant", "tags": ["romantic", "wine"]},
        {"name": "Burger Joint", "category": "restaurant", "tags": ["casual", "fast"]},
        {"name": "French Fine Dining", "category": "restaurant", "tags": ["upscale", "formal"]},
        {"name": "Pizza Place", "category": "restaurant", "tags": ["family", "casual"]},
        {"name": "Fancy Steakhouse", "category": "restaurant", "tags": ["elegant", "expensive"]},
    ]
    
    clusters = engine.cluster_by_vibe(
        test_restaurants,
        vibes=["romantic", "casual", "upscale"]
    )
    
    for vibe, items in clusters.items():
        print(f"   {vibe}: {[i['name'] for i in items]}")
    
    # Test 4: Hipster cafe test
    print("\n☕ Test 4: Semantic Rerank - 'Hipster Coffee'")
    print("-" * 50)
    
    more_cafes = [
        {"name": "Starbucks", "category": "cafe", "tags": ["chain", "corporate", "worldwide"]},
        {"name": "Third Wave Coffee Co", "category": "cafe", "tags": ["artisan", "local", "pour-over"]},
        {"name": "Industrial Roasters", "category": "cafe", "tags": ["vintage", "exposed brick", "vinyl"]},
        {"name": "Dunkin Donuts", "category": "cafe", "tags": ["chain", "fast", "donuts"]},
        {"name": "Bearded Barista", "category": "cafe", "tags": ["craft", "local", "organic"]},
    ]
    
    result = engine.semantic_rerank(more_cafes, "hipster artisan coffee shop")
    print(f"   Query: 'hipster artisan coffee shop'")
    for match in result.ranked_candidates[:3]:
        print(f"     {match.rank}. {match.candidate['name']}: {match.similarity:.3f}")
    
    print("\n" + "=" * 70)
    print("✅ Test suite complete!")
    print("=" * 70)
