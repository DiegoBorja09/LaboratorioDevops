import { buildSummary, options, runOrder } from './orders-flow.js';

const scenario = __ENV.SCENARIO || 'latency';

export { options };

export default function () {
  runOrder();
}

export function handleSummary(data) {
  return buildSummary(data, scenario);
}
