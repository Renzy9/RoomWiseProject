// Page controls only. The trained model and prediction code are separate files.
const fields = ['Temperature', 'Humidity', 'Light', 'CO2'];
let model = null;
let inputRevision = 0;
let selectedSample = null;
let predictionRequest = null;
let modelRequest = null;
const predictionTimeoutMs = 15000;

function element(id) {
  return document.getElementById(id);
}

function updatePredictionButton() {
  element('predict').disabled = !model || predictionRequest !== null;
  element('predict').textContent = predictionRequest ? 'Predicting…' : 'Predict occupancy';
}

function cancelPrediction() {
  if (predictionRequest) {
    const previous = predictionRequest;
    predictionRequest = null;
    clearTimeout(previous.timeout);
    previous.controller.abort();
  }
  updatePredictionButton();
}

function showConnectionProblem(message, status = 'Server unavailable') {
  model = null;
  element('model-status').textContent = status;
  element('connection-status').textContent = message;
  element('connection-actions').hidden = false;
  element('retry-connection').hidden = false;
  element('load').disabled = true;
  updatePredictionButton();
}

// API errors may contain JSON or a plain HTML error page from the server.
async function requestJSON(url, options) {
  let response;
  try {
    response = await fetch(url, options);
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    const failure = new Error('Cannot connect to the trained model.');
    failure.connectionFailure = true;
    throw failure;
  }
  let fallback = 'The server returned an unexpected response. Please try again.';
  if (response.status === 413) {
    fallback = 'The request is too large. Enter shorter measurement values.';
  } else if (response.status >= 500) {
    fallback = 'The server could not complete the prediction. Check the RoomWise window and try again.';
  }
  let result;
  try {
    result = await response.json();
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    const failure = new Error(fallback);
    failure.status = response.status;
    failure.connectionFailure = response.ok;
    throw failure;
  }
  if (!response.ok) {
    const failure = new Error(result && result.error || fallback);
    failure.status = response.status;
    failure.fields = result && result.fields;
    throw failure;
  }
  return result;
}

function clearResult() {
  inputRevision++;
  cancelPrediction();
  element('results').hidden = true;
  element('prediction').textContent = 'Waiting for a new prediction';
  element('suggestion').textContent = 'The readings have changed. Select Predict occupancy.';
  element('actual').hidden = true;
  element('warnings').hidden = true;
  element('form-error').textContent = '';
  for (const name of fields) {
    element('error-' + name).textContent = '';
    element(name).removeAttribute('aria-invalid');
  }
}

// Fill the form with one recorded test example. Its actual label is never an input.
element('load').addEventListener('click', function () {
  const index = element('sample').value;
  if (index === '') {
    element('sample-note').textContent = 'Choose a sample, then select Load.';
    return;
  }
  selectedSample = model.samples[Number(index)];
  for (const name of fields) {
    element(name).value = selectedSample.inputs[name];
  }
  clearResult();
  element('sample-note').textContent = 'Recorded on ' + selectedSample.timestamp + '. Predict to compare with its actual status.';
});

// An edited example becomes a manual reading, so its original label no longer applies.
for (const name of fields) {
  element(name).addEventListener('input', function () {
    selectedSample = null;
    element('sample').value = '';
    clearResult();
    element('sample-note').textContent = 'Manual readings. No recorded actual status is available.';
  });
}

function resetForm() {
  HTMLFormElement.prototype.reset.call(element('prediction-form'));
  element('sample').value = '';
  selectedSample = null;
  clearResult();
  element('sample-note').textContent = 'Or enter your own readings below. All four fields are required.';
  element('Temperature').focus();
}

element('reset').addEventListener('click', resetForm);
element('try-again').addEventListener('click', resetForm);

// Send the readings to Flask. Python loads the PKL and applies the trained pipeline.
element('prediction-form').addEventListener('submit', async function (event) {
  event.preventDefault();
  if (!model || predictionRequest) return;
  clearResult();
  const requestRevision = inputRevision;
  const sampleAtSubmit = selectedSample;
  const active = { controller: new AbortController(), timeout: null, timedOut: false };
  predictionRequest = active;
  updatePredictionButton();
  // Bound the whole request, including reading a response body that stalls.
  const deadline = new Promise((resolve, reject) => {
    active.timeout = setTimeout(() => {
      active.timedOut = true;
      active.controller.abort();
      reject(new Error('Prediction timed out.'));
    }, predictionTimeoutMs);
  });
  try {
    const inputs = {};
    for (const name of fields) {
      inputs[name] = element(name).value;
    }
    const result = await Promise.race([requestJSON('/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(inputs),
      signal: active.controller.signal
    }), deadline]);
    if (predictionRequest !== active || requestRevision !== inputRevision) return;
    element('prediction').textContent = result.prediction;
    element('suggestion').textContent = result.suggestion;
    displayInputSummary(result.inputs);
    displayProbabilities(result.probabilities);
    if (sampleAtSubmit) {
      const actual = sampleAtSubmit.actual === 1 ? 'Occupied' : 'Unoccupied';
      const comparison = sampleAtSubmit.actual === result.label
        ? 'The prediction matches this example.'
        : 'The prediction differs. This is a real model mistake.';
      element('actual').textContent = 'Recorded actual: ' + actual + '. ' + comparison;
      element('actual').hidden = false;
    }
    if (result.warnings.length > 0) {
      element('warnings').textContent = result.warnings.join('\n') + '\nThese readings differ from the training conditions. Interpret cautiously.';
      element('warnings').hidden = false;
    }
    element('results').hidden = false;
    element('result-heading').focus();
  } catch (error) {
    if (predictionRequest !== active || requestRevision !== inputRevision) return;
    if (active.timedOut) {
      showConnectionProblem('Prediction timed out after 15 seconds. Check the RoomWise window, then select Retry connection.', 'Connection timed out');
      return;
    }
    if (error.name === 'AbortError') return;
    if (error.connectionFailure || error.status >= 500) {
      showConnectionProblem(error.message + ' Double-click Start_Website.bat if needed, keep its window open, then select Retry connection.',
        error.status >= 500 ? 'Server error' : 'Server unavailable');
      return;
    }
    element('form-error').textContent = error.message;
    for (const [name, message] of Object.entries(error.fields || {})) {
      if (!fields.includes(name)) continue;
      element('error-' + name).textContent = message;
      element(name).setAttribute('aria-invalid', 'true');
    }
    const firstInvalid = fields.find(name => error.fields && error.fields[name]);
    if (firstInvalid) element(firstInvalid).focus();
  } finally {
    clearTimeout(active.timeout);
    // A canceled request must not unlock the button for a newer prediction.
    if (predictionRequest === active) {
      predictionRequest = null;
      updatePredictionButton();
    }
  }
});

