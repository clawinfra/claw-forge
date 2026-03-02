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

const MOCK_TASKS = MOCK_FEATURES.map((f, i) => ({
  id: String(f.id),
  name: f.name,
  category: "backend",
  status: f.status,
  priority: i + 1,
  depends_on: i > 0 && f.status === 'blocked' ? [String(i)] : [],
  cost_usd: f.cost_usd,
  input_tokens: Math.floor(f.cost_usd * 1000),
  output_tokens: Math.floor(f.cost_usd * 500),
  progress: f.status === 'completed' ? 100 : f.status === 'running' ? Math.floor(Math.random() * 80) + 10 : 0,
  session_id: f.status === 'running' ? `agent_${f.id}` : undefined,
  error_message: f.status === 'failed' ? 'Test assertion failed: expected 200 got 500' : undefined,
  created_at: new Date(Date.now() - (12 - i) * 300000).toISOString(),
  started_at: ['running', 'completed', 'failed'].includes(f.status) ? new Date(Date.now() - (12 - i) * 200000).toISOString() : undefined,
  completed_at: f.status === 'completed' ? new Date(Date.now() - (12 - i) * 100000).toISOString() : undefined,
}));

const MOCK_POOL_STATUS = [
  { name: "claude-oauth", status: "healthy", requests: 142, errors: 0, latency_p50_ms: 1200 },
  { name: "anthropic-direct", status: "healthy", requests: 89, errors: 2, latency_p50_ms: 1450 },
  { name: "groq", status: "degraded", requests: 31, errors: 8, latency_p50_ms: 890 },
];

const MOCK_REGRESSION = {
  run_count: 7,
  last_result: {
    passed: true,
    total: 47,
    failed: 0,
    failed_tests: [],
    duration_ms: 4320,
    run_number: 7,
    implicated_feature_ids: [],
    output: "47 passed, 2 skipped in 4.32s",
  },
};

const MOCK_COMMANDS = [
  { name: "init", description: "Initialize a new project", usage: "claw-forge init <name>" },
  { name: "run", description: "Run the agent harness", usage: "claw-forge run [--spec spec.txt]" },
  { name: "status", description: "Show session status", usage: "claw-forge status [session-id]" },
  { name: "retry", description: "Retry failed features", usage: "claw-forge retry [--all]" },
  { name: "review", description: "Review completed features", usage: "claw-forge review" },
  { name: "ui", description: "Launch the Kanban UI", usage: "claw-forge ui [--port 5173]" },
  { name: "export", description: "Export session report", usage: "claw-forge export [--format json|html]" },
];

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
    name: "my-api",
    total_features: 12,
    passing: 5,
    failing: 2,
    pending: 2,
    in_progress: 2,
    blocked: 1,
    active_agents: 2,
    total_cost_usd: 0.257,
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
