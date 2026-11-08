"""RoomWise: load the notebook pipeline, validate readings, and predict."""
from pathlib import Path
import json
import math
import pickle
import threading
import urllib.request
import webbrowser

import pandas as pd
from flask import Flask, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

BASE_DIR = Path(__file__).resolve().parent
with open(BASE_DIR / 'artifacts' / 'roomwise_pipeline.pkl', 'rb') as file:
    pipeline = pickle.load(file)
with open(BASE_DIR / 'artifacts' / 'metadata.json') as file:
    metadata = json.load(file)
with open(BASE_DIR / 'artifacts' / 'demo_samples.json') as file:
    samples = json.load(file)

FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2']
LIMITS = {
    'Temperature': (-50, 70),
    'Humidity': (0, 100),
    'Light': (0, 200000),
    'CO2': (200, 100000)
}
app = Flask(__name__, static_folder=str(BASE_DIR / 'static'))
app.config['MAX_CONTENT_LENGTH'] = 16384


@app.errorhandler(HTTPException)
def api_error(error):
    # Preserve HTTP status and headers while giving API callers readable JSON.
    if request.path == '/predict' or request.path.startswith('/api/'):
        messages = {
            413: 'The request is too large. Enter shorter measurement values.',
            500: 'The server could not complete the prediction. Check the RoomWise window and try again.'
        }
        response = error.get_response()
        response.data = app.json.dumps({'error': messages.get(error.code, error.description)})
        response.content_type = 'application/json'
        return response
    return error


@app.get('/')
def home():
    return send_file(BASE_DIR / 'index.html')


@app.get('/health')
def health():
    return jsonify(status='ready', model_loaded=True, application='RoomWise')


@app.get('/api/model')
def model_information():
    return jsonify(metadata)


@app.get('/api/samples')
def recorded_examples():
    return jsonify(samples)


@app.post('/predict')
def predict():
    values = request.get_json(silent=True)
    if not isinstance(values, dict) or set(values) != set(FEATURES):
        return jsonify(error='Supply exactly the four environmental measurements.'), 400

    clean = {}
    errors = {}
    warnings = []
    for name in FEATURES:
        try:
            raw = values[name]
            if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
                raise ValueError()
            value = float(raw)
            low, high = LIMITS[name]
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError()
            clean[name] = value
            observed = metadata['training_ranges'][name]
            if not observed['min'] <= value <= observed['max']:
                warnings.append(
                    f"{name} is outside the training range "
                    f"({observed['min']:.2f} to {observed['max']:.2f}).")
        except (ValueError, TypeError, OverflowError):
            low, high = LIMITS[name]
            errors[name] = f'Enter a number from {low} to {high}.'
    if errors:
        return jsonify(error='Check the highlighted measurements.', fields=errors), 400

    # The PKL includes preprocessing: pass raw readings in the training order.
    frame = pd.DataFrame([clean], columns=FEATURES)
    label = int(pipeline.predict(frame)[0])
    probabilities = pipeline.predict_proba(frame)[0]
    occupied_probability = float(probabilities[list(pipeline.classes_).index(1)])
    if label == 1:
        prediction = 'Occupied'
        suggestion = 'People may be present. Keep services available and confirm room conditions.'
    else:
        prediction = 'Unoccupied'
        suggestion = 'Ask staff to check the room and review unnecessary lighting or cooling.'
    return jsonify(
        label=label, prediction=prediction, inputs=clean, warnings=warnings,
        probabilities={'occupied': occupied_probability, 'unoccupied': 1 - occupied_probability},
        suggestion=suggestion
    )


def open_when_ready():
    # Open a browser only after our local server answers successfully.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open('http://127.0.0.1:5080/health', timeout=5) as response:
            if json.load(response).get('application') == 'RoomWise':
                webbrowser.open('http://127.0.0.1:5080/')
    except (OSError, ValueError):
        print('Open http://127.0.0.1:5080/ once the server says Running.', flush=True)


if __name__ == '__main__':
    from werkzeug.serving import make_server
    # Bind before scheduling the browser: a busy port produces a visible error.
    server = make_server('127.0.0.1', 5080, app, threaded=True)
    print('RoomWise is running: http://127.0.0.1:5080/', flush=True)
    print('Keep this window open. Press Ctrl+C to stop.', flush=True)
    threading.Timer(0.5, open_when_ready).start()
    server.serve_forever()