// Keep the result summary tied to the submitted readings.
function displayInputSummary(inputs) {
  const units = { Temperature: '°C', Humidity: '%', Light: 'lux', CO2: 'ppm' };
  for (const name of fields) {
    element('summary-' + name).textContent = inputs[name] + ' ' + units[name];
  }
}

// A binary model has two outcomes. Scores are not real-world accuracy guarantees.
function displayProbabilities(probabilities) {
  for (const outcome of ['occupied', 'unoccupied']) {
    const score = probabilities[outcome];
    const percent = (score * 100).toFixed(2) + '%';
    element('probability-' + outcome).value = score;
    element('probability-' + outcome).textContent = percent;
    element('score-' + outcome).textContent = percent;
  }
}

// Display values saved by the notebook, rather than hard-coded accuracy claims.
async function loadModelInformation() {
  if (modelRequest) return;
  clearResult();
  model = null;
  updatePredictionButton();
  element('load').disabled = true;
  element('connection-actions').hidden = true;
  element('model-status').textContent = 'Connecting to model';
  element('connection-status').textContent = 'Connecting to the trained model…';
  if (location.protocol === 'file:') {
    element('model-status').textContent = 'Start Flask to predict';
    element('connection-status').textContent = 'Double-click Start_Website.bat and keep its window open. Use http://127.0.0.1:5080/ to predict; opening index.html directly cannot run the model.';
    element('connection-actions').hidden = false;
    element('retry-connection').hidden = true;
    return;
  }
  element('retry-connection').hidden = false;
  element('retry-connection').disabled = true;
  const controller = new AbortController();
  modelRequest = controller;
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const [metadata, samples] = await Promise.all([
      requestJSON('/api/model', { signal: controller.signal, cache: 'no-store' }),
      requestJSON('/api/samples', { signal: controller.signal, cache: 'no-store' })
    ]);
    const loadedModel = { metadata, samples };
    // A retry must replace old examples and metrics instead of duplicating them.
    element('sample').length = 1;
    element('sample').value = '';
    selectedSample = null;
    element('cv').replaceChildren();
    element('sample-note').textContent = 'Or enter your own readings below. All four fields are required.';
    for (const [index, sample] of loadedModel.samples.entries()) {
      const option = document.createElement('option');
      option.value = index;
      option.textContent = sample.name;
      element('sample').appendChild(option);
    }
    const metrics = loadedModel.metadata;
    element('training').textContent = (metrics.training_accuracy * 100).toFixed(2) + '%';
    element('validation').textContent = (metrics.validation_accuracy * 100).toFixed(2) + '%';
    element('test').textContent = (metrics.test_accuracy * 100).toFixed(2) + '%';
    element('gap').textContent = metrics.gap_points.toFixed(2) + ' pts';
    for (const fold of metrics.cv) {
      const row = document.createElement('tr');
      const values = [fold.Fold, fold['Training (%)'].toFixed(2) + '%',
        fold['Validation (%)'].toFixed(2) + '%', fold['Gap (points)'].toFixed(2) + ' pts',
        fold.Valid ? 'Yes' : 'No'];
      for (const value of values) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.appendChild(cell);
      }
      element('cv').appendChild(row);
    }
    element('form-error').textContent = '';
    element('connection-status').textContent = '';
    element('model-status').textContent = 'Flask model ready · Local';
    model = loadedModel;
    updatePredictionButton();
    element('load').disabled = false;
  } catch (error) {
    showConnectionProblem('Cannot connect to the trained model. Double-click Start_Website.bat, keep its window open, and open http://127.0.0.1:5080/. Then retry the connection.');
  } finally {
    clearTimeout(timeout);
    controller.abort();
    modelRequest = null;
    element('retry-connection').disabled = false;
  }
}
element('retry-connection').addEventListener('click', loadModelInformation);
loadModelInformation();
