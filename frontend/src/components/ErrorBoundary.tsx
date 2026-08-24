import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

/**
 * Nothing in the app previously caught a render error — a bad markdown
 * block, a malformed mermaid diagram, a broken workflow graph node — so one
 * throwing component blanked the entire screen with no way back except a
 * full reload. This catches at whatever boundary it wraps and offers a
 * scoped "reload this part" instead of losing the whole session.
 *
 * Class component because getDerivedStateFromError / componentDidCatch have
 * no hook equivalent — this is the one place in the codebase that has to be
 * a class for a real reason, not a style choice.
 */

type Props = {
    children: ReactNode
    /** Shown in the fallback message; identifies which part of the app broke. */
    label?: string
}

type State = {
    error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
    state: State = { error: null }

    static getDerivedStateFromError(error: Error): State {
        return { error }
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error(`[ErrorBoundary${this.props.label ? `:${this.props.label}` : ''}]`, error, info.componentStack)
    }

    private reset = () => {
        this.setState({ error: null })
    }

    render() {
        if (this.state.error) {
            return (
                <div className="error-boundary-fallback" role="alert">
                    <AlertTriangle size={20} className="error-boundary-icon" aria-hidden="true" />
                    <p className="error-boundary-message">
                        {this.props.label ? `${this.props.label} gặp lỗi khi hiển thị.` : 'Phần này gặp lỗi khi hiển thị.'}
                    </p>
                    <button type="button" className="btn btn-ghost" onClick={this.reset}>
                        Thử lại
                    </button>
                </div>
            )
        }
        return this.props.children
    }
}
