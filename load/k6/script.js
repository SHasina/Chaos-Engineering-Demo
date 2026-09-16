import http from "k6/http";
import { sleep } from "k6";

// Background traffic generator: gives the chaos experiments a realistic
// SLI to violate or hold, instead of measuring an idle system.
export const options = {
  vus: 5,
  duration: __ENV.K6_DURATION || "90s",
};

const BASE_URL = __ENV.BASE_URL || "http://localhost:8080";

export default function () {
  http.get(`${BASE_URL}/orders`);
  sleep(0.5);
}
