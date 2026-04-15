# Dashboard — Frontend & Backend

## Overview

The dashboard consists of two services:

- **Express backend** (`dashboard/backend/`) — REST API + WebSocket server + MongoDB persistence
- **Next.js frontend** (`dashboard/frontend/`) — React UI with real-time log display and charts

---

## Express Backend

### Stack

| Package | Version | Purpose |
|---------|---------|---------|
| express | 5.x | HTTP server |
| mongoose | 8.x | MongoDB ODM |
| socket.io | 4.x | WebSocket server |
| body-parser | 2.x | JSON request parsing |
| cors | 2.x | Cross-origin headers |
| os-utils | 0.0.14 | CPU usage polling |
| check-disk-space | 3.x | Disk usage |
| dotenv | 16.x | Environment variables |

### Starting

```bash
cd dashboard/backend/
npm install
node server.js
# or with auto-reload:
npx nodemon server.js
```

Server starts on port **5000**.

### Environment variables

The `.env` file currently only sets `PORT`. The MongoDB URI is **not set** — it is an
empty string in `server.js`. This must be configured before the backend will work.

```env
# dashboard/backend/.env
PORT=5000
MONGO_URI=mongodb://localhost:27017/siem   # add this
```

Update `server.js` line:
```javascript
const mongoURI = process.env.MONGO_URI;
```

### MongoDB Schema

Collection: `logs`

```javascript
{
  log: {
    content: String,
    event_template: String,
    level: String,
    component: String,
    line_id: String
  },
  anomaly_type: String,    // e.g. "memory_error", "authentication_error"
  severity: String,        // "Low" | "Medium" | "High" | "Critical"
  confidence: Number,      // 0.0 – 1.0
  anomaly_score: Number,   // raw MSE reconstruction error
  processing_mode: String, // "sequential" | "single" | "hybrid"
  timestamp: String        // "HH:MM:SS" format
}
```

### WebSocket events

| Event | Direction | Payload | Description |
|-------|-----------|---------|-------------|
| `connection` | client → server | — | Client connects |
| `disconnect` | client → server | — | Client disconnects |
| `new_log` | server → client | Log document | Emitted after each `POST /api/logs` insert |

---

## Next.js Frontend

### Stack

| Package | Version | Purpose |
|---------|---------|---------|
| next | 15.3.1 | React framework |
| react | 19 | UI library |
| socket.io-client | 4.x | WebSocket client |
| chart.js | 4.x | Chart rendering |
| react-chartjs-2 | 5.x | React wrapper for Chart.js |
| react-toastify | 11.x | Toast notifications |
| react-icons | 5.x | Icon set |
| tailwindcss | 4.x | Utility CSS |
| axios | 1.x | HTTP client (imported but fetch used in practice) |

### Starting

```bash
cd dashboard/frontend/
npm install
npm run dev      # development (hot reload, :3000)
npm run build    # production build
npm start        # serve production build
```

Frontend runs on port **3000**.

---

## Pages

### Home (`/`)

**File:** `app/page.js`

Displays:
- **Recent Logs panel** — last 5 logs from the backend, color-coded by threat status
- **Threat Summary pie chart** — threats vs non-threats as percentage
- **Logs & Threats Over Time line chart** — last 10 logs with cumulative threat count

Real-time behavior:
- On mount: `GET http://localhost:5000/api/logs` to load historical data
- Socket.IO subscription to `new_log` events — prepends new logs to state
- Toast notification (top-right, dark theme, 5s) for each new threat

Threat classification — a log is a "threat" if `anomaly_type` is one of:
```javascript
['system_critical', 'authentication_error', 'file_error',
 'network_error', 'permission_error', 'memory error']
```

> Note: `'memory error'` (with space) does not match the model's output `'memory_error'`
> (with underscore). This is a bug — see [improvements.md](./improvements.md).

### Logs (`/pages/logs`)

**File:** `app/pages/logs/page.js`

Full log table with:
- All logs from the backend (last 100 via `GET /api/logs`)
- Real-time updates via Socket.IO
- Severity color coding
- Timestamp formatting

### System Health (`/pages/threats`)

**File:** `app/pages/threats/page.js`

Displays live system metrics from `GET /api/system-health`:
- CPU usage gauge
- Memory usage (total / used / free)
- Disk usage (total / used / free)
- System info (hostname, uptime, platform, CPU cores)

Polls the endpoint on mount. No auto-refresh interval is set — data is static after load.

---

## Navbar (`app/components/navbar.js`)

Responsive navigation bar with three links:

| Label | Route | Icon |
|-------|-------|------|
| Home | `/` | FaHome |
| Logs | `/pages/logs` | FaClipboardList |
| System Health | `/pages/threats` | FaExclamationTriangle |

Mobile hamburger menu collapses links on small screens.

---

## Data Flow

```
1. Python model runs detection
2. ExpressExporter.export_anomalies() → POST http://localhost:5000/api/logs
   Body: JSON array of anomaly objects

3. Express server.js:
   - Validates array
   - Maps to Log schema
   - Log.insertMany() → MongoDB
   - io.emit('new_log', savedLog) for each inserted document
   - Returns 200

4. Next.js frontend:
   - Socket.IO receives 'new_log' event
   - Prepends to logs state
   - If anomaly_type is a threat type → toast notification
   - Charts re-render with updated data
```

---

## Configuration

The backend URL is hardcoded in the frontend as `http://localhost:5000`.
To change it, update these files:
- `app/page.js` — fetch URL and socket URL
- `app/pages/logs/page.js` — fetch URL and socket URL
- `app/pages/threats/page.js` — fetch URL

There is no environment variable for the backend URL in the current implementation.

---

## Known Issues

1. **MongoDB URI is empty** — `server.js` has `const mongoURI = ""`. The backend will crash
   on startup without a valid URI. Must be set via environment variable.

2. **No authentication** — all API endpoints are publicly accessible.

3. **Threat type mismatch** — frontend checks for `'memory error'` (space) but the model
   outputs `'memory_error'` (underscore). Memory errors are never highlighted as threats.

4. **Backend URL hardcoded** — no environment variable support in the frontend.

5. **System health page does not auto-refresh** — metrics are fetched once on mount.

6. **`server.js` is a monolith** — all routes, middleware, DB connection, and WebSocket
   logic are in a single 150-line file.

See [improvements.md](./improvements.md) for planned fixes.
