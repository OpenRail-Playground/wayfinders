# A Spatial AI Wayfinding Agent for Railway Stations

This project implements LLM-enhanced indoor navigation in railway stations that enables navigation using natural language input and output. Users can specify their navigation request in free-form text and receive a textual step-by-step description of the route based on POIs as landmarks in the station.

LLM-based processing steps translate
- the user's request into start and destination geographical coordinates and levels
- the found geographical route into a list of instructions that reference easily visible waypoints for the user to orient himself.

The routing itself relies on an existing routing API.

## Background

<p align="center">
  <img alt="Hack4Rail Logo" src="img/hack4rail-logo.jpg" width="400"/>
</p>

This project has been initiated during the [Hack4Rail 2026](https://hack4rail.org/), a joint hackathon organised by the railway companies SBB, ÖBB, and DB in partnership with the OpenRail Association.

## Install

### Prerequisites

- Python 3.10+
- Node.js 18+

As-is, this code base only works within the VPN of Deutsche Bahn and with suitable API keys for calling the DB GenAI Hub (which provides the LLMs to use) and the RIS-Maps API.

### Environment variables

Copy the `.env` file to the project root (or ensure it exists). It must contain:

```
RIMAPS_BASE_URL=...
RIMAPS_USER=...
RIMAPS_PASSWORD=...
GENAI_API_KEY=...
GENAI_ENDPOINT=...
```

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start the development server:

```bash
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
```

Start the development server:

```bash
npm run dev
```

The frontend runs on http://localhost:3000 and connects to the backend at http://localhost:8000.

## License

The content of this repository is licensed under the [Apache 2.0 license](LICENSE).
