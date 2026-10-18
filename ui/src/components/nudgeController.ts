/**
 * Press-and-hold logic of the nudge cross, kept free of React so it can be tested.
 *
 * A quick press moves the mount for a fixed time (`TAP_MS`) and lets go by itself. A press held
 * past `HOLD_MS` moves it until released. Requests go out strictly one after the other (a stop
 * can never overtake the start before it), and a held nudge is a short lease renewed while the
 * button is down, so if the release is ever lost the server stops the mount on its own.
 */

/** Held longer than this and the press is a hold; shorter is a tap. */
export const HOLD_MS = 250
/** How long a tap moves the mount. */
export const TAP_MS = 500
/** A held nudge dies this long after the last renewal. */
export const LEASE_MS = 2000
export const RENEW_MS = 700

export interface NudgeIo {
  /** Move `direction` at `rate`; the server stops by itself after `durationMs`. */
  start(direction: string, rate: string, durationMs: number): Promise<unknown>
  stop(): Promise<unknown>
  onError(error: unknown): void
}

interface Press {
  direction: string
  rate: string
  holding: boolean
  holdTimer: ReturnType<typeof setTimeout> | null
  renewTimer: ReturnType<typeof setInterval> | null
}

export class NudgeController {
  private press: Press | null = null
  private queue: Promise<void> = Promise.resolve()
  private queued = 0

  constructor(private io: NudgeIo) {}

  /** A direction button went down. Ignored while another press is in progress. */
  pressDown(direction: string, rate: string): void {
    if (this.press) return
    const press: Press = { direction, rate, holding: false, holdTimer: null, renewTimer: null }
    press.holdTimer = setTimeout(() => this.beginHold(press), HOLD_MS)
    this.press = press
  }

  /** The button came up: a tap becomes a timed nudge, a hold stops. */
  release(): void {
    const press = this.press
    if (!press) return
    this.clear(press)
    if (press.holding) this.enqueue(() => this.io.stop())
    else this.enqueue(() => this.io.start(press.direction, press.rate, TAP_MS))
  }

  /** The pad went away (hidden, folded, closed, button disabled): stop what is moving, start nothing. */
  abort(): void {
    const press = this.press
    if (!press) return
    this.clear(press)
    if (press.holding) this.enqueue(() => this.io.stop())
  }

  private clear(press: Press): void {
    if (press.holdTimer) clearTimeout(press.holdTimer)
    if (press.renewTimer) clearInterval(press.renewTimer)
    this.press = null
  }

  private beginHold(press: Press): void {
    press.holdTimer = null
    press.holding = true
    const lease = () => this.io.start(press.direction, press.rate, LEASE_MS)
    this.enqueue(lease)
    // Renew only when the line is quiet: a slow request must not pile renewals up behind it.
    press.renewTimer = setInterval(() => { if (this.queued === 0) this.enqueue(lease) }, RENEW_MS)
  }

  private enqueue(job: () => Promise<unknown>): void {
    this.queued += 1
    this.queue = this.queue
      .then(async () => { await job() })
      .catch((e) => this.io.onError(e))
      .finally(() => { this.queued -= 1 })
  }
}
