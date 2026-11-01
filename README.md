# Geospatial Agent

An AI agent for querying and exploring maps through chat

Geospatial Agent is a map and chat workspace for exploring location questions alongside geographic layers and the tools that produce them.

![Geospatial Agent](https://atelierneyra.com/assets/product-motion-v4/geospatial-agent.jpg)

[Open demo](https://preview.atelierneyra.com/apps/geospatial-agent/) · [Project website](https://atelierneyra.com/geospatial-agent/) · [Documentation](https://docs.atelierneyra.com/geospatial-agent/overview/) · [GitHub](https://github.com/latintzar/geospatial-agent)

## What it does

The recovered Next.js and deck.gl workspace combines chat, map layers, process views and a Python backend with geographic tool adapters. The public example shows a retained result calculated by the retail location scorer using generated H3 features. Choose the suggested Covent Garden prompt to inspect its explanation and map layer.

## Run the example

Requires Node.js 22 or newer and npm.

```sh
git clone https://github.com/latintzar/geospatial-agent.git
cd geospatial-agent/frontend
npm ci
NEXT_PUBLIC_EXAMPLE_MODE=true npm run dev
```

Open http://localhost:3000. The example uses MapLibre and OpenStreetMap tiles and makes no model request. Local development and production builds serve the app at the root. For a prefixed deployment, set `NEXT_PUBLIC_ASSET_PREFIX` at build time. See [example mode](frontend/EXAMPLE-MODE.md).

## Live configuration and status

The original backend and tool adapters are retained for further development; live operation requires your own model and mapping accounts, data, and validation of each tool. See [environment template](env.template), [recovery notes](RECOVERY.md) and [original technical README](docs/original-README.md). The public example uses 90 synthetic feature records. A separate private historical London matrix was verified at 131,596 locations and 1,956 numeric features; global matrix completion has not been verified.

[Retail Location Similarity](https://github.com/latintzar/retail-location-similarity) is the standalone scoring example. Original source is MIT licensed; third-party code, services and data retain their own licenses.

[Set up with your agent](docs/AGENT-SETUP.md).

## Source and agent instructions

The source was recovered from `latintzar/puedo_casa`, branch `leo-agentic-maps`, commit `3d0512e23c5ea5c43075dbaac5b633f98f73bee1`, under `Leo/`. Preserve the distinction between authored examples and live provider output; use operator-owned credentials and keep synthetic and privately held datasets clearly identified. See [recovery](RECOVERY.md) and [data provenance](DATA-RIGHTS-AND-PROVENANCE.md) before changing data handling.


The API is local-first. [Recipient access and service setup](docs/AGENT-SETUP.md#api-access-boundary) describes exact frontend origins and private authorization for network deployments. The released map example runs with its included generated data.
