import type { Transition } from 'motion/react'

/** The app's two springs.
 *
 * Springs rather than fixed-duration curves because a spring animates from
 * wherever the value *is*, not from where the last animation was told to
 * start. Retarget one mid-flight — reopen a panel that is still closing, flip
 * back to the tab you just left — and it carries its current position and
 * velocity into the new motion instead of jumping to the start of a fresh
 * curve.
 *
 * `bounce`/`duration` here are motion's names for what Apple calls damping
 * and response: `bounce: 0` is critically damped, and `duration` is how long
 * the value takes to arrive, not a fixed runtime.
 */

/** Everything the user did not throw. Critically damped — no overshoot.
 *
 * Overshoot is the visual signature of momentum, so it belongs to gestures
 * that carried some. A panel that bounces because it was *clicked* open reads
 * as slack, not as physical. */
export const SETTLE: Transition = { type: 'spring', bounce: 0, duration: 0.4 }

/** The same spring, shortened, for small things that should be over before
 * they are noticed — a chip appearing, a toast sliding up. */
export const SETTLE_FAST: Transition = { type: 'spring', bounce: 0, duration: 0.28 }
