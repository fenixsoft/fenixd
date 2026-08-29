#!/usr/bin/env node
/**
 * dev-server.mjs — Per-run isolated test server for V2 dashboard.
 *
 * Serves static files from the worktree's core/dashboard/static/ directory,
 * and proxies /api/* requests to the main dashboard server (http://127.0.0.1:8787).
 * For SSE (/api/stream), the response is streamed without buffering.
 *
 * Usage:
 *   node dev-server.mjs <static-root> <port>
 *
 * Environment variables (overridden by argv):
 *   STATIC_ROOT — path to static files (default: argv[2])
 *   PORT        — port to listen on (default: argv[3])
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Parse arguments
const staticRoot = process.argv[2] || process.env.STATIC_ROOT;
const port = parseInt(process.argv[3] || process.env.PORT, 10);

if (!staticRoot || !port) {
  console.error('Usage: node dev-server.mjs <static-root> <port>');
  process.exit(1);
}

const UPSTREAM = 'http://127.0.0.1:8787';

// Simple MIME type mapping
const MIME_TYPES = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

const server = http.createServer((req, res) => {
  const parsedUrl = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = parsedUrl.pathname;

  // Proxy API and SSE requests to the main server
  if (pathname.startsWith('/api/')) {
    const isSSE = pathname === '/api/stream';

    const proxyReq = http.request(
      {
        hostname: '127.0.0.1',
        port: 8787,
        path: req.url,
        method: req.method,
        headers: { ...req.headers, host: '127.0.0.1:8787' },
      },
      (proxyRes) => {
        // For SSE, we must forward headers and stream without buffering
        if (isSSE) {
          // Copy important headers (Content-Type, Cache-Control, Connection)
          const headers = {
            'Content-Type': proxyRes.headers['content-type'] || 'text/event-stream',
            'Cache-Control': proxyRes.headers['cache-control'] || 'no-cache',
            'Connection': proxyRes.headers['connection'] || 'keep-alive',
          };
          res.writeHead(proxyRes.statusCode, headers);
          // Pipe the response directly (unbuffered)
          proxyRes.pipe(res);
        } else {
          // For other API responses, forward all headers and body
          res.writeHead(proxyRes.statusCode, proxyRes.headers);
          proxyRes.pipe(res);
        }
      }
    );

    proxyReq.on('error', (err) => {
      console.error(`Proxy error for ${req.url}:`, err.message);
      if (!res.headersSent) {
        res.writeHead(502, { 'Content-Type': 'text/plain' });
      }
      res.end('Bad Gateway: upstream server unreachable');
    });

    // Pipe the request body to the upstream
    req.pipe(proxyReq);
    return;
  }

  // Serve static files from the worktree
  let filePath = path.join(staticRoot, pathname);

  // Missing file → 404. Do NOT fall through to upstream for non-/api paths:
  // the worktree copy must be authoritative for static assets (spec 3.1).
  if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
    res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
    res.end('Not Found');
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('Not Found');
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || 'application/octet-stream';

    res.writeHead(200, { 'Content-Type': contentType });
    res.end(data);
  });
});

server.listen(port, '127.0.0.1', () => {
  console.log(`dev-server listening on http://127.0.0.1:${port}`);
  console.log(`Static root: ${staticRoot}`);
  console.log(`Upstream: ${UPSTREAM}`);
});

// Handle server errors
server.on('error', (err) => {
  console.error('Server error:', err);
  process.exit(1);
});

// Graceful shutdown
process.on('SIGTERM', () => {
  console.log('Received SIGTERM, shutting down...');
  server.close(() => process.exit(0));
});

process.on('SIGINT', () => {
  console.log('Received SIGINT, shutting down...');
  server.close(() => process.exit(0));
});