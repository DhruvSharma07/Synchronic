// One stable color per user (derived from the user id), reused for the caret,
// name tag, and avatar so a person looks the same everywhere.
const PALETTE = ['#e64980', '#12b886', '#4263eb', '#f76707', '#7048e8', '#1098ad', '#d6336c', '#37b24d', '#f59f00', '#1c7ed6']

function hash(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0
  return Math.abs(h)
}

export const colorForUser = (id: string) => PALETTE[hash(id) % PALETTE.length]

/** Per-user blink offset (seconds) so several carets don't flash in lockstep. */
export const blinkDelayForUser = (id: string) => (hash(id + 'blink') % 10) / 10
