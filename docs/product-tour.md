# Product tour

Geospatial Agent is a chat and map workspace for analysts exploring where to locate a business or understand a place. The product connects the question to inspectable geographic layers, keeping processing evidence in the same workspace.

[Open demo](https://preview.atelierneyra.com/apps/geospatial-agent/) · [Run the example](../README.md#run-the-example)

## A location comparison

1. Open the app. On phones, choose **Ask about a place**; desktop shows chat alongside the map.
2. Select **Find locations similar to Covent Garden**. The prepared example returns the retained explanation and the scorer’s 30 synthetic matching locations.
3. Return to the map and select a highlighted cell to inspect its score. Use the layer control to hide and restore **Synthetic similarity results**.
4. Open **Process** to inspect the progress panel. In example mode the useful evidence is the retained result and its generated-data provenance. With the backend configured, streamed events populate the process and plan components as work runs.
5. Reopen chat. The messages and draft stay in place as you switch between conversation and map. The other two prepared prompts expose the same retained example, while fresh analysis follows the provider setup path.

The example uses 90 generated H3 feature records. Its scores were calculated by the retail scorer; the response text is authored. [Example mode](../frontend/EXAMPLE-MODE.md) records that boundary precisely.

## Product areas and source

| Area | Actions and results | Source |
| --- | --- | --- |
| Conversation | Enter a question, choose an example and keep the conversation beside its result. | [ChatPanel.tsx](../frontend/src/components/ChatPanel.tsx), [useLeoClient.ts](../frontend/src/hooks/useLeoClient.ts). |
| Geographic canvas | Pan, zoom, inspect feature results and toggle layers. | [MapPanel.tsx](../frontend/src/components/MapPanel.tsx), [DeckGLMap.tsx](../frontend/src/components/DeckGLMap.tsx). |
| Processing evidence | Render tool/log events, plan steps and streamed messages from a configured backend. | [ThoughtDrawer.tsx](../frontend/src/components/ThoughtDrawer.tsx), [PlanCard.tsx](../frontend/src/components/PlanCard.tsx), [useLeoClient.ts](../frontend/src/hooks/useLeoClient.ts). |
| Agent and transport | Extract query features, run cascade search and stream layer updates to the client. | [backend/agent.py](../backend/agent.py), [backend/main.py](../backend/main.py), [API access boundary](AGENT-SETUP.md#api-access-boundary). |
| Data tools | Query Overture/Athena, demographics, agriculture, climate, routes, news and other selected sources. | [backend/tools/](../backend/tools/), [Overture schema](../backend/tools/overture_schema.py). |
| Similarity and feature building | Compare location vectors or continue the retained matrix-building work. | [tools_diem_search.py](../backend/tools/tools_diem_search.py), [backend/etl/](../backend/etl/), [global matrix record](GLOBAL_MATRIX_BUILD.md). |

## Configured agent flow

The implemented cascade path extracts requested features, queries its selected spatial data and streams map layers as stages finish. The frontend’s event handler also supports plan, progress, map-control and response events. The separate location-similarity mode sends a selected point through the H3 scoring path. Configure each tool’s dataset and provider, then test that workflow from request to mapped result.

The design keeps the conversation and evidence together, and lets layers appear during processing. Phone chat and Process use native full-screen dialogs; closing chat preserves its state. [Mobile decisions](MOBILE-UX.md) describe the shared components and keyboard behavior.

## Continue from here

- [Agent setup](AGENT-SETUP.md) and [environment fields](../env.template) for selected services and the local-first API.
- [Original technical architecture](original-README.md#-architecture), retained as a historical design record.
- [Cascade search](CASCADE_SEARCH.md) and [retail schema](RETAIL_INTELLIGENCE_V1_SCHEMA.md) for deeper algorithm/data contracts.
- [Recovery](../RECOVERY.md) and [data provenance](../DATA-RIGHTS-AND-PROVENANCE.md) for historical evidence and distribution status.
- [Request-boundary tests](../tests/test_request_boundary.py) and [mobile browser checks](../tests/browser_mobile.py).

A useful continuation is to configure one tool end to end—question, data query, streamed event and inspectable layer—before adding further provider paths. The historical full London matrix remains separately held; the included example is the reusable starting dataset.
