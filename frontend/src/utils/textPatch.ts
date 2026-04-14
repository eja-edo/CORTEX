import diff from 'fast-diff'

export type NotePatchOp =
    | { op: 'insert'; pos: number; text: string }
    | { op: 'delete'; pos: number; length: number }
    | { op: 'replace'; pos: number; length: number; text: string }

export function buildTextPatch(oldText: string, newText: string): NotePatchOp[] {
    if (oldText === newText) return []

    const chunks = diff(oldText, newText)
    const patch: NotePatchOp[] = []
    let oldPos = 0

    for (let i = 0; i < chunks.length; i += 1) {
        const [op, text] = chunks[i]
        if (!text) continue

        if (op === diff.EQUAL) {
            oldPos += text.length
            continue
        }

        if (op === diff.DELETE) {
            const next = chunks[i + 1]
            if (next && next[0] === diff.INSERT && next[1]) {
                patch.push({ op: 'replace', pos: oldPos, length: text.length, text: next[1] })
                oldPos += text.length
                i += 1
                continue
            }

            patch.push({ op: 'delete', pos: oldPos, length: text.length })
            oldPos += text.length
            continue
        }

        if (op === diff.INSERT) {
            patch.push({ op: 'insert', pos: oldPos, text })
        }
    }

    return patch
}
