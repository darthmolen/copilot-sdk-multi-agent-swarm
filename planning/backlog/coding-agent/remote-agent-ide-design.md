# Remote Swarm Agent — IDE & Access Design

## Problem Statement

The swarm agent needs to be remotely deployable with two access modes:
1. **Developer access** — full IDE for debugging, inspecting, and managing agent-created files
2. **End-user access** — embedded editor/file browser baked into the agent's SPA UI

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Agent Server                      │
│                                                     │
│  ┌─────────────┐   ┌─────────────┐   ┌──────────┐  │
│  │ code-server │   │   SPA :3000 │   │   SSH    │  │
│  │   :8080     │   │  + Monaco   │   │  :22     │  │
│  └─────────────┘   └──────┬──────┘   └──────────┘  │
│                           │                         │
│                    ┌──────▼──────┐                  │
│                    │  File API   │                  │
│                    │ (Express or │                  │
│                    │  FastAPI)   │                  │
│                    └──────┬──────┘                  │
│                           │                         │
│                    ┌──────▼──────┐                  │
│                    │   Agent     │                  │
│                    │  Workspace  │                  │
│                    │  /workspace │                  │
│                    └─────────────┘                  │
└─────────────────────────────────────────────────────┘
              ↕ Tailscale (private mesh)
        Your machine / other agents
```

---

## Track 1: Developer Access (Full IDE)

### Option A — code-server (Self-Hosted VS Code)
- Runs full VS Code in the browser
- Scoped to `/workspace` directory
- Auth: password or OAuth
- Put behind Nginx + HTTPS + Tailscale

```bash
# Dockerfile snippet
RUN curl -fsSL https://code-server.dev/install.sh | sh
CMD ["code-server", "--bind-addr", "0.0.0.0:8080", "--auth", "password", "/workspace"]
```

### Option B — VS Code Tunnels (Zero-Infra)
- Uses Microsoft relay, auth via GitHub
- No ports to open, no infra to manage
- Good for ephemeral/ad-hoc deployments

```bash
code tunnel --name my-swarm-agent --accept-server-license-terms
```

### Option C — VS Code Remote SSH (Classic)
- Nothing extra to install server-side
- Works natively from VS Code desktop
- Pair with Tailscale to avoid exposing SSH publicly

---

## Track 2: Embedded Editor in SPA

### Stack
- **Monaco Editor** (`@monaco-editor/react`) — VS Code engine as a component
- **react-complex-tree** or **rc-tree** — file tree UI
- **File API** — thin backend layer to read/write agent workspace

### Monaco Component (sketch)

```tsx
import Editor from "@monaco-editor/react";

interface CodeEditorProps {
  filePath: string;
  content: string;
  language: string;
  onChange: (value: string) => void;
}

export function CodeEditor({ filePath, content, language, onChange }: CodeEditorProps) {
  return (
    <Editor
      height="100%"
      language={language}
      value={content}
      theme="vs-dark"
      onChange={(val) => onChange(val ?? "")}
      options={{
        minimap: { enabled: true },
        fontSize: 14,
        wordWrap: "on",
        automaticLayout: true,
      }}
    />
  );
}
```

### File Tree + Editor Layout (sketch)

```tsx
// Layout: sidebar file tree + main editor panel
<div style={{ display: "flex", height: "100vh" }}>
  <FileTree
    width={260}
    onFileSelect={(path) => loadFile(path)}
  />
  <CodeEditor
    filePath={activeFile}
    content={fileContent}
    language={detectLanguage(activeFile)}
    onChange={handleEdit}
  />
</div>
```

---

## File API (Backend)

Thin Express or FastAPI layer over `/workspace`.

### Endpoints

| Method | Route | Description |
|--------|-------|-------------|
| `GET` | `/api/files` | Recursive directory listing |
| `GET` | `/api/files/*path` | Read file contents |
| `PUT` | `/api/files/*path` | Write / update file |
| `DELETE` | `/api/files/*path` | Delete file |
| `POST` | `/api/files/*path` | Create new file or directory |

### Express Sketch

```ts
import express from "express";
import fs from "fs/promises";
import path from "path";

const WORKSPACE = process.env.WORKSPACE_DIR ?? "/workspace";
const router = express.Router();

router.get("/files/*", async (req, res) => {
  const filePath = path.join(WORKSPACE, req.params[0]);
  const content = await fs.readFile(filePath, "utf-8");
  res.json({ path: req.params[0], content });
});

router.put("/files/*", async (req, res) => {
  const filePath = path.join(WORKSPACE, req.params[0]);
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, req.body.content, "utf-8");
  res.json({ ok: true });
});

// TODO: directory listing, delete, create
```

---

## Security Model

### Tailscale (Recommended)
- Private WireGuard mesh between your machines
- No public ports needed for SSH or code-server
- Free tier handles most use cases
- Works across cloud providers, laptops, VMs

### Nginx Reverse Proxy (If Public)
```nginx
server {
    listen 443 ssl;
    server_name agent.yourdomain.com;

    location /ide/ {
        proxy_pass http://localhost:8080/;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection upgrade;
        # Add auth here (basic auth, OAuth, etc.)
    }

    location /api/ {
        proxy_pass http://localhost:3001/api/;
        # JWT validation middleware recommended
    }
}
```

### Auth Considerations
- code-server: built-in password, or proxy through your auth provider
- File API: JWT issued by your agent's auth system
- SPA: same auth session as the rest of your app

---

## Docker Compose (Full Stack)

```yaml
version: "3.9"

services:
  agent:
    build: ./agent
    volumes:
      - workspace:/workspace
    environment:
      - WORKSPACE_DIR=/workspace

  file-api:
    build: ./file-api
    ports:
      - "3001:3001"
    volumes:
      - workspace:/workspace
    environment:
      - WORKSPACE_DIR=/workspace
      - JWT_SECRET=${JWT_SECRET}

  spa:
    build: ./spa
    ports:
      - "3000:3000"
    depends_on:
      - file-api

  code-server:
    image: codercom/code-server:latest
    ports:
      - "8080:8080"
    volumes:
      - workspace:/workspace
    environment:
      - PASSWORD=${CODE_SERVER_PASSWORD}
    command: ["--bind-addr", "0.0.0.0:8080", "/workspace"]

volumes:
  workspace:
```

---

## Open Questions / TODOs

- [ ] **Auth strategy** — shared JWT across SPA + File API, or separate sessions?
- [ ] **Real-time updates** — WebSocket or SSE to push file changes from agent → Monaco?
- [ ] **Read-only vs editable** — should end users be able to edit agent files, or just inspect?
- [ ] **Multi-agent workspaces** — one `/workspace` per agent instance, or shared?
- [ ] **code-server vs Tunnels** — depends on deployment target (VPS = code-server, serverless-ish = Tunnels)
- [ ] **File API language detection** — map extensions → Monaco language IDs
- [ ] **Diff view** — Monaco has a built-in diff editor, useful for showing agent changes
- [ ] **Terminal in SPA** — xterm.js for an embedded terminal if you want to go full IDE in-app

---

## Relevant Packages

```json
{
  "dependencies": {
    "@monaco-editor/react": "^4.6.0",
    "react-complex-tree": "^2.1.0",
    "xterm": "^5.3.0",
    "xterm-addon-fit": "^0.8.0"
  }
}
```

```txt
code-server     → https://github.com/coder/code-server
Tailscale       → https://tailscale.com
Monaco Editor   → https://github.com/suren-atoyan/monaco-react
react-complex-tree → https://rct.lukasbach.com
xterm.js        → https://xtermjs.org
```
