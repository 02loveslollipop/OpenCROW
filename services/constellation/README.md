# OpenCROW Constellation

OpenCROW Constellation is the multi-agent coordination core of OpenCROW. It provides topic management, directive broadcasting, finding/changelog corpus synchronization, resumable Codex sessions, and GridFS artifact storage.

## Running Constellation with Docker Compose

1. Extract the release package:
   ```bash
   unzip opencrow-constellation.zip
   cd opencrow-constellation
   ```

2. Start the services:
   ```bash
   docker compose up -d --build
   ```

3. Check service status:
   ```bash
   docker compose ps
   ```

The backend server will run on port `8080` (or `8000`), and the UI web dashboard will be available at `http://localhost:5000`.

## Architecture Components

- **Backend**: Tornado REST & Websocket event orchestration engine.
- **UI**: Flask web dashboard for monitoring topics, live chat, and artifacts.
- **MongoDB & GridFS**: Document database for persistent topic logs and immutable file artifacts.
