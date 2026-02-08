# Server

Backend API for PeerTube Browser. It serves recommendations and video metadata
from the local SQLite dataset and ANN index.

## What it does
- `/api/similar` recommendations (layered pipeline).
- `/api/video` metadata for the video page.
- `/api/user-profile` endpoints (likes/profile).

## Notes
- Reads from `DEFAULT_DB_PATH` and FAISS index.
- Uses local likes by default (client JSON), optional users DB.
