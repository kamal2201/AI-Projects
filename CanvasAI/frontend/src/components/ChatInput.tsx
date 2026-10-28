import React, { useState, useRef, useEffect } from 'react'
import { Send, Square, Loader2 } from 'lucide-react'

interface ChatInputProps {
  onSendMessage: (text: string) => void
  onStopGenerating: () => void
  isStreaming: boolean
  disabled?: boolean
}

export const ChatInput: React.FC<ChatInputProps> = ({
  onSendMessage,
  onStopGenerating,
  isStreaming,
  disabled = false,
}) => {
  const [input, setInput] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea height
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${Math.min(
        textareaRef.current.scrollHeight,
        200
      )}px`
    }
  }, [input])

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault()
    if (!input.trim() || isStreaming || disabled) return
    const textToSend = input.trim()
    setInput('')
    onSendMessage(textToSend)

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="w-full max-w-4xl mx-auto px-4 pb-6 pt-2">
      {/* Streaming Status Bar */}
      {isStreaming && (
        <div
          data-testid="streaming-indicator"
          className="flex items-center justify-between mb-2 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs"
        >
          <div className="flex items-center gap-2">
            <Loader2 size={13} className="animate-spin text-emerald-600" />
            <span className="font-medium">Streaming response from Gemini...</span>
          </div>
          <button
            type="button"
            data-testid="stop-generating-button"
            onClick={onStopGenerating}
            className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-amber-50 hover:bg-amber-100 text-amber-700 border border-amber-200 transition-colors font-medium text-xs shadow-xs"
          >
            <Square size={12} className="fill-amber-600" />
            Stop generating
          </button>
        </div>
      )}

      {/* Input container */}
      <form onSubmit={handleSubmit} className="relative flex items-end">
        <div className="relative flex-1 rounded-2xl bg-white border border-slate-300 shadow-sm focus-within:border-slate-400 focus-within:ring-2 focus-within:ring-slate-100 transition-all overflow-hidden">
          <textarea
            ref={textareaRef}
            data-testid="chat-input-textarea"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={disabled}
            placeholder={
              isStreaming
                ? 'Gemini is responding...'
                : 'Ask a question or enter a prompt... (Shift+Enter for newline)'
            }
            rows={1}
            className="w-full resize-none bg-transparent py-3.5 pl-4 pr-24 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none max-h-48"
          />

          <div className="absolute right-2 bottom-2.5 flex items-center gap-2">
            {isStreaming ? (
              <button
                type="button"
                data-testid="input-stop-button"
                onClick={onStopGenerating}
                className="flex items-center gap-1 px-3 py-1.5 rounded-xl bg-amber-600 hover:bg-amber-500 text-white text-xs font-semibold shadow-md transition-colors"
                title="Stop generation"
              >
                <Square size={12} className="fill-white" />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="submit"
                data-testid="send-message-button"
                disabled={!input.trim() || disabled}
                className="flex h-8 w-8 items-center justify-center rounded-xl bg-slate-900 hover:bg-slate-800 disabled:opacity-40 disabled:hover:bg-slate-900 text-white transition-all shadow-xs"
                title="Send message"
              >
                <Send size={15} />
              </button>
            )}
          </div>
        </div>
      </form>
      <div className="mt-2 text-center text-[11px] text-slate-400">
        Responses stream token-by-token via FastAPI SSE & LangChain
      </div>
    </div>
  )
}
