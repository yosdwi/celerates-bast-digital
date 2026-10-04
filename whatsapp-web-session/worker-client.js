"use strict";

// Client for bot-worker (/internal/v1/reply). Kept out of bridge.js so it can be tested over real HTTP
// without a WhatsApp client.
//
// Why this is not one long fetch: Node's built-in fetch (undici) gives up on any response whose headers have not
// arrived after 300s (UND_ERR_HEADERS_TIMEOUT) no matter what AbortSignal.timeout says, so a BAST export that
// renders for 5-11 minutes always died with "bot-worker unreachable: fetch failed" -- even while the worker
// went on to finish the file. Instead the worker answers within seconds: either the result, or HTTP 202 plus a
// job id that we poll with short requests until it is done.

const DEFAULT_REQUEST_TIMEOUT_MS = 60_000;
const DEFAULT_POLL_INTERVAL_MS = 5_000;
const DEFAULT_MAX_POLL_FAILURES = 6;

const defaultSleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function callWorker({
  baseUrl,
  token,
  payload,
  totalTimeoutMs,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  pollIntervalMs = DEFAULT_POLL_INTERVAL_MS,
  maxPollFailures = DEFAULT_MAX_POLL_FAILURES,
  fetchImpl = fetch,
  sleep = defaultSleep,
  now = Date.now,
  log = () => {},
}) {
  const headers = { "content-type": "application/json", "x-bridge-token": token };
  let accepted;
  try {
    const res = await fetchImpl(`${baseUrl}/internal/v1/reply`, {
      method: "POST",
      headers,
      // `async` lets the worker hand a slow command back as a job. A worker that predates it ignores the flag
      // and answers synchronously, which is handled below as the ordinary 200 case.
      body: JSON.stringify({ ...payload, async: true }),
      signal: AbortSignal.timeout(requestTimeoutMs),
    });
    const json = await res.json();
    if (res.status !== 202) return { ok: Boolean(json.ok), text: String(json.text ?? "") };
    accepted = json;
  } catch (err) {
    log(`callWorker: request failed: ${err.stack || err}`);
    return { ok: false, text: `bot-worker unreachable: ${err.message}` };
  }

  const jobId = String(accepted.job_id || "");
  if (!/^[0-9a-f-]{36}$/.test(jobId)) return { ok: false, text: "bot-worker returned an invalid job id" };
  const deadline = now() + totalTimeoutMs;
  let failures = 0;
  while (now() < deadline) {
    await sleep(pollIntervalMs);
    try {
      const res = await fetchImpl(`${baseUrl}/internal/v1/jobs/${jobId}`, {
        headers,
        signal: AbortSignal.timeout(requestTimeoutMs),
      });
      if (res.status === 404) {
        // The worker holds jobs in memory only; a restart (deploy) loses them. A finished render is cached on
        // disk, so asking again is quick.
        return { ok: false, text: "bot-worker restarted before the job finished" };
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      failures = 0;
      if (json.state === "done") return { ok: Boolean(json.ok), text: String(json.text ?? "") };
    } catch (err) {
      failures += 1;
      log(`callWorker: poll ${jobId} failed (${failures}/${maxPollFailures}): ${err.message}`);
      if (failures >= maxPollFailures) return { ok: false, text: `bot-worker unreachable: ${err.message}` };
    }
  }
  return { ok: false, text: `bot-worker did not finish within ${Math.round(totalTimeoutMs / 1000)}s` };
}

module.exports = { callWorker };
