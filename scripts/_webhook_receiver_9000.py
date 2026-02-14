"""临时接收端：打印 POST 的 path、X-JoyGate-Signature、body，用于验证 secret=null 不签名。"""
from http.server import BaseHTTPRequestHandler, HTTPServer

class H(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        print("\n--- received ---")
        print("path:", self.path)
        print("X-JoyGate-Signature:", repr(self.headers.get("X-JoyGate-Signature")))
        print("body:", body.decode("utf-8", "ignore")[:500])
        self.send_response(204)
        self.end_headers()
    def log_message(self, *args): pass

if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9000), H).serve_forever()
