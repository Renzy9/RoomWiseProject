"""Validate notebook exports and safely replace the website's artifact set."""
from pathlib import Path
import io
import json
import math
import os
import pickle
import shutil
import tempfile

import pandas as pd
import sklearn

HERE = Path(__file__).resolve().parent
FEATURES = ['Temperature', 'Humidity', 'Light', 'CO2']


def valid_number(value, low, high):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def prepare_exports(source):
    """Read and validate every input before changing any website files."""
    required = ['roomwise_pipeline.pkl', 'metadata.json', 'test_predictions.csv']
    missing = [name for name in required if not (source / name).is_file()]
    if missing:
        raise FileNotFoundError(
            'Run the notebook completely and download its exports first. Missing: '
            + ', '.join(missing))
    contents = {name: (source / name).read_bytes() for name in required}
    metadata = json.loads(contents['metadata.json'].decode('utf-8-sig'))
    if metadata.get('features') != FEATURES:
        raise ValueError('Metadata must list Temperature, Humidity, Light, and CO2 in that order.')
    if metadata.get('versions', {}).get('sklearn') != sklearn.__version__:
        raise ValueError('Use the scikit-learn version recorded in metadata.json before exporting.')
    for name in FEATURES:
        limits = metadata['training_ranges'][name]
        low, high = limits['min'], limits['max']
        if not valid_number(low, -math.inf, math.inf) or not valid_number(high, low, math.inf):
            raise ValueError(f'Invalid training range for {name}.')
    for name in ['training_accuracy', 'validation_accuracy', 'test_accuracy']:
        if not valid_number(metadata.get(name), 0, 1):
            raise ValueError(f'Metadata contains invalid {name}.')
    if not valid_number(metadata.get('gap_points'), 0, 100):
        raise ValueError('Metadata contains an invalid accuracy gap.')
    folds = metadata.get('cv')
    if not isinstance(folds, list) or not folds:
        raise ValueError('Metadata must contain cross-validation fold results.')
    for fold in folds:
        if (not isinstance(fold, dict) or not valid_number(fold.get('Fold'), 1, math.inf)
                or not isinstance(fold.get('Valid'), bool)
                or any(not valid_number(fold.get(name), 0, 100)
                       for name in ['Training (%)', 'Validation (%)', 'Gap (points)'])):
            raise ValueError('Metadata contains invalid cross-validation fold results.')
    json.dumps(metadata, allow_nan=False)

    records = pd.read_csv(io.BytesIO(contents['test_predictions.csv']))
    columns = FEATURES + ['Actual', 'Predicted', 'Timestamp']
    if records.empty or not set(columns).issubset(records.columns):
        raise ValueError('Test predictions must contain readings, Actual, Predicted, and Timestamp.')
    for name in FEATURES + ['Actual', 'Predicted']:
        records[name] = pd.to_numeric(records[name], errors='raise')
        if not records[name].map(math.isfinite).all():
            raise ValueError(f'Test predictions contain missing or non-finite {name} values.')
    if not records[['Actual', 'Predicted']].isin([0, 1]).all().all():
        raise ValueError('Actual and Predicted must contain only 0 or 1.')
    if records['Timestamp'].isna().any():
        raise ValueError('Test predictions contain missing timestamps.')
    pd.to_datetime(records['Timestamp'], errors='raise')

    # Only load exports produced by your own trusted notebook.
    pipeline = pickle.loads(contents['roomwise_pipeline.pkl'])
    if list(pipeline.feature_names_in_) != FEATURES:
        raise ValueError('The saved pipeline features do not match the website.')
    if list(pipeline.classes_) != [0, 1] or not callable(getattr(pipeline, 'predict_proba', None)):
        raise ValueError('The saved model must support occupied and unoccupied probabilities.')
    predictions = pipeline.predict(records[FEATURES])
    if not (predictions == records['Predicted'].to_numpy()).all():
        raise ValueError('The saved model and test predictions do not match. Export them from the same notebook run.')
    if abs(float(metadata['test_accuracy']) - float((predictions == records['Actual']).mean())) > 1e-9:
        raise ValueError('The metadata test accuracy does not match the recorded test results.')

    groups = [
        ('Recorded empty room', records[(records.Actual == 0) & (records.Predicted == 0)]),
        ('Recorded occupied room', records[(records.Actual == 1) & (records.Predicted == 1)]),
        ('A recorded model mistake', records[records.Actual != records.Predicted])
    ]
    samples = []
    for name, rows in groups:
        if rows.empty:
            continue
        row = rows.iloc[0]
        samples.append({
            'name': name,
            'inputs': {feature: float(row[feature]) for feature in FEATURES},
            'actual': int(row.Actual),
            'timestamp': str(row.Timestamp)
        })
    return {
        'roomwise_pipeline.pkl': contents['roomwise_pipeline.pkl'],
        'metadata.json': contents['metadata.json'],
        'demo_samples.json': json.dumps(samples, indent=2, allow_nan=False).encode('utf-8')
    }


def publish_exports(exports, destination):
    """Stage a complete artifact directory and retain the old set on failure."""
    destination = destination.resolve()
    temporary = Path(tempfile.mkdtemp(prefix='.roomwise-export-', dir=destination.parent)).resolve()
    if temporary.parent != destination.parent:
        raise RuntimeError('The staging folder is outside the website directory.')
    staged = temporary / 'new'
    previous = temporary / 'previous'
    cleanup = True
    try:
        if destination.exists():
            shutil.copytree(destination, staged)
        else:
            staged.mkdir()
        for name, content in exports.items():
            (staged / name).write_bytes(content)
        if destination.exists():
            os.replace(destination, previous)
        try:
            os.replace(staged, destination)
        except OSError as update_error:
            if previous.exists():
                try:
                    os.replace(previous, destination)
                except OSError as restore_error:
                    cleanup = False
                    raise RuntimeError(
                        f'Export failed and automatic recovery could not finish. '
                        f'The previous artifacts are preserved at {previous}.') from restore_error
            raise update_error
    finally:
        if cleanup:
            shutil.rmtree(temporary, ignore_errors=True)


def main():
    source = HERE / 'artifacts'
    destination = HERE.parent / 'RoomWise' / 'artifacts'
    if not (destination.parent / 'app.py').is_file():
        raise FileNotFoundError('Keep the RoomWise system folder beside RoomWise_Notebook first.')
    exports = prepare_exports(source)
    publish_exports(exports, destination)
    print('Copied validated PKL, metadata, and recorded examples to:', destination)
    print('Restart Flask after replacing a model.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        raise SystemExit(f'Export failed: {error}') from error
