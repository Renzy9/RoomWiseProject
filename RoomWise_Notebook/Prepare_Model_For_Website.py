"""Copy notebook exports into the sibling RoomWise Flask system. No training."""
from pathlib import Path
import json
import shutil
import pandas as pd

HERE = Path(__file__).resolve().parent
source = HERE / 'artifacts'
destination = HERE.parent / 'RoomWise' / 'artifacts'
if not (destination.parent / 'app.py').exists():
    raise FileNotFoundError('Extract the RoomWise system folder beside RoomWise_Notebook first.')
destination.mkdir(exist_ok=True)

shutil.copy2(source / 'roomwise_pipeline.pkl', destination / 'roomwise_pipeline.pkl')
shutil.copy2(source / 'metadata.json', destination / 'metadata.json')

records = pd.read_csv(source / 'test_predictions.csv')
features = ['Temperature', 'Humidity', 'Light', 'CO2']
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
    inputs = {}
    for feature in features:
        inputs[feature] = float(row[feature])
    samples.append({
        'name': name,
        'inputs': inputs,
        'actual': int(row.Actual),
        'timestamp': str(row.Timestamp)
    })
with open(destination / 'demo_samples.json', 'w') as file:
    json.dump(samples, file, indent=2)
print('Copied PKL, metadata, and recorded examples to:', destination)
print('Restart Flask after replacing a model.')
