/**
 * Keeps the mount moving as the joystick says, with requests sent strictly one after the other.
 *
 * The joystick reports what it wants (`update`) as often as the thumb moves; only the latest
 * wish is acted on. Every motion is a short lease renewed while the thumb stays down, so a lost
 * release ends with the mount stopping on its own. A flick shorter than `TAP_MS` still moves the
 * mount for that long, like a tap on the cross.
 */
import { LEASE_MS, RENEW_MS, TAP_MS, type NudgeIo } from './nudgeController'
import type { Direction } from './joystick'

export interface Move { direction: Direction; rate: string }

export class JoystickController {
  private wanted = new Map<Direction, string>()
  private applied = new Map<Direction, string>()
  private pumping = false
  private movingSince = 0
  private tapMs = 0
  private renewTimer: ReturnType<typeof setInterval> | null = null

  constructor(private io: NudgeIo) {}

  /** What the thumb asks for now: the directions to move in and the rate for them. */
  update(moves: Move[]): void {
    this.wanted = new Map(moves.map((m) => [m.direction, m.rate]))
    this.tapMs = 0
    void this.pump()
  }

  /** The thumb lifted. A very short push still gets its fixed-time nudge. */
  end(): void {
    const elapsed = Date.now() - this.movingSince
    this.tapMs = this.applied.size > 0 && elapsed < TAP_MS ? Math.max(50, TAP_MS - elapsed) : 0
    this.wanted = new Map()
    void this.pump()
  }

  /** The pad went away: stop at once. */
  abort(): void {
    this.tapMs = 0
    this.wanted = new Map()
    void this.pump()
  }

  private async pump(): Promise<void> {
    if (this.pumping) return
    this.pumping = true
    try {
      while (!this.settled()) {
        try { await this.step() } catch (e) {
          this.io.onError(e)
          // Give up on what failed: whatever is applied now is what we want.
          this.wanted = new Map(this.applied)
        }
      }
    } finally {
      this.pumping = false
      this.syncRenewal()
    }
  }

  private settled(): boolean {
    if (this.wanted.size === 0) return this.applied.size === 0
    if (this.wanted.size !== this.applied.size) return false
    for (const [d, r] of this.wanted) if (this.applied.get(d) !== r) return false
    return true
  }

  private async step(): Promise<void> {
    if (this.wanted.size === 0) {
      const tap = this.tapMs
      const running = [...this.applied]
      this.tapMs = 0
      if (tap > 0) {
        // Let the moves run out by themselves.
        for (const [d, r] of running) await this.io.start(d, r, tap)
        this.applied.clear()
      } else {
        this.applied.clear()
        await this.io.stop()
      }
      return
    }
    // A direction no longer wanted can only be dropped by stopping, then the rest starts again.
    if ([...this.applied.keys()].some((d) => !this.wanted.has(d))) {
      this.applied.clear()
      await this.io.stop()
      return
    }
    const wasIdle = this.applied.size === 0
    for (const [d, r] of this.wanted) {
      if (this.applied.get(d) === r) continue
      await this.io.start(d, r, LEASE_MS)
      this.applied.set(d, r)
      if (wasIdle && this.applied.size === 1) this.movingSince = Date.now()
    }
    this.syncRenewal()
  }

  private syncRenewal(): void {
    const needed = this.applied.size > 0 && this.wanted.size > 0
    if (needed && !this.renewTimer) {
      this.renewTimer = setInterval(() => { void this.renew() }, RENEW_MS)
    } else if (!needed && this.renewTimer) {
      clearInterval(this.renewTimer)
      this.renewTimer = null
    }
  }

  private async renew(): Promise<void> {
    if (this.pumping || this.applied.size === 0) return
    this.pumping = true
    try {
      for (const [d, r] of this.applied) await this.io.start(d, r, LEASE_MS)
    } catch (e) { this.io.onError(e) } finally {
      this.pumping = false
      void this.pump()   // pick up what changed while renewing
    }
  }
}
