# Geospatial Agent and retail location similarity

Leo is a geospatial agent prototype combining a conversational workspace, tools and map layers. The recovered console requires operator-owned model and Mapbox credentials. The [retail similarity example](retail-demo/README.md) runs locally against clearly synthetic features.

Original source: `latintzar/puedo_casa`, branch `leo-agentic-maps`, commit `3d0512e23c5ea5c43075dbaac5b633f98f73bee1`, `Leo/`. See [recovery and provenance](RECOVERY.md). Original source code is MIT licensed; dependencies and data retain their own licenses.

---

# 🦁 Leo - Geospatial Intelligence Agent

> **The Bloomberg Terminal for the Physical World**

Leo is an autonomous Geospatial Agent. You talk to it like a Senior Analyst. It understands Commerce, Geography, and Risk.

It doesn't just "show data"; it **triangulates truth**. It combines disparate layers (Crop Yields + Live Conflict + Road Connectivity) to answer complex economic questions in seconds.

![Leo Demo](https://img.shields.io/badge/demo-live-brightgreen)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![Next.js](https://img.shields.io/badge/next.js-14-black)

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- [Gemini API Key](https://ai.google.dev/) (free)
- [Mapbox Token](https://www.mapbox.com/) (free tier)

### Installation

```bash
# Clone and navigate to Leo
cd Leo

# Backend setup
cd backend
pip install -r requirements.txt
cd ..

# Frontend setup
cd frontend
npm install
cd ..

# Configure environment
cp env.template .env
# Edit .env with your API keys
```

### Run Leo

**Option 1: Quick Start Script**
```bash
./start.sh
```

**Option 2: Manual (Two Terminals)**

Terminal 1 - Backend:
```bash
cd Leo
python -m uvicorn backend.main:app --reload --port 8000
```

Terminal 2 - Frontend:
```bash
cd Leo/frontend
npm run dev
```

**Access Leo:**
- 🗺️ **Console**: http://localhost:3000
- 📚 **API Docs**: http://localhost:8000/docs

## 🧠 What Leo Can Do

### Ask Natural Questions

```
"What's the population density in central Tokyo?"
"Find optimal locations for a cocoa factory in Ghana"
"Analyze gentrification patterns in Berlin"
"Show me trade flows from Brazil to Europe"
"Where should we open a coffee shop in Austin?"
```

### 22 Geospatial Tools

| Tool | Data | Cost |
|------|------|------|
| **Overture Maps** | POIs, boundaries, buildings | FREE |
| **Demographics** | Population density (WorldPop) | FREE |
| **Agriculture** | Crop production (MapSPAM) | FREE |
| **Wealth Index** | Relative Wealth (Meta/HDX) | FREE |
| **Climate** | Weather risk, elevation | FREE |
| **HDX** | Humanitarian infrastructure | FREE |
| **News/Risk** | GDELT live events | FREE |
| **Routes** | OSRM transport routing | FREE |
| **Trade** | UN Comtrade flows | RATE-LTD |
| **Scraper** | Google Maps (ScrapingDog) | PAID |

## 🏗️ Architecture

### The 5-Step Agentic Pipeline

```
User Query
    ↓
┌─────────────────────────────────────────────────────────────┐
│  1. DEFINE AOI    - Smart location boundary detection       │
│  2. GATHER        - Context-aware data fetching             │
│  3. COMPUTE       - Intersection & derivative analysis      │
│  4. VISUALIZE     - Deck.gl + Mapbox rendering              │
│  5. STORYTELLING  - Cinematic camera + narrative            │
└─────────────────────────────────────────────────────────────┘
    ↓
3D Map + Analysis + Suggested Actions
```

### Tech Stack

**Backend:**
- FastAPI + Uvicorn
- Google Gemini (AI orchestration)
- H3, Shapely, GeoPandas (geo processing)
- DuckDB (fast spatial queries)

**Frontend:**
- Next.js 14 + TypeScript
- Deck.gl (3D visualization)
- Mapbox GL (base maps)
- Tailwind CSS

## 📁 Project Structure

```
Leo/
├── backend/              # Python FastAPI server
│   ├── agent.py          # ReAct agent orchestrator
│   ├── main.py           # API endpoints
│   ├── schema.py         # Pydantic models
│   ├── tools/            # 10+ geospatial tools
│   │   ├── tools_overture.py
│   │   ├── tools_demographics.py
│   │   ├── tools_agriculture.py
│   │   └── ...
│   └── data/             # Local data cache
├── frontend/             # Next.js application
│   ├── src/
│   │   ├── app/          # Pages
│   │   ├── components/   # Map, Chat, Deck.gl
│   │   └── lib/          # Types & utilities
│   └── package.json
├── tests/                # Test suite
├── pyproject.toml        # Python package config
├── start.sh              # Quick start script
└── README.md
```

## 🎬 Visual Design System

Leo uses a **Unified Visual Design System** where each data type has a distinct look:

| Data | Style | Color | Visual |
|------|-------|-------|--------|
| Demographics | 3D Extrusion | Magma | "Human Mountains" |
| Agriculture | Flat | Green | "Fertile Ground" |
| Wealth | Flat | Viridis | "Economic Terrain" |
| Retail Gravity | 3D Extrusion | Inferno | "Commercial Intensity" |
| Routes | Line | Neon Blue | "Glowing Highways" |
| Trade | 3D Arc | Magenta | "Flight Paths" |
| Risk/News | Symbol | Red/Green | "Radar Blips" |

## 🔧 Configuration

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GOOGLE_AI_API_KEY` | Yes | Gemini API key |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Yes | Mapbox access token |
| `NEXT_PUBLIC_API_URL` | No | Backend URL (default: localhost:8000) |
| `SCRAPINGDOG_API_KEY` | No | For paid Google Maps features |

### API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/chat` | POST | Send message, get AI response + layers |
| `/chat/stream` | POST | Streaming response |
| `/health` | GET | Health check |
| `/docs` | GET | OpenAPI documentation |

## 🧪 Testing

```bash
cd Leo
python -m pytest tests/
```

## 📜 License

MIT License - See [LICENSE](LICENSE) for details.

---

Built with 🦁 by the Puedo Casa Team
