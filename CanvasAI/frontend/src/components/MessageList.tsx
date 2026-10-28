import React, { useEffect, useRef } from 'react'
import type { ChatMessage } from '../types/chat'
import { MessageItem } from './MessageItem'

interface MessageListProps {
  messages: ChatMessage[]
  isStreaming: boolean
  onPresetSelect?: (prompt: string) => void
}

export const MessageList: React.FC<MessageListProps> = ({
  messages,
  isStreaming,
  onPresetSelect,
}) => {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Automatically scroll to bottom as streaming tokens arrive
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isStreaming])

  if (messages.length === 0) {
    const starterPrompts = [
      'Explain how Server-Sent Events work in end-to-end LLM streaming.',
      'Write a Python generator function that yields Fibonacci numbers.',
      'What are the key trade-offs between WebSockets and SSE?',
    ]

    return (
      <div className="flex flex-1 flex-col items-center justify-center p-8 text-center">
        <h2 className="text-2xl font-bold text-slate-900 mb-2">
          MyGPT
        </h2>
        <p className="text-sm text-slate-500 max-w-md mb-6 leading-relaxed">
          How can I help you today?
        </p>

        <div className="w-full max-w-lg space-y-2">
          <span className="text-xs uppercase tracking-wider text-slate-400 font-medium block text-left pl-1">
            Try a sample prompt:
          </span>
          {starterPrompts.map((prompt) => (
            <button
              key={prompt}
              type="button"
              onClick={() => onPresetSelect?.(prompt)}
              className="w-full text-left p-3 rounded-xl bg-white border border-slate-200 hover:border-slate-300 hover:bg-slate-50 text-slate-700 text-xs shadow-xs transition-colors"
            >
              &ldquo;{prompt}&rdquo;
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div
      data-testid="message-list"
      className="flex-1 overflow-y-auto px-4 py-6 space-y-4 max-w-4xl mx-auto w-full"
    >
      {messages.map((message, index) => {
        const isStreamingThis =
          isStreaming &&
          message.role === 'assistant' &&
          index === messages.length - 1

        return (
          <MessageItem
            key={message.id}
            message={message}
            isStreamingThisMessage={isStreamingThis}
          />
        )
      })}
      <div ref={bottomRef} />
    </div>
  )
}
