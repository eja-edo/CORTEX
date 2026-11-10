import type { MaterialIn } from '../api/types'

/** Google's own file dialog (the Picker), loaded from Google when first needed. It runs in the browser with a short-lived token that only
 *  reaches `drive.file`: a file the teacher picks there is granted to this app, and nothing else in their Drive is. */
interface PickerBuilder {
  setAppId(id: string): PickerBuilder; setOAuthToken(t: string): PickerBuilder; setDeveloperKey(k: string): PickerBuilder; setLocale(l: string): PickerBuilder
  setOrigin(o: string): PickerBuilder; setTitle(t: string): PickerBuilder; enableFeature(f: unknown): PickerBuilder; addView(v: unknown): PickerBuilder; setCallback(cb: (d: Record<string, unknown>) => void): PickerBuilder
  build(): { setVisible(v: boolean): void }
}
interface DocsView { setIncludeFolders(v: boolean): DocsView; setSelectFolderEnabled(v: boolean): DocsView; setOwnedByMe(v: boolean): DocsView; setStarred(v: boolean): DocsView }
interface GooglePicker {
  PickerBuilder: new () => PickerBuilder
  DocsView: new (id?: unknown) => DocsView
  DocsUploadView: new () => unknown
  ViewId: Record<string, unknown>; Feature: Record<string, unknown>; Response: Record<string, string>; Action: Record<string, string>; Document: Record<string, string>
}
type Win = { gapi?: { load(name: string, o: { callback: () => void; onerror: () => void }): void }; google?: { picker?: GooglePicker } }
const win = () => window as unknown as Win

let loading: Promise<void> | null = null
/** Loads Google's script and its picker part once. A failure (offline, blocked) is not remembered, so the next click tries again. */
export function loadPicker(): Promise<void> {
  if (win().google?.picker) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const fail = () => { loading = null; reject(new Error('PICKER_LOAD_FAILED')) }
    const ready = () => win().gapi!.load('picker', { callback: resolve, onerror: fail })
    if (win().gapi) return ready()
    const s = document.createElement('script')
    s.src = 'https://apis.google.com/js/api.js'
    s.async = true
    s.onload = ready
    s.onerror = fail
    document.head.appendChild(s)
  })
  return loading
}

export interface PickerConfig { token: string; apiKey: string; appId: string }

/** An attachment the way the compose form keeps it. The address is built from the id alone, which is all the server reads from it. */
export const materialOf = (id: string, name: string): MaterialIn => ({ url: `https://drive.google.com/file/d/${id}/view`, title: name, share: 'VIEW' })

/** While Google's dialog is open the page behind it must not scroll: the dialog is laid over the whole window and, with a page scrollbar showing, it
 *  overflows by the scrollbar's own width, which brings a second (horizontal) one. Hiding the page's scroll for that time removes both. */
function lockPageScroll(): () => void {
  const html = document.documentElement.style
  const body = document.body.style
  const before = [html.overflow, body.overflow]
  html.overflow = 'hidden'
  body.overflow = 'hidden'
  let done = false
  return () => { if (!done) { done = true; html.overflow = before[0]; body.overflow = before[1] } }
}

/** Opens the dialog and returns at once; `onPick` is called when the teacher presses "Chọn". Rejects if Google's script cannot be loaded.
 *  The tabs: their own files first, then what was picked here before, what others shared, and an upload from the computer.
 *  `browse` off (a teacher on an account every class shares): the upload alone, because every other tab shows the other classes' files. */
export async function openDrivePicker(cfg: PickerConfig, onPick: (files: MaterialIn[]) => void, browse = true): Promise<void> {
  await loadPicker()
  const g = win().google!.picker!
  const views = browse ? [new g.DocsView(g.ViewId.DOCS).setIncludeFolders(true).setSelectFolderEnabled(false),  // browse folders, but only files can be chosen
    g.ViewId.RECENTLY_PICKED, new g.DocsView(g.ViewId.DOCS).setOwnedByMe(false)] : []
  const unlock = lockPageScroll()
  try {
    const builder = new g.PickerBuilder()
      .setAppId(cfg.appId).setOAuthToken(cfg.token).setDeveloperKey(cfg.apiKey).setLocale('vi').setOrigin(`${window.location.protocol}//${window.location.host}`)
      .setTitle('Chọn tệp đính kèm')
      .enableFeature(g.Feature.MULTISELECT_ENABLED)
    for (const v of [...views, new g.DocsUploadView()]) builder.addView(v)
    builder.setCallback((data) => {
        const action = data[g.Response.ACTION]
        if (action !== g.Action.PICKED && action !== g.Action.CANCEL) return  // "loaded" and the like: the dialog is still open
        unlock()
        if (action !== g.Action.PICKED) return
        const picked = (data[g.Response.DOCUMENTS] as Record<string, string>[]) ?? []
        onPick(picked.filter((d) => d[g.Document.ID]).map((d) => materialOf(d[g.Document.ID], d[g.Document.NAME] ?? '')))
      })
      .build().setVisible(true)
  } catch (e) {
    unlock()
    throw e
  }
}
