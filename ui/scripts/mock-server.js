#!/usr/bin/env node
/**
 * Mock state server for claw-forge Kanban UI screenshots
 * Serves on port 8888
 */

const http = require('http');

const MOCK_FEATURES = [
  { id: 1, name: "User authentication", status: "completed", agent_type: "coding", cost_usd: 0.042, duration_ms: 45000 },
  { id: 2, name: "JWT token refresh", status: "completed", agent_type: "coding", cost_usd: 0.031, duration_ms: 32000 },
  { id: 3, name: "Password reset flow", status: "completed", agent_type: "coding", cost_usd: 0.055, duration_ms: 58000 },
  { id: 4, name: "User profile CRUD", status: "completed", agent_type: "coding", cost_usd: 0.038, duration_ms: 41000 },
  { id: 5, name: "File upload endpoint", status: "completed", agent_type: "coding", cost_usd: 0.029, duration_ms: 28000 },
  { id: 6, name: "Stripe payment integration", status: "running", agent_type: "coding", cost_usd: 0.011, duration_ms: null },
  { id: 7, name: "Email notification service", status: "running", agent_type: "coding", cost_usd: 0.008, duration_ms: null },
  { id: 8, name: "Admin dashboard", status: "pending", agent_type: "coding", cost_usd: 0, duration_ms: null },
  { id: 9, name: "Analytics tracking", status: "pending", agent_type: "coding", cost_usd: 0, duration_ms: null },
  { id: 10, name: "Rate limiting middleware", status: "failed", agent_type: "coding", cost_usd: 0.019, duration_ms: 22000 },
  { id: 11, name: "WebSocket chat feature", status: "failed", agent_type: "coding", cost_usd: 0.024, duration_ms: 31000 },
  { id: 12, name: "Two-factor authentication", status: "blocked", agent_type: "coding", cost_usd: 0, duration_ms: null },
];

const MOCK_SESSION = {
  id: "sess_demo_001",
  name: "my-api v1.0",
  project: "my-api",
  status: "running",
  created_at: new Date(Date.now() - 3600000).toISOString(),
  updated_at: new Date().toISOString(),
  features: MOCK_FEATURES,
  total_cost_usd: MOCK_FEATURES.reduce((sum, f) => sum + f.cost_usd, 0).toFixed(3),
  completed: MOCK_FEATURES.filter(f => f.status === 'completed').length,
  running: MOCK_FEATURES.filter(f => f.status === 'running').length,
  pending: MOCK_FEATURES.filter(f => f.status === 'pending').length,
  failed: MOCK_FEATURES.filter(f => f.status === 'failed').length,
  blocked: MOCK_FEATURES.filter(f => f.status === 'blocked').length,
};

const MOCK_TASKS = MOCK_FEATURES.map(f => ({
  id: f.id,
  feature_id: f.id,
  name: f.name,
  status: f.status,
  agent_type: f.agent_type,
  cost_usd: f.cost_usd,
  duration_ms: f.duration_ms,
  created_at: new Date(Date.now() - Math.random() * 3600000).toISOString(),
}));

const MOCK_POOL_STATUS = {
  providers: [
    { name: "claude-oauth", status: "healthy", requests: 142, errors: 0, latency_p50_ms: 1200 },
    { name: "anthropic-direct", status: "healthy", requests: 89, errors: 2, latency_p50_ms: 1450 },
    { name: "groq", status: "degraded", requests: 31, errors: 8, latency_p50_ms: 890 },
  ],
  total_requests: 262,
  total_cost_usd: 0.257,
};

const MOCK_REGRESSION = {
  run_count: 7,
  last_result: {
    passed: true,
    total: 47,
    failed: 0,
    skipped: 2,
    duration_ms: 4320,
    run_at: new Date(Date.now() - 600000).toISOString(),
  },
};

const MOCK_COMMANDS = {
  commands: [
    { name: "init", description: "Initialize a new project", usage: "claw-forge init <name>" },
    { name: "run", description: "Run the agent harness", usage: "claw-forge run [--spec spec.txt]" },
    { name: "status", description: "Show session status", usage: "claw-forge status [session-id]" },
    { name: "retry", description: "Retry failed features", usage: "claw-forge retry [--all]" },
    { name: "review", description: "Review completed features", usage: "claw-forge review" },
    { name: "ui", description: "Launch the Kanban UI", usage: "claw-forge ui [--port 5173]" },
    { name: "export", description: "Export session report", usage: "claw-forge export [--format json|html]" },
  ],
};

function sendJson(res, data, status = 200) {
  const body = JSON.stringify(data, null, 2);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': '*',
    'Content-Length': Buffer.byteLength(body),
  });
  res.end(body);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:8888`);
  const path = url.pathname;

  if (req.method === 'OPTIONS') {
    res.writeHead(204, { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': '*', 'Access-Control-Allow-Methods': '*' });
    res.end();
    return;
  }

  if (path === '/health') return sendJson(res, { status: 'ok' });
  if (path === '/sessions') return sendJson(res, [MOCK_SESSION]);
  if (path.match(/^\/sessions\/[^/]+$/) && !path.includes('/tasks') && !path.includes('/summary')) return sendJson(res, MOCK_SESSION);
  if (path.match(/^\/sessions\/[^/]+\/tasks$/)) return sendJson(res, MOCK_TASKS);
  if (path.match(/^\/sessions\/[^/]+\/summary$/)) return sendJson(res, {
    project_path: "my-api",
    total: 12, completed: 5, running: 2, pending: 2, failed: 2, blocked: 1,
    total_cost_usd: MOCK_SESSION.total_cost_usd,
  });
  if (path === '/pool/status') return sendJson(res, MOCK_POOL_STATUS);
  if (path === '/regression/status') return sendJson(res, MOCK_REGRESSION);
  if (path === '/commands/list') return sendJson(res, MOCK_COMMANDS);

  sendJson(res, { error: 'Not found' }, 404);
});

// Try to use ws for WebSocket support
let wss;
try {
  const { WebSocketServer } = require('ws');
  wss = new WebSocketServer({ server });
  let featureIdx = 0;
  wss.on('connection', (ws) => {
    const interval = setInterval(() => {
      const feature = MOCK_FEATURES[featureIdx % MOCK_FEATURES.length];
      featureIdx++;
      ws.send(JSON.stringify({ type: 'feature_update', data: feature }));
    }, 3000);
    ws.on('close', () => clearInterval(interval));
  });
  console.log('WebSocket support enabled');
} catch (e) {
  console.log('WebSocket not available (ws module not installed), HTTP only');
}

server.listen(8888, () => {
  console.log('Mock server running on http://localhost:8888');
});
