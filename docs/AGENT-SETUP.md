# Set up Geospatial Agent with your agent

Geospatial Agent combines a chat interface, geographic layers and Python map tools. Start with the included map example, then select the live provider/data path you want to continue.

## Run the map example

Use Node 18.17+ and npm:

```sh
cd frontend
npm ci
NEXT_PUBLIC_EXAMPLE_MODE=true npm run dev
```

Open `http://localhost:3000` and choose the Covent Garden suggestion. This displays the retained location-scoring result using 90 generated feature records, MapLibre and OpenStreetMap. [Example mode](../frontend/EXAMPLE-MODE.md) explains the precise data and behavior.

## Connect the retained backend

The [recovery record](../RECOVERY.md) and [original technical guide](original-README.md) describe the Python 3.11+/FastAPI backend. Review the chosen tool, dependencies and dataset before starting it. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
```

Supply your own configuration through a private process environment or secret manager. Use [env.template](../env.template) as a field reference:

| Capability | Configuration and source |
|---|---|
| Gemini extraction and summaries | `GOOGLE_AI_API_KEY`; supported aliases in `backend/gemini_client.py` |
| Browser-to-backend connection | `NEXT_PUBLIC_API_URL`, normally `http://localhost:8000` for development |
| Original Mapbox map path | Your public `NEXT_PUBLIC_MAPBOX_TOKEN`; example mode uses MapLibre instead |
| Athena/Overture tools | Your selected AWS account, region, database, workgroup and output bucket, plus access to the data those tools query |
| Local cascade/DIEM search | The parquet files expected by the selected tool and their documented schema/licence |

The current backend loads root `.env.local`, then `backend/.env` with override enabled. Inspect any existing files so their contents match the account you selected. An agent should check variable names and presence while keeping values private. `NEXT_PUBLIC_` fields are browser-visible build inputs.

`backend/agent.py` constructs its Gemini client with a pinned model argument. Review that call and choose a model accepted by your account when commissioning the backend; `GEMINI_MODEL` applies to client calls that leave the model argument unset.

With your selected data and provider configured, the retained entrypoint is:

```sh
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

Run the frontend against that service with example mode disabled. Verify one selected tool from query to response and map layer before expanding the integration. Provider requests and cloud queries use your accounts.

## Dataset and result status

The public example supplies a small generated feature dataset. The historical full London matrix is separately recorded evidence, with distribution rights and provenance documented in [data rights](../DATA-RIGHTS-AND-PROVENANCE.md). Supply the actual parquet inputs or owned cloud dataset for the live search path. Global matrix completion remains unverified in the project record.

[Project overview](../README.md) · [Backend agent](../backend/agent.py) · [Gemini client](../backend/gemini_client.py) · [MIT licence](../LICENSE)
