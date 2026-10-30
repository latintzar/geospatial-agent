# Public console example

Set `NEXT_PUBLIC_EXAMPLE_MODE=true` at build time to run the console without a model account. The two suggested prompts display an authored explanation and a retained result produced by the retail scorer against generated H3 features. Other prompts receive directions to the supported example. No model or live tools run in this mode. The map uses MapLibre and OpenStreetMap tiles with attribution.

The sample result is `src/lib/example-results.json` and comes from the scorer in `../retail-demo` using its `synthetic-example.parquet`. It does not contain the private London matrix. To run the original backend modes, configure your own model and map providers and validate the relevant tools; see the root README and recovery notes.

The deployment build uses asset prefix `/apps/geospatial-agent` and expects a reverse proxy to strip that prefix before forwarding to Next. For another route, adjust `assetPrefix` in `next.config.mjs`.
