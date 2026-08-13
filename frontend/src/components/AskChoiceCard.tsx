import { useMemo, useState } from 'react'
import { Check } from 'lucide-react'
import { clsx } from 'clsx'
import type { AskChoiceQuestion } from '../services/api'

const CUSTOM_KEY = '__custom__'

interface AskChoiceStep {
    id: string
    questions?: AskChoiceQuestion[]
    answers?: Record<string, string>
}

interface Props {
    step: AskChoiceStep
    disabled?: boolean
    onSubmit: (answers: Record<string, string>, summaryText: string) => void
}

export function AskChoiceCard({ step, disabled, onSubmit }: Props) {
    const questions = step.questions ?? []
    const [activeTab, setActiveTab] = useState(0)
    const [selected, setSelected] = useState<Record<string, string[]>>({})
    const [customText, setCustomText] = useState<Record<string, string>>({})

    const answered = step.answers

    const isQuestionAnswered = (q: AskChoiceQuestion) => {
        const picks = selected[q.id] ?? []
        const hasCustom = picks.includes(CUSTOM_KEY) && (customText[q.id] ?? '').trim().length > 0
        const hasOption = picks.some(p => p !== CUSTOM_KEY)
        return hasCustom || hasOption
    }

    const allAnswered = useMemo(
        () => questions.length > 0 && questions.every(isQuestionAnswered),
        [questions, selected, customText],
    )

    const toggleOption = (q: AskChoiceQuestion, key: string) => {
        setSelected(prev => {
            const current = prev[q.id] ?? []
            if (q.allow_multiple) {
                const next = current.includes(key) ? current.filter(k => k !== key) : [...current, key]
                return { ...prev, [q.id]: next }
            }
            return { ...prev, [q.id]: [key] }
        })
    }

    const answerLabel = (q: AskChoiceQuestion): string => {
        const picks = selected[q.id] ?? []
        const parts: string[] = []
        for (const p of picks) {
            if (p === CUSTOM_KEY) {
                const text = (customText[q.id] ?? '').trim()
                if (text) parts.push(text)
            } else {
                parts.push(p)
            }
        }
        return parts.join(', ')
    }

    const handleSubmit = () => {
        if (!allAnswered) return
        const answers: Record<string, string> = {}
        const lines: string[] = []
        questions.forEach((q, idx) => {
            const answer = answerLabel(q)
            answers[q.id] = answer
            lines.push(`${idx + 1}. ${q.question} → ${answer}`)
        })
        onSubmit(answers, lines.join('\n'))
    }

    if (questions.length === 0) return null

    if (answered) {
        return (
            <div className="ask-choice-card ask-choice-card--locked">
                {questions.map((q, idx) => (
                    <div key={q.id} className="ask-choice-locked-row">
                        <span className="ask-choice-locked-question">{idx + 1}. {q.question}</span>
                        <span className="ask-choice-locked-answer">
                            <Check size={12} />
                            {answered[q.id] ?? ''}
                        </span>
                    </div>
                ))}
            </div>
        )
    }

    const q = questions[activeTab]

    return (
        <div className="ask-choice-card">
            {questions.length > 1 && (
                <div className="ask-choice-tabs">
                    {questions.map((tq, idx) => (
                        <button
                            key={tq.id}
                            type="button"
                            className={clsx('ask-choice-tab', idx === activeTab && 'is-active', isQuestionAnswered(tq) && 'is-answered')}
                            onClick={() => setActiveTab(idx)}
                        >
                            Câu {idx + 1}
                        </button>
                    ))}
                </div>
            )}

            <div className="ask-choice-question">{q.question}</div>

            <div className="ask-choice-options">
                {q.options.map(opt => {
                    const isSelected = (selected[q.id] ?? []).includes(opt.label)
                    return (
                        <button
                            key={opt.label}
                            type="button"
                            className={clsx('ask-choice-option', isSelected && 'is-selected')}
                            onClick={() => toggleOption(q, opt.label)}
                            disabled={disabled}
                        >
                            <span className={clsx('ask-choice-option-mark', q.allow_multiple && 'is-checkbox')}>
                                {isSelected && <Check size={11} />}
                            </span>
                            <span className="ask-choice-option-body">
                                <span className="ask-choice-option-label">{opt.label}</span>
                                {opt.description && <span className="ask-choice-option-desc">{opt.description}</span>}
                            </span>
                        </button>
                    )
                })}

                <button
                    type="button"
                    className={clsx('ask-choice-option', 'ask-choice-option--custom', (selected[q.id] ?? []).includes(CUSTOM_KEY) && 'is-selected')}
                    onClick={() => toggleOption(q, CUSTOM_KEY)}
                    disabled={disabled}
                >
                    <span className={clsx('ask-choice-option-mark', q.allow_multiple && 'is-checkbox')}>
                        {(selected[q.id] ?? []).includes(CUSTOM_KEY) && <Check size={11} />}
                    </span>
                    <span className="ask-choice-option-body">
                        <input
                            type="text"
                            className="ask-choice-custom-input"
                            placeholder="Câu trả lời khác…"
                            value={customText[q.id] ?? ''}
                            disabled={disabled}
                            onClick={e => e.stopPropagation()}
                            onFocus={() => {
                                if (!(selected[q.id] ?? []).includes(CUSTOM_KEY)) toggleOption(q, CUSTOM_KEY)
                            }}
                            onChange={e => setCustomText(prev => ({ ...prev, [q.id]: e.target.value }))}
                        />
                    </span>
                </button>
            </div>

            <div className="ask-choice-footer">
                <button
                    type="button"
                    className="ask-choice-submit-btn"
                    disabled={disabled || !allAnswered}
                    onClick={handleSubmit}
                >
                    Gửi câu trả lời
                </button>
            </div>
        </div>
    )
}
