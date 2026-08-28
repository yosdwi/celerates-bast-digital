"use strict";

/**
 * Run an async operation and show a wait notice only when the operation is
 * genuinely slow. Fast deterministic paths stay quiet, while slow CLI/LLM
 * work still gets a useful acknowledgement.
 *
 * If the timer has already fired, wait for the notice send to settle before
 * returning the operation result so the final reply cannot overtake the
 * acknowledgement on WhatsApp. Notice failures never fail the business
 * operation.
 */
async function withDelayedNotice(operation, notify, delayMs) {
  let settled = false;
  let noticePromise = null;
  const timer = setTimeout(() => {
    if (settled) return;
    noticePromise = Promise.resolve()
      .then(notify)
      .catch(() => undefined);
  }, Math.max(0, Number(delayMs) || 0));

  try {
    return await operation();
  } finally {
    settled = true;
    clearTimeout(timer);
    if (noticePromise) await noticePromise;
  }
}

module.exports = { withDelayedNotice };
