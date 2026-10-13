import { describe, expect, it } from 'vitest'
import { findPage, hasPage, imageUrl } from './content'

describe('findPage', () => {
  it('finds core and plugin pages in the interface language', () => {
    expect(findPage('mount', 'fr')?.repoPath).toBe('docs/fr/mount.md')
    expect(findPage('guider', 'fr')?.repoPath).toBe('astrolol/plugins/guider/docs/fr.md')
  })
  it('falls back to English, then to the single-language page', () => {
    expect(findPage('mount', 'de')?.repoPath).toBe('docs/en/mount.md')
    expect(findPage('raspberry-pi-deployment', 'fr')?.repoPath).toBe('docs/raspberry-pi-deployment.md')
    expect(findPage('nope', 'en')).toBeNull()
    expect(hasPage('getting-started')).toBe(true)
  })
  it('loads the page text', async () => {
    expect(await findPage('getting-started', 'fr')!.load()).toMatch(/^# Premiers pas/)
  })
  it('knows the screenshots', () => {
    expect(imageUrl('docs/images/mount.png')).toBeTruthy()
    expect(imageUrl('astrolol/plugins/platesolve/docs/platesolve.jpg')).toBeTruthy()
  })
})
