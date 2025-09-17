from flask import Flask, send_from_directory, jsonify, request
import os
import sys
import subprocess
import asyncio
import threading
from scraper import main as scraper_main

app = Flask(__name__, static_folder='')

@app.route('/')
def index():
    return send_from_directory('', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('', path)

@app.route('/open-excel')
def open_excel():
    file_path = os.path.abspath('jobs.xlsx')
    try:
        if sys.platform.startswith("win"):
            os.startfile(file_path)
        elif sys.platform == "darwin":
            subprocess.run(["open", file_path])
        else:
            subprocess.run(["xdg-open", file_path])
        return jsonify({"status": "success", "message": "Excel file opened."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/start-scraping', methods=['POST'])
def start_scraping():
    try:
        data = request.get_json()
        limit = data.get('limit', 5)
        delay = data.get('delay', 5)

        # Run scraper in a separate thread to avoid blocking
        def run_scraper():
            try:
                asyncio.run(scraper_main(limit=limit))
            except Exception as e:
                print(f"Scraper error: {e}")

        thread = threading.Thread(target=run_scraper)
        thread.daemon = True
        thread.start()

        return jsonify({
            "status": "success",
            "message": f"Started scraping {limit} profiles with {delay}s delay between profiles."
        })

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
