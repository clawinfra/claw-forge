#!/usr/bin/env node
/**
 * Mock state server for claw-forge Kanban UI screenshots
 * Serves on port 8888
 */

const http = require('http');

const MOCK_FEATURES = [
  { id: "f-001", name: "User authentication",       category: "Auth",       status: "completed", cost_usd: 0.042 },
  { id: "f-002", name: "JWT token refresh",          category: "Auth",       status: "completed", cost_usd: 0.031 },
  { id: "f-003", name: "Password reset flow",        category: "Auth",       status: "completed", cost_usd: 0.055 },
  { id: "f-004", name: "User profile CRUD",          category: "Users",      status: "completed", cost_usd: 0.038 },
  { id: "f-005", name: "File upload endpoint",       category: "Storage",    status: "completed", cost_usd: 0.029 },
  { id: "f-006", name: "Stripe payment integration", category: "Payments",   status: "running",   cost_usd: 0.011 },
  { id: "f-007", name: "Email notification service", category: "Messaging",  status: "running",   cost_usd: 0.008 },
  { id: "f-008", name: "Admin dashboard",            category: "Admin",      status: "pending",   cost_usd: 0 },
  { id: "f-009", name: "Analytics tracking",         category: "Analytics",  status: "pending",   cost_usd: 0 },
  { id: "f-010", name: "Rate limiting middleware",   category: "API",        status: "failed",    cost_usd: 0.019 },
  { id: "f-011", name: "WebSocket chat feature",     category: "Messaging",  status: "failed",    cost_usd: 0.024 },
  { id: "f-012", name: "Two-factor authentication",  category: "Auth",       status: "blocked",   cost_usd: 0 },
  { id: "f-013", name: "OAuth2 social login",        category: "Auth",       status: "completed", cost_usd: 0.036 },
  { id: "f-014", name: "Role-based access control",  category: "Auth",       status: "completed", cost_usd: 0.041 },
  { id: "f-015", name: "API rate limiter config",    category: "API",        status: "running",   cost_usd: 0.006 },
  { id: "f-016", name: "Database migration system",  category: "Database",   status: "completed", cost_usd: 0.033 },
  { id: "f-017", name: "Audit log tracking",         category: "Monitoring", status: "pending",   cost_usd: 0 },
  { id: "f-018", name: "Health check endpoints",     category: "API",        status: "completed", cost_usd: 0.018 },
];

const MOCK_SESSION = {
  id: "sess_demo_001",
  project_path: "/home/user/my-api",
  status: "running",
  created_at: new Date(Date.now() - 3600000).toISOString(),
  task_count: MOCK_FEATURES.length,
};

const MOCK_TASKS = MOCK_FEATURES.map((f, i) => ({
  id: f.id,
  name: f.name,
  plugin_name: "coding",
  category: f.category,
  description: `${f.name}: Full implementation of ${f.name.toLowerCase()}`,
  status: f.status,
  priority: i,
  depends_on: f.status === 'blocked' ? ["f-003"] : [],
  steps: [],
  cost_usd: f.cost_usd,
  input_tokens: Math.floor(f.cost_usd * 30000),
  output_tokens: Math.floor(f.cost_usd * 8000),
  active_subagents: f.status === 'running' ? 1 : 0,
  error_message: f.status === 'failed' ? 'Test assertion failed: expected 200 got 500' : null,
  result_json: f.status === 'completed' ? { output: "Feature implemented successfully" } : null,
  created_at: new Date(Date.now() - (18 - i) * 300000).toISOString(),
  started_at: ['running', 'completed', 'failed'].includes(f.status) ? new Date(Date.now() - (18 - i) * 200000).toISOString() : null,
  completed_at: f.status === 'completed' ? new Date(Date.now() - (18 - i) * 100000).toISOString() : null,
}));

