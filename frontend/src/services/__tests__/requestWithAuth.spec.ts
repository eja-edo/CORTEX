import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * `requestWithAuth` — header mặc định.
 *
 * Thiếu `Content-Type` trên một request có body làm FastAPI trả **422
 * Unprocessable Entity**, và đó là mã lỗi trỏ sai hướng: nó đọc như "payload
 * của bạn sai", nên người sửa đi kiểm payload — vốn đúng. Bug này đã xảy ra
 * đúng như vậy với các endpoint dự án, và chỉ lộ ra khi bấm thử trên UI thật
 * chứ không phải trong test backend (test backend gọi qua ASGI với header tự
 * đặt).
 *
 * Nên mặc định nằm ở tầng dùng chung, và đây là test khoá nó.
 */

const fetchMock = vi.fn()

beforeEach(() => {
    vi.resetModules()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    window.localStorage.setItem(
        'cortex_tokens',
        JSON.stringify({ accessToken: 'acc', refreshToken: 'ref' }),
    )
})

function ok(body: unknown = {}) {
    return Promise.resolve({
        ok: true,
        status: 200,
        text: () => Promise.resolve(JSON.stringify(body)),
    })
}

async function load() {
    return await import('../api')
}

function headersOf(call: unknown[]): Headers {
    return (call[1] as RequestInit).headers as Headers
}

describe('requestWithAuth', () => {
    it('sets application/json when there is a body and nobody said otherwise', async () => {
        fetchMock.mockReturnValue(ok())
        const { requestWithAuth } = await load()

        await requestWithAuth('/projects', { method: 'POST', body: '{"name":"Alpha"}' })

        const headers = headersOf(fetchMock.mock.calls[0])
        expect(headers.get('Content-Type')).toBe('application/json')
        expect(headers.get('Authorization')).toBe('Bearer acc')
    })

    it('leaves a GET alone — no body, no content type', async () => {
        fetchMock.mockReturnValue(ok([]))
        const { requestWithAuth } = await load()

        await requestWithAuth('/projects')

        expect(headersOf(fetchMock.mock.calls[0]).has('Content-Type')).toBe(false)
    })

    it('never overrides a caller that set its own content type', async () => {
        // Upload dùng multipart và tự đặt boundary — đè lên đó sẽ làm hỏng
        // đúng những request phức tạp nhất.
        fetchMock.mockReturnValue(ok())
        const { requestWithAuth } = await load()

        await requestWithAuth('/upload', {
            method: 'POST',
            body: 'x',
            headers: { 'Content-Type': 'text/plain' },
        })

        expect(headersOf(fetchMock.mock.calls[0]).get('Content-Type')).toBe('text/plain')
    })

    it('keeps the content type on the retry after a token refresh', async () => {
        // Lần thử lại dựng header từ đầu. Bỏ sót ở nhánh này thì lỗi chỉ
        // xuất hiện khi access token vừa hết hạn — tức là hiếm, và gần như
        // không lặp lại được khi đi tìm.
        fetchMock
            .mockReturnValueOnce(Promise.resolve({ ok: false, status: 401, text: () => Promise.resolve('') }))
            .mockReturnValueOnce(
                Promise.resolve({
                    ok: true,
                    status: 200,
                    text: () =>
                        Promise.resolve(
                            JSON.stringify({ access_token: 'acc2', refresh_token: 'ref2', token_type: 'bearer' }),
                        ),
                }),
            )
            .mockReturnValueOnce(ok())
        const { requestWithAuth } = await load()

        await requestWithAuth('/projects', { method: 'POST', body: '{}' })

        const retry = headersOf(fetchMock.mock.calls[2])
        expect(retry.get('Content-Type')).toBe('application/json')
        expect(retry.get('Authorization')).toBe('Bearer acc2')
    })
})
