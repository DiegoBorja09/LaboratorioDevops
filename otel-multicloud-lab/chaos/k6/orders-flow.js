import http from 'k6/http';
import { check, sleep } from 'k6';

const vus = Number(__ENV.VUS || 5);
const duration = __ENV.DURATION || '120s';
const baseUrl = (__ENV.BASE_URL || 'http://service-a:8080').replace(/\/$/, '');

if (!baseUrl) {
  throw new Error('BASE_URL no puede estar vacío');
}

if (!Number.isFinite(vus) || vus < 1) {
  throw new Error('VUS debe ser un entero mayor que cero');
}

export const options = {
  scenarios: {
    orders: {
      executor: 'constant-vus',
      vus,
      duration,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    checks: ['rate>=0.99'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

const payload = JSON.stringify({
  customer_id: 'bench-customer',
  amount: 150000.5,
  currency: 'cop',
});

function requestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (symbol) {
    const random = Math.floor(Math.random() * 16);
    const value = symbol === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

export function runOrder() {
  const response = http.post(baseUrl + '/api/v1/orders', payload, {
    headers: {
      'Content-Type': 'application/json',
      'X-Request-ID': requestId(),
    },
    tags: { endpoint: 'POST /api/v1/orders' },
  });
  check(response, {
    'codigo HTTP exitoso': function (res) {
      return res.status === 201;
    },
  });
  sleep(0.2);
}

function metricValue(data, metric, key) {
  const values = data.metrics && data.metrics[metric] && data.metrics[metric].values;
  if (!values || values[key] === undefined || values[key] === null) {
    return null;
  }
  return values[key];
}

export function buildSummary(data, scenario) {
  const summary = {
    scenario: scenario,
    base_url: baseUrl,
    vus: vus,
    duration: duration,
    http_req_duration_avg: metricValue(data, 'http_req_duration', 'avg'),
    http_req_duration_p95: metricValue(data, 'http_req_duration', 'p(95)'),
    http_req_failed_rate: metricValue(data, 'http_req_failed', 'rate'),
    checks_rate: metricValue(data, 'checks', 'rate'),
    iterations: metricValue(data, 'iterations', 'count'),
    requests_per_second: metricValue(data, 'http_reqs', 'rate'),
  };
  const lines = [
    'scenario=' + scenario + ' vus=' + vus + ' duration=' + duration + ' base_url=' + baseUrl,
    'http_req_duration avg=' + summary.http_req_duration_avg + ' p95=' + summary.http_req_duration_p95,
    'http_req_failed=' + summary.http_req_failed_rate,
    'checks=' + summary.checks_rate,
    'iterations=' + summary.iterations + ' requests_per_second=' + summary.requests_per_second,
  ];
  const output = {
    stdout: lines.join('\n') + '\n',
  };
  if (__ENV.RESULT_FILE) {
    output[__ENV.RESULT_FILE] = JSON.stringify(summary, null, 2);
  }
  return output;
}
