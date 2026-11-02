# Geospatial Agent

An AI agent for querying and exploring maps through chat

Geospatial Agent is a chat-based workspace for querying geographic data and building interactive map layers. It keeps a location question, its processing steps and the resulting map in one place, with Python adapters for Overture, H3 search and other geographic sources.

[Open demo](https://preview.atelierneyra.com/apps/geospatial-agent/) · [Project website](https://atelierneyra.com/geospatial-agent/) · [Product tour](docs/product-tour.md) · [Documentation](https://docs.atelierneyra.com/geospatial-agent/overview/)

![Geospatial Agent](https://atelierneyra.com/assets/product-motion-v4/geospatial-agent.jpg)

## Product areas

| Area | What it does |
| --- | --- |
| Chat | Submit a location question and read the response beside the map. |
| Map layers | Display geographic results with deck.gl; inspect cells and show or hide individual layers. |
| Process and plans | Keep streamed progress, tool events and plan states in the workspace when using the configured backend. |
| Geographic tools | Extend the Python adapters for Overture, demographics, agriculture, climate, routes, news and other sources. |
| Location similarity | Use the retained H3 feature-search path or reuse the separate [Retail Location Similarity](https://github.com/latintzar/retail-location-similarity) scorer. |

## Explore the example

Choose **Find locations similar to Covent Garden**. The original map renderer shows 30 matching locations from a retained retail-scoring result. Select a cell to inspect its score, then hide and restore the result layer. On phones, **Ask about a place** opens full-screen chat; desktop keeps the chat/map split.

The three prepared prompts share an authored explanation and a result calculated from 90 generated H3 feature records. Fresh agent queries use your configured model, datasets and tools. The [product tour](docs/product-tour.md) explains both paths and maps the visible areas to source.

## Run the example

Requires Node.js 22 or newer and npm.

```sh
git clone https://github.com/latintzar/geospatial-agent.git
cd geospatial-agent/frontend
npm ci
NEXT_PUBLIC_EXAMPLE_MODE=true npm run dev
```

Open **http://localhost:3000**. MapLibre and OpenStreetMap provide the example basemap. Local builds serve at the root; set `NEXT_PUBLIC_ASSET_PREFIX` at build time for a mounted path. [Example mode](frontend/EXAMPLE-MODE.md) covers the data and deployment contract.

## Build with it

- [Product tour](docs/product-tour.md): example journey, product areas and source map.
- [Agent and provider setup](docs/AGENT-SETUP.md): Python backend, selected accounts, datasets and API access boundary.
- [Mobile interactions](docs/MOBILE-UX.md): full-screen dialogs, keyboard geometry and shared state.
- [Historical technical guide](docs/original-README.md): original product architecture and tool design.
- [Recovery record](RECOVERY.md) and [data rights](DATA-RIGHTS-AND-PROVENANCE.md): dated provenance and distribution decisions.

The original backend and tool adapters are retained for further development. Configure and test each chosen tool with your own model, mapping and data accounts. The local-first API’s [authenticated network configuration](docs/AGENT-SETUP.md#api-access-boundary) keeps the private token on your server or proxy.

A separate historical London matrix was privately verified at 131,596 locations and 1,956 numeric features. The public example supplies generated features; global matrix completion remains unverified. Source authority is `latintzar/puedo_casa`, `leo-agentic-maps`, commit `3d0512e23c5ea5c43075dbaac5b633f98f73bee1`, under `Leo/`. Original code is [MIT licensed](LICENSE); third-party software, services and data retain their own terms.

[made by atelier neyra](https://atelierneyra.com)
