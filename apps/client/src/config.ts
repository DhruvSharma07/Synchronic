// Same-origin by default (Vite proxy in dev, Caddy in prod). Override with
// VITE_API_URL / VITE_SYNC_SERVER_URL only if the backend lives on another origin.
const env = import.meta.env

export const API_URL: string = ((env.VITE_API_URL as string | undefined) || '/api').replace(/\/$/, '')

function wsBase(): string {
  const configured = env.VITE_SYNC_SERVER_URL as string | undefined
  if (configured) return configured.replace(/\/$/, '')
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${window.location.host}`
}

// y-websocket appends "/<roomname>" to this, giving the server's /sync/{document_id}
export const SYNC_URL = `${wsBase()}/sync`
