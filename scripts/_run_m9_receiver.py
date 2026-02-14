"""Minimal webhook receiver for run_m9_webhook_full_chain: bind 127.0.0.1:9001, return 200 for POST."""
from http.server import HTTPServer, BaseHTTPRequestHandler

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")
    def log_message(self, *a):
        pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9001), H).serve_forever()
