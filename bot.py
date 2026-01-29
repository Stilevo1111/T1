import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

def run_web_server():
    port = int(os.environ.get("PORT", 10000))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Bot is running")

    server = HTTPServer(("0.0.0.0", port), Handler)
    server.serve_forever()

# Запускаем веб-сервер в отдельном потоке
threading.Thread(target=run_web_server, daemon=True).start()

import main

if __name__ == "__main__":
    main.main()
