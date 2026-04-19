"""Dashboard web app and proxy API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from api.routes import account_manager, proxy_manager, session_manager, snap_sender, upsell_strategy

app = FastAPI(title="Snapchat Bot Dashboard")


@app.get("/", response_class=HTMLResponse)
def dashboard_home() -> str:
    """Serve dashboard HTML shell."""
    return """
    <!doctype html>
    <html>
      <head>
        <meta charset=\"utf-8\" />
        <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\" />
        <title>Snapchat Bot Dashboard</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 24px; background: #0b1220; color: #e5e7eb; }
          .panel { background: #111827; border: 1px solid #1f2937; border-radius: 10px; padding: 16px; margin-bottom: 16px; }
          table { width: 100%; border-collapse: collapse; }
          th, td { border-bottom: 1px solid #1f2937; text-align: left; padding: 8px; }
        </style>
      </head>
      <body>
        <h1>Snapchat Bot Automation Dashboard</h1>
        <div id=\"account-health\" class=\"panel\"></div>
        <div id=\"snap-status\" class=\"panel\"></div>
        <script src=\"/components/AccountHealth.js\"></script>
        <script src=\"/components/SnapStatus.js\"></script>
      </body>
    </html>
    """


@app.get("/components/{name}")
def serve_component(name: str) -> FileResponse:
    """Serve frontend dashboard JS components."""
    component_map = {
        "AccountHealth.js": Path("dashboard/components/AccountHealth.js").resolve(),
        "SnapStatus.js": Path("dashboard/components/SnapStatus.js").resolve(),
    }
    path = component_map.get(name)
    if path is None:
        raise HTTPException(status_code=404, detail="Component not found")
    return FileResponse(path)


@app.get("/dashboard/api/accounts")
def dashboard_accounts() -> JSONResponse:
    """Proxy endpoint returning account list for dashboard."""
    return JSONResponse(content=account_manager.list_active_accounts())


@app.get("/dashboard/api/stats")
def dashboard_stats() -> JSONResponse:
    """Proxy endpoint returning stats for dashboard."""
    sent = sum(1 for s in snap_sender.delivery_status.values() if s.get("status") == "sent")
    failed = sum(1 for s in snap_sender.delivery_status.values() if s.get("status") == "failed")
    payload = {
        "active_accounts": len(account_manager.list_active_accounts()),
        "active_sessions": session_manager.get_active_sessions(),
        "proxy_stats": proxy_manager.get_proxy_stats(),
        "snap_sent": sent,
        "snap_failed": failed,
        "upsell": upsell_strategy.get_upsell_stats(),
    }
    return JSONResponse(content=payload)
