#!/usr/bin/env python3
"""
Simple static file server for the web frontend.
For MVP testing purposes.
"""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

class CORSRequestHandler(SimpleHTTPRequestHandler):
    """HTTP request handler with CORS enabled."""
    
    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

def main():
    # Change to web directory
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        os.chdir(web_dir)
    
    port = 3000
    server_address = ('', port)
    
    httpd = HTTPServer(server_address, CORSRequestHandler)
    
    print(f"Starting web server on port {port}")
    print(f"Web interface available at: http://localhost:{port}")
    print(f"Serving from: {web_dir}")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down web server...")
        httpd.shutdown()

if __name__ == "__main__":
    main()