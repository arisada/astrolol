import { describe, expect, it } from 'vitest'
import { docRefFromPath, joinPath, repoPathFromGlobKey, resolveHref, topicForRoute } from './paths'

describe('repoPathFromGlobKey', () => {
  it('strips the relative prefix of core and plugin files', () => {
    expect(repoPathFromGlobKey('../../../docs/en/mount.md')).toBe('docs/en/mount.md')
    expect(repoPathFromGlobKey('../../astrolol/plugins/guider/docs/en.md')).toBe('astrolol/plugins/guider/docs/en.md')
    expect(repoPathFromGlobKey('/src/other.md')).toBeNull()
  })
})

describe('docRefFromPath', () => {
  it('names core pages by file and plugin pages by plugin id', () => {
    expect(docRefFromPath('docs/fr/getting-started.md')).toEqual({ topic: 'getting-started', lng: 'fr' })
    expect(docRefFromPath('docs/raspberry-pi-deployment.md')).toEqual({ topic: 'raspberry-pi-deployment', lng: null })
    expect(docRefFromPath('astrolol/plugins/polar_align/docs/en.md')).toEqual({ topic: 'polar_align', lng: 'en' })
    expect(docRefFromPath('docs/images/mount.png')).toBeNull()
  })
})

describe('joinPath', () => {
  it('resolves dot segments', () => {
    expect(joinPath('docs/en', '../../astrolol/plugins/x/docs/en.md')).toBe('astrolol/plugins/x/docs/en.md')
    expect(joinPath('docs/en', './mount.md')).toBe('docs/en/mount.md')
  })
})

describe('resolveHref', () => {
  it('follows links from a core page to a plugin page, keeping the anchor', () => {
    expect(resolveHref('docs/en/README.md', '../../astrolol/plugins/guider/docs/en.md#set-up-tab'))
      .toEqual({ kind: 'doc', topic: 'guider', anchor: 'set-up-tab' })
  })
  it('follows links from a plugin page back to core and to another plugin', () => {
    expect(resolveHref('astrolol/plugins/target/docs/en.md', '../../../../docs/en/profiles.md'))
      .toEqual({ kind: 'doc', topic: 'profiles', anchor: '' })
    expect(resolveHref('astrolol/plugins/lx200/docs/en.md', '../../stellarium/docs/en.md'))
      .toEqual({ kind: 'doc', topic: 'stellarium', anchor: '' })
  })
  it('decodes accented anchors', () => {
    expect(resolveHref('docs/fr/mount.md', 'interface.md#propri%C3%A9t%C3%A9s-des-appareils'))
      .toEqual({ kind: 'doc', topic: 'interface', anchor: 'propriétés-des-appareils' })
    expect(resolveHref('docs/fr/mount.md', '#parcage%20x')).toEqual({ kind: 'anchor', anchor: 'parcage x' })
  })
  it('tells images, anchors and external links apart', () => {
    expect(resolveHref('docs/en/mount.md', '../images/mount.png')).toEqual({ kind: 'file', repoPath: 'docs/images/mount.png' })
    expect(resolveHref('docs/en/mount.md', '#park')).toEqual({ kind: 'anchor', anchor: 'park' })
    expect(resolveHref('docs/en/mount.md', 'https://stellarium.org/')).toEqual({ kind: 'external', url: 'https://stellarium.org/' })
  })
})

describe('topicForRoute', () => {
  it('maps core pages, camera pages and plugin pages', () => {
    expect(topicForRoute('/')).toBe('imaging')
    expect(topicForRoute('/imaging/camera_zwo')).toBe('imaging')
    expect(topicForRoute('/equipment')).toBe('equipment')
    expect(topicForRoute('/polar_align')).toBe('polar_align')
    expect(topicForRoute('/help/guider')).toBe('guider')
  })
})