const MOCK_POOL_STATUS = {
  active: true,
  strategy: "PRIORITY",
  model_aliases: {
    low: "claude-haiku-4-5-20251001",
    med: "claude-sonnet-4-6",
    high: "claude-opus-4-6",
  },
  providers: [
    {
      name: "claude-oauth",
      type: "anthropic_oauth",
      health: "healthy",
      enabled: true,
      rpm: 14,
      max_rpm: 60,
      circuit_state: "closed",
      total_cost_usd: 0.142,
      avg_latency_ms: 1200,
      model: "claude-sonnet-4-6",
      priority: 1,
      model_map: {
        low: "claude-haiku-4-5-20251001",
        med: "claude-sonnet-4-6",
        high: "claude-opus-4-6",
      },
      active_tiers: ["low", "med", "high"],
    },
    {
      name: "anthropic-direct",
      type: "anthropic",
      health: "healthy",
      enabled: true,
      rpm: 8,
      max_rpm: 60,
      circuit_state: "closed",
      total_cost_usd: 0.089,
      avg_latency_ms: 1450,
      model: "claude-sonnet-4-6",
      priority: 2,
    },
    {
      name: "bedrock-us",
      type: "bedrock",
      health: "degraded",
      enabled: true,
      rpm: 3,
      max_rpm: 30,
      circuit_state: "half_open",
      total_cost_usd: 0.031,
      avg_latency_ms: 2900,
      model: "anthropic.claude-sonnet-4-6",
      priority: 3,
    },
  ],
};

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
  {
    id: "run",
    label: "Run Agent Harness",
    icon: "⚙️",
    description: "Start the autonomous coding agent on your spec",
    category: "build",
    shortcut: "R",
    args: [{ name: "spec", label: "Spec file", type: "string", optional: true }],
  },
  {
    id: "status",
    label: "Show Session Status",
    icon: "📊",
    description: "Display current session progress and costs",
    category: "monitoring",
    args: [],
  },
  {
    id: "retry",
    label: "Retry Failed Tasks",
    icon: "🔄",
    description: "Reset failed or blocked tasks back to pending",
    category: "fix",
    args: [],
  },
  {
    id: "review",
    label: "Review Completed Features",
    icon: "🔍",
    description: "Run code review on all completed features",
    category: "quality",
    args: [],
  },
  {
    id: "export",
    label: "Export Session Report",
    icon: "📤",
    description: "Export session summary as JSON or HTML",
    category: "save",
    args: [{ name: "format", label: "Format (json|html)", type: "string", optional: true }],
  },
  {
    id: "init",
    label: "Initialize Project",
    icon: "🚀",
    description: "Set up a new claw-forge project",
    category: "setup",
    args: [{ name: "name", label: "Project name", type: "string", optional: false }],
  },
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
  if (path === '/sessions') return sendJson(res, [{
    id: MOCK_SESSION.id,
    project_path: MOCK_SESSION.project_path,
    status: MOCK_SESSION.status,
    created_at: MOCK_SESSION.created_at,
  }]);
  if (path.match(/^\/sessions\/[^/]+$/) && !path.includes('/tasks') && !path.includes('/summary')) return sendJson(res, MOCK_SESSION);
  if (path.match(/^\/sessions\/[^/]+\/tasks$/)) return sendJson(res, MOCK_TASKS);
  if (path.match(/^\/sessions\/[^/]+\/summary$/)) return sendJson(res, {
    name: "my-api",
    total_features: MOCK_FEATURES.length,
    passing: MOCK_FEATURES.filter(f => f.status === 'completed').length,
    failing: MOCK_FEATURES.filter(f => f.status === 'failed').length,
    pending: MOCK_FEATURES.filter(f => f.status === 'pending').length,
    in_progress: MOCK_FEATURES.filter(f => f.status === 'running').length,
    blocked: MOCK_FEATURES.filter(f => f.status === 'blocked').length,
    active_agents: MOCK_FEATURES.filter(f => f.status === 'running').length,
    total_cost_usd: MOCK_FEATURES.reduce((s, f) => s + f.cost_usd, 0),
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
