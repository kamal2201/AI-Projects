import React from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Bot, User, AlertCircle, StopCircle, Copy, Check, Sparkles } from 'lucide-react'
import type { ChatMessage } from '../types/chat'
import { renderComponent } from './renderers/ComponentRegistry'
import { MessageComponentProvider } from '../context/MessageComponentContext'

interface MessageItemProps {
  message: ChatMessage
  isStreamingThisMessage?: boolean
}

/**
 * Filter out leaked internal JSON strings or conversation context tags
 * from the user-facing prose text body.
 */
function sanitizeProseContent(content: string, hasComponents: boolean): string {
  if (!content) return ''
  let cleaned = content

  // Remove internal follow-up context tags if leaked
  cleaned = cleaned.replace(/\[Active Components:[^\]]*\]/gi, '').trim()

  // Remove leaked raw JSON component specifications
  if (hasComponents) {
    cleaned = cleaned
      .replace(/```(?:json)?\s*\{[\s\S]*?"type"\s*:\s*"[^"]+"[\s\S]*?\}\s*```/gi, '')
      .replace(/^\s*\{[\s\S]*?"(?:type|component_type|headers|rows|labels|values)"[\s\S]*?\}\s*$/gm, '')
      .trim()
  }

  return cleaned
}

export const MessageItem: React.FC<MessageItemProps> = ({
  message,
  isStreamingThisMessage = false,
}) => {
  const [copied, setCopied] = React.useState(false)
  const isUser = message.role === 'user'
  const hasComponents = Boolean(message.components && message.components.length > 0)
  const displayContent = sanitizeProseContent(message.content, hasComponents)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(displayContent || message.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // clipboard write might fail in some environments
    }
  }

  return (
    <div
      data-testid={`message-${message.role}`}
      className={`message-row flex w-full gap-4 p-4 rounded-2xl transition-colors ${
        isUser
          ? 'bg-slate-100/80 border border-slate-200'
          : 'bg-white border border-slate-200 shadow-xs'
      }`}
    >
      {/* Avatar Icon */}
      <div
        className={`flex h-9 w-9 shrink-0 select-none items-center justify-center rounded-xl shadow-xs ${
          isUser
            ? 'bg-slate-700 text-white'
            : 'bg-emerald-600 text-white'
        }`}
      >
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>

      {/* Message Content */}
      <div className="flex-1 overflow-hidden space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-slate-500">
              {isUser ? 'You' : 'MyGPT'}
            </span>
            {isStreamingThisMessage && message.statusMessage && (
              <span className="flex items-center gap-1 text-[11px] text-emerald-700 font-medium px-2 py-0.5 rounded-full bg-emerald-50 border border-emerald-200">
                <Sparkles size={11} className="animate-spin text-emerald-600" />
                {message.statusMessage}
              </span>
            )}
          </div>

          <div className="flex items-center gap-2">
            {message.status === 'error' && (
              <span className="flex items-center gap-1 text-xs text-red-700 font-medium bg-red-50 px-2 py-0.5 rounded border border-red-200">
                <AlertCircle size={12} />
                Failed
              </span>
            )}
            {message.status === 'cancelled' && (
              <span className="flex items-center gap-1 text-xs text-amber-700 font-medium bg-amber-50 px-2 py-0.5 rounded border border-amber-200">
                <StopCircle size={12} />
                Stopped
              </span>
            )}
            {!isUser && displayContent && (
              <button
                type="button"
                onClick={handleCopy}
                className="text-slate-400 hover:text-slate-600 transition-colors p-1 rounded"
                title="Copy response"
                aria-label="Copy response"
              >
                {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
              </button>
            )}
          </div>
        </div>

        {/* Markdown & KaTeX Math Body */}
        <div className="markdown-body prose prose-slate max-w-none text-slate-800 text-sm leading-relaxed">
          {displayContent ? (
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={[rehypeKatex]}
            >
              {displayContent}
            </ReactMarkdown>
          ) : isStreamingThisMessage && !hasComponents ? (
            <span className="text-slate-400 italic flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-slate-400 animate-ping" />
              Generating response...
            </span>
          ) : message.status === 'error' ? (
            <span className="text-red-600 text-sm">No response generated due to an error.</span>
          ) : null}

          {/* Streaming active cursor */}
          {isStreamingThisMessage && message.content && (
            <span
              data-testid="streaming-cursor"
              className="inline-block w-2 h-4 ml-1 bg-slate-500 animate-pulse align-middle"
              aria-label="Generating"
            />
          )}
        </div>

        {/* Rendered Rich UI Components */}
        {hasComponents && (
          <MessageComponentProvider>
            <div
              data-testid="message-components-container"
              className="pt-2 space-y-4 border-t border-slate-200"
            >
              {message.components!.map((comp, idx) => (
                <div key={`${comp.type}-${idx}`} className="w-full">
                  {renderComponent(comp, `${message.id}-comp-${idx}`)}
                </div>
              ))}
            </div>
          </MessageComponentProvider>
        )}

        {/* Safe error message banner */}
        {message.error && (
          <div
            data-testid="message-error-banner"
            className="mt-3 p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-start gap-2"
          >
            <AlertCircle size={16} className="shrink-0 mt-0.5 text-red-600" />
            <span>{message.error}</span>
          </div>
        )}
      </div>
    </div>
  )
}
