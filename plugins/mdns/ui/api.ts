export interface MdnsSettings {
  advertised_host: string | null
  advertised_port: number | null
  scheme: 'http' | 'https'
  instance_name: string | null
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    throw new Error(`${options?.method ?? 'GET'} ${path} failed: ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const getSettings = () => request<MdnsSettings>('/plugins/mdns/settings')
export const putSettings = (s: MdnsSettings) =>
  request<MdnsSettings>('/plugins/mdns/settings', { method: 'PUT', body: JSON.stringify(s) })
