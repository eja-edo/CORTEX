import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { materialOf, openDrivePicker } from './drivePicker'

/** A stand-in for Google's script: records what the dialog is built from and lets the test press "Chọn" or "Hủy". */
function fakeGoogle() {
  const built: { views: unknown[]; title?: string; callback?: (d: Record<string, unknown>) => void; visible: boolean } = { views: [], visible: false }
  class View { flags: string[] = []
    setIncludeFolders() { this.flags.push('folders'); return this } setSelectFolderEnabled() { this.flags.push('no-folder-pick'); return this }
    setOwnedByMe() { this.flags.push('shared'); return this } setStarred() { this.flags.push('starred'); return this } }
  class Builder {
    setAppId() { return this } setOAuthToken() { return this } setDeveloperKey() { return this } setLocale() { return this } setOrigin() { return this } enableFeature() { return this }
    setTitle(t: string) { built.title = t; return this } addView(v: unknown) { built.views.push(v); return this }
    setCallback(cb: (d: Record<string, unknown>) => void) { built.callback = cb; return this } build() { return { setVisible: (v: boolean) => { built.visible = v } } }
  }
  const picker = { PickerBuilder: Builder, DocsView: View, DocsUploadView: class { kind = 'upload' }, ViewId: { DOCS: 'docs', RECENTLY_PICKED: 'recent' }, Feature: { MULTISELECT_ENABLED: 'multi' },
    Response: { ACTION: 'action', DOCUMENTS: 'docs' }, Action: { PICKED: 'picked', CANCEL: 'cancel', LOADED: 'loaded' }, Document: { ID: 'id', NAME: 'name' } }
  ;(window as unknown as { google: unknown }).google = { picker }
  return built
}

const CFG = { token: 't', apiKey: 'k', appId: '1' }
beforeEach(() => { document.documentElement.style.overflow = ''; document.body.style.overflow = '' })
afterEach(() => { delete (window as unknown as { google?: unknown }).google })

describe('Google Drive picker', () => {
  it('builds the dialog from four tabs with no duplicate "Google Drive" and a title in Vietnamese', async () => {
    const built = fakeGoogle()
    await openDrivePicker(CFG, vi.fn())
    expect(built.visible).toBe(true)
    expect(built.title).toBe('Chọn tệp đính kèm')
    expect(built.views).toHaveLength(4)  // their files, recent, shared with them, upload: the starred tab that was also called "Google Drive" is gone
    expect(built.views[1]).toBe('recent')
    expect((built.views[0] as { flags: string[] }).flags).toEqual(['folders', 'no-folder-pick'])  // a file can be chosen, not a folder
    expect((built.views[2] as { flags: string[] }).flags).toEqual(['shared'])
  })

  it('offers a teacher on a shared account the upload alone, no tab that shows the Drive', async () => {
    const built = fakeGoogle()
    await openDrivePicker(CFG, vi.fn(), false)
    expect(built.visible).toBe(true)
    expect(built.views).toHaveLength(1)
    expect(built.views).not.toContain('recent')
    expect((built.views[0] as { flags?: string[] }).flags).toBeUndefined()  // not a Docs view: nothing of the account is listed
  })

  it('holds the page still while the dialog is open and lets go when a file is chosen', async () => {
    const built = fakeGoogle()
    const onPick = vi.fn()
    await openDrivePicker(CFG, onPick)
    expect(document.body.style.overflow).toBe('hidden')
    expect(document.documentElement.style.overflow).toBe('hidden')
    built.callback!({ action: 'loaded' })
    expect(document.body.style.overflow).toBe('hidden')  // still open
    built.callback!({ action: 'picked', docs: [{ id: 'a1', name: 'Biểu đồ mẫu.pdf' }, { name: 'no id' }] })
    expect(document.body.style.overflow).toBe('')
    expect(document.documentElement.style.overflow).toBe('')
    expect(onPick).toHaveBeenCalledWith([materialOf('a1', 'Biểu đồ mẫu.pdf')])  // a document without an id is dropped
  })

  it('lets go too when the dialog is closed without choosing, and chooses nothing', async () => {
    const built = fakeGoogle()
    const onPick = vi.fn()
    document.body.style.overflow = 'scroll'
    await openDrivePicker(CFG, onPick)
    built.callback!({ action: 'cancel' })
    expect(document.body.style.overflow).toBe('scroll')  // what was there before comes back
    expect(onPick).not.toHaveBeenCalled()
  })
})
