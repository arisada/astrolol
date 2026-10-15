export interface McpToolInfo {
  name: string
  description: string
  read_only: boolean
}

export interface McpInfo {
  endpoint: string
  auth_required: boolean
  tools: McpToolInfo[]
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

export const getInfo = () => request<McpInfo>('/plugins/mcp/info')
export const skillUrl = '/plugins/mcp/skill'
