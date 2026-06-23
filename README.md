# Our Cool Project

<!-- TODO: Shortly explain what this project is about -->

## Background

<p align="center">
  <img alt="Hack4Rail Logo" src="img/hack4rail-logo.jpg" width="400"/>
</p>

This project has been initiated during the [Hack4Rail 2026](https://hack4rail.org/), a joint hackathon organised by the railway companies SBB, ÖBB, and DB in partnership with the OpenRail Association.

## Install

### Prerequisites

- Python 3.10+
- Node.js 18+

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
