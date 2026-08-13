import { describe, expect, it } from 'vitest'
import { GLOBAL_ROUTES, ROUTES, isKnownRoute, todayRoute } from '../routes'

/**
 * App.tsx redirects any pathname `isKnownRoute` rejects back to `/`. So a
 * route that exists but isn't listed is not a broken page — it's an
 * invisible one: the nav item works, and you land on the home screen with
 * nothing to explain why. That happened to /today, hence these tests.
 */
describe('every declared route is reachable', () => {
    const parameterised = (path: string) => path.includes(':')

    const exactRoutes: Array<[string, string]> = Object.entries(ROUTES)
        .filter(([, path]) => !parameterised(path))

    it.each(exactRoutes)('%s is a known route', (_name: string, path: string) => {
        expect(isKnownRoute(path)).toBe(true)
    })

    it('still accepts /today, which now redirects to home', () => {
        // "Hôm nay" renders inside the home screen rather than on a page of
        // its own. The path is kept as a known route so an old bookmark
        // redirects deliberately instead of falling through the
        // unknown-route handler.
        expect(todayRoute()).toBe('/today')
        expect(isKnownRoute('/today')).toBe(true)
    })

    it('still accepts the routes that have no ROUTES constant', () => {
        // They render, so they must be reachable, constant or not.
        expect(isKnownRoute('/settings')).toBe(true)
        expect(isKnownRoute('/notifications')).toBe(true)
    })

    it('accepts workspace-scoped paths', () => {
        expect(isKnownRoute('/w/abc123')).toBe(true)
        expect(isKnownRoute('/w/abc123/notes')).toBe(true)
    })

    it('still rejects genuinely unknown paths', () => {
        // The redirect exists for a reason — this guard must not become a
        // blanket "everything is fine".
        expect(isKnownRoute('/nope')).toBe(false)
        expect(isKnownRoute('/todayy')).toBe(false)
        expect(isKnownRoute('/today/extra')).toBe(false)
    })

    it('keeps GLOBAL_ROUTES free of parameterised paths', () => {
        // It is matched by exact equality, so ':id' in there would silently
        // never match.
        for (const path of GLOBAL_ROUTES) {
            expect(path).not.toContain(':')
        }
    })
})
