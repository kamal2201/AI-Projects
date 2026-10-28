import React, { useState, useRef, useCallback } from 'react'
import { Plus } from 'lucide-react'
import type { ChatMessage, MessageRole } from '../types/chat'
import { streamChatCompletion } from '../services/chatStream'
import { MessageList } from './MessageList'
import { ChatInput } from './ChatInput'

function generateId(): string {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) {
    return crypto.randomUUID()
  }
  return `msg-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`
}

export const ChatInterface: React.FC = () => {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [isStreaming, setIsStreaming] = useState<boolean>(false)
  const [globalError, setGlobalError] = useState<string | null>(null)
  const abortControllerRef = useRef<AbortController | null>(null)

  const stopGenerating = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort()
      abortControllerRef.current = null
    }

    setIsStreaming(false)

    setMessages((prev) => {
      if (prev.length === 0) return prev
      const lastIndex = prev.length - 1
      const lastMessage = prev[lastIndex]
      if (lastMessage.role === 'assistant' && lastMessage.status === 'streaming') {
        const updated = [...prev]
        updated[lastIndex] = {
          ...lastMessage,
          status: 'cancelled',
          statusMessage: undefined,
        }
        return updated
      }
      return prev
    })
  }, [])

  const sendMessage = useCallback(
    async (text: string) => {
      if (!text.trim() || isStreaming) return

      setGlobalError(null)

      const userMessage: ChatMessage = {
        id: generateId(),
        role: 'user',
        content: text.trim(),
        timestamp: Date.now(),
      }

      // Preserve previous conversation history plus new user prompt
      const updatedMessages = [...messages, userMessage]
      setMessages(updatedMessages)

      // Serialize history for the planner, embedding component context for seamless follow-ups
      const historyPayload = updatedMessages
        .filter((m) => m.content.trim().length > 0 || (m.components && m.components.length > 0))
        .map((m) => {
          let content = m.content
          if (m.role === 'assistant' && m.components && m.components.length > 0) {
            const compSummary = m.components
              .map((c) => `${c.type}: ${(c as any).title || (c as any).label || ''}`)
              .join('; ')
            content += `\n[Active Components: ${compSummary}]`
          }
          return {
            role: m.role as MessageRole,
            content,
          }
        })

      const controller = new AbortController()
      abortControllerRef.current = controller
      setIsStreaming(true)

      let assistantMessageId = generateId()
      let assistantCreated = false

      try {
        await streamChatCompletion({
          messages: historyPayload,
          signal: controller.signal,
          onStart: (startData) => {
            assistantMessageId = startData.message_id || generateId()
            assistantCreated = true
            setMessages((prev) => [
              ...prev,
              {
                id: assistantMessageId,
                role: 'assistant',
                content: '',
                components: [],
                status: 'streaming',
                statusMessage: undefined,
                timestamp: Date.now(),
              },
            ])
          },
          onStatus: (statusText) => {
            setMessages((prev) => {
              const lastIdx = prev.length - 1
              if (lastIdx < 0) return prev
              const copy = [...prev]
              copy[lastIdx] = {
                ...copy[lastIdx],
                statusMessage: statusText,
              }
              return copy
            })
          },
          onToken: (delta) => {
            setMessages((prev) => {
              if (!assistantCreated) {
                assistantCreated = true
                return [
                  ...prev,
                  {
                    id: assistantMessageId,
                    role: 'assistant',
                    content: delta,
                    components: [],
                    status: 'streaming',
                    timestamp: Date.now(),
                  },
                ]
              }
              const lastIdx = prev.length - 1
              if (lastIdx < 0) return prev
              const lastMsg = prev[lastIdx]
              if (lastMsg.role === 'assistant') {
                const copy = [...prev]
                copy[lastIdx] = {
                  ...lastMsg,
                  content: lastMsg.content + delta,
                }
                return copy
              }
              return prev
            })
          },
          onUIComponent: (component) => {
            setMessages((prev) => {
              if (!assistantCreated) {
                assistantCreated = true
                return [
                  ...prev,
                  {
                    id: assistantMessageId,
                    role: 'assistant',
                    content: '',
                    components: [component],
                    status: 'streaming',
                    timestamp: Date.now(),
                  },
                ]
              }
              const lastIdx = prev.length - 1
              if (lastIdx < 0) return prev
              const lastMsg = prev[lastIdx]
              if (lastMsg.role === 'assistant') {
                const copy = [...prev]
                const existing = lastMsg.components || []
                copy[lastIdx] = {
                  ...lastMsg,
                  components: [...existing, component],
                }
                return copy
              }
              return prev
            })
          },
          onDone: () => {
            setMessages((prev) => {
              const lastIdx = prev.length - 1
              if (lastIdx < 0) return prev
              const lastMsg = prev[lastIdx]
              if (lastMsg.role === 'assistant') {
                const copy = [...prev]
                copy[lastIdx] = {
                  ...lastMsg,
                  status: 'complete',
                  statusMessage: undefined,
                }
                return copy
              }
              return prev
            })
            setIsStreaming(false)
            abortControllerRef.current = null
          },
          onError: (errMsg) => {
            setMessages((prev) => {
              if (!assistantCreated) {
                return [
                  ...prev,
                  {
                    id: assistantMessageId,
                    role: 'assistant',
                    content: '',
                    components: [],
                    status: 'error',
                    error: errMsg,
                    timestamp: Date.now(),
                  },
                ]
              }
              const lastIdx = prev.length - 1
              if (lastIdx < 0) return prev
              const copy = [...prev]
              copy[lastIdx] = {
                ...copy[lastIdx],
                status: 'error',
                statusMessage: undefined,
                error: errMsg,
              }
              return copy
            })
            setGlobalError(errMsg)
            setIsStreaming(false)
            abortControllerRef.current = null
          },
        })
      } catch (err: unknown) {
        if (err instanceof DOMException && err.name === 'AbortError') {
          return
        }
        const message = err instanceof Error ? err.message : 'Generation failed.'
        setGlobalError(message)
      } finally {
        setIsStreaming(false)
        abortControllerRef.current = null
      }
    },
    [messages, isStreaming]
  )

  const clearConversation = useCallback(() => {
    if (isStreaming) {
      stopGenerating()
    }
    setMessages([])
    setGlobalError(null)
  }, [isStreaming, stopGenerating])

  return (
    <div className="flex h-screen w-full flex-col bg-slate-50 text-slate-800 antialiased relative">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-200 px-6 bg-white/90 backdrop-blur z-10">
        <div className="flex items-center">
          <h1 className="text-base font-semibold tracking-tight text-slate-900">
            MyGPT
          </h1>
        </div>

        {/* Header Right Actions */}
        <div className="flex items-center gap-3">
          {messages.length > 0 && (
            <button
              type="button"
              data-testid="clear-chat-button"
              onClick={clearConversation}
              className="flex items-center gap-1.5 text-xs text-slate-600 hover:text-slate-900 transition-colors px-2.5 py-1.5 rounded-lg border border-slate-200 hover:border-slate-300 bg-white shadow-xs font-medium"
            >
              <Plus size={14} />
              New
            </button>
          )}
        </div>
      </header>

      {/* Global Error Banner */}
      {globalError && (
        <div
          data-testid="global-error-banner"
          className="mx-auto my-2 max-w-4xl w-full px-4"
        >
          <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex justify-between items-center">
            <span>{globalError}</span>
            <button
              type="button"
              onClick={() => setGlobalError(null)}
              className="text-red-500 hover:text-red-700 ml-4 font-bold"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Unified Conversation Feed & Composer */}
      <div className="flex flex-1 flex-col overflow-hidden w-full relative">
        <MessageList
          messages={messages}
          isStreaming={isStreaming}
          onPresetSelect={(prompt) => sendMessage(prompt)}
        />
        <ChatInput
          onSendMessage={sendMessage}
          onStopGenerating={stopGenerating}
          isStreaming={isStreaming}
        />
      </div>
    </div>
  )
}
