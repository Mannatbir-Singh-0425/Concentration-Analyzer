"""
Concentration Analyzer - Desktop App Launcher
Launches the analyzer in a dedicated desktop window or system browser.
"""

import sys
import os
import threading
import time
import webbrowser

def start_server():
    from app import app
    app.run(host="127.0.0.1", port=5000, debug=False)

def main():
    print("=" * 60)
    print("   CONCENTRATION ANALYZER // DESKTOP LAUNCHER")
    print("=" * 60)
    print("Starting background server...")
    
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()
    
    time.sleep(1.2)
    url = "http://127.0.0.1:5000/"

    # Attempt to open via pywebview if installed, otherwise open standard system window
    try:
        import webview
        print("Opening native desktop window...")
        webview.create_window(
            "Concentration Analyzer // QuantLab",
            url,
            width=1280,
            height=850,
            background_color="#0a0d14",
            resizable=True
        )
        webview.start()
    except ImportError:
        print(f"Launching web view at {url}...")
        webbrowser.open(url)
        print("\nApp is running in your browser! Press Ctrl+C in this terminal to quit.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down desktop app.")
            sys.exit(0)

if __name__ == "__main__":
    main()
