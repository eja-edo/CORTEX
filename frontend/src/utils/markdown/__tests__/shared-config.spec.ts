import { describe, it, expect } from 'vitest'
import {
  MARKDOWN_IT_OPTIONS,
  SANITIZE_ALLOWED_TAGS,
  SANITIZE_ALLOWED_ATTR,
} from '../config'
import { BACKEND_MARKDOWN_IT_OPTIONS } from './_backend-config-mirror'

describe('shared markdown config', () => {
  it('has the canonical option set', () => {
    expect(MARKDOWN_IT_OPTIONS).toEqual({
      html: false,
      linkify: true,
      typographer: true,
      breaks: true,
    })
  })

  it('exposes a sanitize allow-list', () => {
    expect(SANITIZE_ALLOWED_TAGS).toContain('h1')
    expect(SANITIZE_ALLOWED_TAGS).toContain('h6')
    expect(SANITIZE_ALLOWED_TAGS).toContain('img')
    expect(SANITIZE_ALLOWED_ATTR).toContain('href')
    expect(SANITIZE_ALLOWED_ATTR).toContain('title')
  })

  it('stays in sync with backend mirror (drift detector)', () => {
    expect(BACKEND_MARKDOWN_IT_OPTIONS).toEqual(MARKDOWN_IT_OPTIONS)
  })
})
