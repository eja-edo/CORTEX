import { describe, expect, it } from 'vitest'
import { ApiError, explain } from './client'

describe('explain', () => {
  it('turns a refusal code into a sentence a person can act on', () => {
    expect(explain(new ApiError(409, { code: 'STALE' }))).toMatch(/Khách vừa nhắn thêm/)
    expect(explain(new ApiError(409, { code: 'OUTBOUND_OFF' }))).toMatch(/hãy tự gửi/)
    expect(explain(new ApiError(409, { code: 'SLOT_FULL' }))).toBe('Buổi này đã hết chỗ.')
  })
  it('never shows a raw code or a stack: unknown things get the generic line', () => {
    expect(explain(new ApiError(409, { code: 'SOMETHING_NEW' }))).toBe('Không thực hiện được. Thử lại sau.')
    expect(explain(new Error('boom'))).toBe('Không thực hiện được. Thử lại sau.')
  })
  it('reads lint errors and pydantic errors as messages', () => {
    expect(explain(new ApiError(422, { errors: ['match intent is not in the domain pack'] }))).toContain('domain pack')
    expect(explain(new ApiError(422, [{ loc: ['body', 'slug'], msg: 'String should match pattern' }]))).toBe('slug: String should match pattern')
  })
  it('says plainly when the role is not allowed', () => {
    expect(explain(new ApiError(403, 'owner only'))).toBe('Bạn không có quyền làm việc này.')
  })
})
