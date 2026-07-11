import socket
import threading
import time
import webbrowser
from app import create_app

app = create_app()

def find_free_port(start_port=18088):
    """Finds an available port starting from start_port."""
    port = start_port
    while port < 65535:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return port
            except socket.error:
                port += 1
    return start_port  # Fallback to start_port

def start_browser(port):
    """Waits for the server to start, then opens the browser."""
    time.sleep(1.0)  # Give the server a moment to spin up
    webbrowser.open(f"http://127.0.0.1:{port}")

if __name__ == '__main__':
    # Find a free port starting at 18088 to avoid collisions
    port = find_free_port(18088)
    
    print(f"Starting Optibreed on port {port}...")
    print(f"Opening browser at http://127.0.0.1:{port}")
    
    # Launch browser automatically in a background thread
    threading.Thread(target=start_browser, args=(port,), daemon=True).start()
    
    try:
        from waitress import serve
        serve(app, host='0.0.0.0', port=port, threads=4)
    except ImportError:
        # Run the Flask app on all interfaces for local network access
        # Disabling debug mode prevents duplicate browser windows from opening.
        app.run(host='0.0.0.0', port=port, debug=False)

