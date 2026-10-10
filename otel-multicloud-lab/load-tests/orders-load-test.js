import http from 'k6/http';
import { check, sleep } from 'k6';

const vus = Number(__ENV.VUS || 50);
const duration = __ENV.DURATION || '5m';
const baseUrl = (__ENV.BASE_URL || '').replace(/\/$/, '');

if (!baseUrl) {
  throw new Error('BASE_URL es obligatorio. Dentro de Docker usa http://service-a:8080');
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
    http_req_duration: ['p(99)<500'],
    http_req_failed: ['rate<0.01'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

const payload = JSON.stringify({
  customer_id: 'bench-customer',
  amount: 150000.5,
  currency: 'cop',
});

const params = {
  headers: { 'Content-Type': 'application/json' },
  tags: { endpoint: 'POST /api/v1/orders' },
};

export default function () {
  const response = http.post(`${baseUrl}/api/v1/orders`, payload, params);
  check(response, {
    'codigo HTTP exitoso': (res) => res.status === 201,
  });
  sleep(0.2);
}

function metricValue(data, metric, key) {
  const values = data.metrics && data.metrics[metric] && data.metrics[metric].values;
  if (!values || values[key] === undefined || values[key] === null) {
    return 'ausente';
  }
  return values[key];
}

export function handleSummary(data) {
  const resultFile = __ENV.RESULT_FILE;
  const output = {
    stdout: [
      `vus=${vus} duration=${duration} base_url=${baseUrl}`,
      `http_req_duration avg=${metricValue(data, 'http_req_duration', 'avg')} p95=${metricValue(data, 'http_req_duration', 'p(95)')} p99=${metricValue(data, 'http_req_duration', 'p(99)')}`,
      `http_req_failed=${metricValue(data, 'http_req_failed', 'rate')}`,
      `http_reqs_per_s=${metricValue(data, 'http_reqs', 'rate')} iterations=${metricValue(data, 'iterations', 'count')}`,
    ].join('\n') + '\n',
  };
  if (resultFile) {
    output[resultFile] = JSON.stringify(data, null, 2);
  }
  return output;
}
