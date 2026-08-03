# OpenCROW Constellation

OpenCROW Constellation is the multi-agent coordination core of OpenCROW. It provides topic management, directive broadcasting, lifecycle artifact synchronization, native resumable sessions for all supported providers, and GridFS artifact storage.

## Running Constellation with Docker Compose

1. Extract the release package:
   ```bash
   unzip opencrow-constellation.zip -d opencrow-constellation
   cd opencrow-constellation/services/constellation
   ```

2. Start the services:
   ```bash
   docker compose up -d --build
   ```

3. Check service status:
   ```bash
   docker compose ps
   ```

The backend runs on port `8787`, and the UI dashboard is available at `http://localhost:8788`.

## Architecture Components

- **Backend**: Tornado REST & Websocket event orchestration engine.
- **UI**: Flask web dashboard for monitoring topics, live chat, and artifacts.
- **MongoDB & GridFS**: Document database for persistent topic logs and immutable file artifacts.
- **Trusted runtime hosts**: Provider-neutral adapters for Codex, OpenCode, Claude Code, and Antigravity. These hosts execute agents in full-auto mode and must be isolated accordingly.
