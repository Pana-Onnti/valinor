/**
 * Valinor API — Cloudflare Workers proxy
 *
 * Responsibilities:
 *  - Health check shortcut at /health (never proxied upstream)
 *  - CORS preflight (OPTIONS) handling
 *  - Security header injection on every response
 *  - CF-Ray and X-Worker-Version response headers
 *  - IP-level request logging (true rate-limit enforcement requires KV /
 *    Durable Objects and is noted as a TODO)
 *  - Transparent reverse-proxy to API_BACKEND_URL for all other paths
 */

const WORKER_VERSION = "1.0.0";

// ---------------------------------------------------------------------------
// Environment bindings
// ---------------------------------------------------------------------------

export interface Env {
  /** Full URL of the upstream FastAPI backend, e.g. https://api.valinor.internal */
  API_BACKEND_URL: string;
  /** One of: production | staging | development */
  ENVIRONMENT: string;
}

// ---------------------------------------------------------------------------
// Security headers — appended to every outgoing response
// ---------------------------------------------------------------------------

const SECURITY_HEADERS: Record<string, string> = {
  "X-Frame-Options": "DENY",
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "X-XSS-Protection": "1; mode=block",
};

// ---------------------------------------------------------------------------
// CORS helpers
// ---------------------------------------------------------------------------

const ALLOWED_ORIGINS = new Set([
  "https://valinor.app",
  "https://dashboard.valinor.app",
  "https://valinor-staging.vercel.app",
]);

function corsHeaders(origin: string | null): Record<string, string> {
  const allowed =
    origin && ALLOWED_ORIGINS.has(origin) ? origin : "https://valinor.app";

  return {
    "Access-Control-Allow-Origin": allowed,
    "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
    "Access-Control-Allow-Headers":
      "Content-Type, Authorization, X-Requested-With",
    "Access-Control-Max-Age": "86400",
    "Vary": "Origin",
  };
}

// ---------------------------------------------------------------------------
// IP-based rate-limit logging
//
// TODO: Replace with true enforcement once KV / Durable Objects are bound.
//       For now every request is logged with its connecting IP so that
//       downstream log analysis can apply thresholds retroactively.
// ---------------------------------------------------------------------------

function logRateInfo(request: Request): void {
  const ip =
    request.headers.get("CF-Connecting-IP") ??
    request.headers.get("X-Forwarded-For")?.split(",")[0].trim() ??
    "unknown";

  console.log(
    JSON.stringify({
      event: "request",
      ip,
      method: request.method,
      url: request.url,
      ts: new Date().toISOString(),
    })
  );
}

// ---------------------------------------------------------------------------
// Response builders
// ---------------------------------------------------------------------------

function workerHeaders(
  request: Request,
  origin: string | null,
  upstream?: Response
): Record<string, string> {
  const cfRay =
    request.headers.get("CF-Ray") ??
    (upstream ? upstream.headers.get("CF-Ray") : null) ??
    "";

  return {
    ...SECURITY_HEADERS,
    ...corsHeaders(origin),
    "CF-Ray": cfRay,
    "X-Worker-Version": WORKER_VERSION,
  };
}

function jsonResponse(
  body: unknown,
  status: number,
  extra: Record<string, string>
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json;charset=UTF-8",
      ...extra,
    },
  });
}

// ---------------------------------------------------------------------------
// Main fetch handler
// ---------------------------------------------------------------------------

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const origin = request.headers.get("Origin");

    // Log every request for observability (and future rate-limit enforcement)
    logRateInfo(request);

    // ------------------------------------------------------------------
    // 1. CORS preflight
    // ------------------------------------------------------------------
    if (request.method === "OPTIONS") {
      return new Response(null, {
        status: 204,
        headers: workerHeaders(request, origin),
      });
    }

    // ------------------------------------------------------------------
    // 2. Health check shortcut — never proxied upstream
    // ------------------------------------------------------------------
    if (url.pathname === "/health") {
      return jsonResponse(
        { status: "ok", worker: "valinor-api" },
        200,
        workerHeaders(request, origin)
      );
    }

    // ------------------------------------------------------------------
    // 3. Proxy to backend
    // ------------------------------------------------------------------
    const backendBase = (env.API_BACKEND_URL ?? "").replace(/\/$/, "");

    if (!backendBase) {
      return jsonResponse(
        { error: "Configuration error: API_BACKEND_URL is not set." },
        500,
        workerHeaders(request, origin)
      );
    }

    const targetUrl = `${backendBase}${url.pathname}${url.search}`;

    // Clone incoming headers and inject forwarding metadata
    const proxyHeaders = new Headers(request.headers);
    proxyHeaders.set(
      "X-Forwarded-For",
      request.headers.get("CF-Connecting-IP") ??
        request.headers.get("X-Forwarded-For") ??
        "unknown"
    );
    proxyHeaders.set("X-Forwarded-Host", url.hostname);
    proxyHeaders.set("X-Forwarded-Proto", url.protocol.replace(":", ""));
    proxyHeaders.set("X-Worker-Environment", env.ENVIRONMENT ?? "production");
    // Strip the incoming Host so the upstream receives its own hostname
    proxyHeaders.delete("Host");

    let backendResponse: Response;

    try {
      backendResponse = await fetch(targetUrl, {
        method: request.method,
        headers: proxyHeaders,
        body:
          request.method !== "GET" && request.method !== "HEAD"
            ? request.body
            : undefined,
        // Expose redirects to the caller rather than following silently
        redirect: "manual",
      });
    } catch (err) {
      console.error("[valinor-worker] Upstream fetch failed:", err);
      return jsonResponse(
        {
          error: "Bad gateway",
          message: "The upstream API is temporarily unreachable. Please retry.",
        },
        502,
        workerHeaders(request, origin)
      );
    }

    // ------------------------------------------------------------------
    // 4. Decorate the upstream response with worker headers
    // ------------------------------------------------------------------
    const responseHeaders = new Headers(backendResponse.headers);

    for (const [key, value] of Object.entries(
      workerHeaders(request, origin, backendResponse)
    )) {
      responseHeaders.set(key, value);
    }

    return new Response(backendResponse.body, {
      status: backendResponse.status,
      statusText: backendResponse.statusText,
      headers: responseHeaders,
    });
  },
} satisfies ExportedHandler<Env>;
