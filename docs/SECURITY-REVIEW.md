# API and dependency review

Reviewed 1 November 2026.

The provider-backed Python API accepts loopback clients and exact configured frontend origins by default. A network deployment requires an operator-owned bearer token, exact origins and an authenticated frontend or proxy. Request bodies, messages, coordinates and result counts are bounded before provider execution. User query and coordinate values stay out of the request log.

The public map example uses generated records and an authored response. Its browser has access to OpenStreetMap tiles; the hosted Next process is restricted to loopback networking. Provider-backed tools require the recipient's own accounts and datasets.

The frontend uses Next.js 15.5.28, sharp 0.35.5 and MapLibre 6.16.0. These versions address the upstream [Next.js image optimization advisory](https://github.com/advisories/GHSA-2464-fhr4-w9xw) and [MapLibre attribution sanitizer advisory](https://github.com/advisories/GHSA-jrc7-96c5-q579). The deck.gl packages are aligned at 9.4.1; the lockfile contains the fixed loaders.gl textures implementation and excludes the optional texture-compression CLI. Fonts are installed locally with their upstream OFL licences.

Validation includes eleven API boundary tests, a clean lockfile install, a production example build and an actual browser example walkthrough. A dated npm runtime audit is an advisory snapshot; maintain dependencies as upstream advisories change. The original Python geospatial and cloud tools remain a retained development path, with commissioning and dataset checks described in [setup](AGENT-SETUP.md).
