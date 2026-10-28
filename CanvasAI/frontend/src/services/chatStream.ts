import { SSEParser } from './sseParser'
import type {
  SSEDoneData,
  SSEErrorData,
  SSEStartData,
  SSEStatusData,
  SSETokenData,
  SSEUIComponentData,
  StreamChatOptions,
} from '../types/chat'
import type { ImageComponentSpec } from '../types/uiPlan'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || ''

export async function streamChatCompletion(options: StreamChatOptions): Promise<void> {
  const {
    messages,
    model,
    temperature,
    signal,
    onStart,
    onStatus,
    onToken,
    onUIComponent,
    onDone,
    onError,
  } = options

  let completedOrErrored = false

  const parser = new SSEParser((event) => {
    switch (event.event) {
      case 'start': {
        const startData = event.data as SSEStartData
        onStart?.(startData)
        break
      }
      case 'status': {
        const statusData = event.data as SSEStatusData
        if (statusData?.status) {
          onStatus?.(statusData.status)
        }
        break
      }
      case 'token': {
        const tokenData = event.data as SSETokenData
        if (tokenData?.delta) {
          onToken?.(tokenData.delta)
        }
        break
      }
      case 'ui_component': {
        const compData = event.data as SSEUIComponentData
        if (compData?.component) {
          onUIComponent?.(compData.component)
        }
        break
      }
      case 'image': {
        const imgData = event.data as Record<string, string>
        if (imgData?.url) {
          const imgSpec: ImageComponentSpec = {
            type: 'image',
            url: imgData.url,
            alt: imgData.alt || 'Generated image asset',
            caption: imgData.caption,
          }
          onUIComponent?.(imgSpec)
        }
        break
      }
      case 'done': {
        completedOrErrored = true
        const doneData = event.data as SSEDoneData
        onDone?.(doneData)
        break
      }
      case 'error': {
        completedOrErrored = true
        const errorData = event.data as SSEErrorData
        onError?.(errorData?.message || 'An error occurred during generation.')
        break
      }
      default:
        // Ignore unhandled event types safely
        break
    }
  })

  try {
    const response = await fetch(`${API_BASE_URL}/api/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      },
      body: JSON.stringify({
        messages,
        model: model || undefined,
        temperature: temperature ?? undefined,
      }),
      signal,
    })

    if (!response.ok) {
      let errorMessage = `Server error (${response.status})`
      try {
        const errJson = await response.json()
        if (errJson?.detail) {
          errorMessage = typeof errJson.detail === 'string' ? errJson.detail : JSON.stringify(errJson.detail)
        }
      } catch {
        // fallback to status code message
      }
      onError?.(errorMessage)
      return
    }

    if (!response.body) {
      onError?.('Readable stream is not supported or response body is empty.')
      return
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')

    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const chunkText = decoder.decode(value, { stream: true })
        parser.feed(chunkText)
      }

      // Final flush
      const remaining = decoder.decode()
      if (remaining) {
        parser.feed(remaining)
      }
    } finally {
      reader.releaseLock()
    }

    // If stream ended without explicit done or error event, mark done
    if (!completedOrErrored) {
      onDone?.({ finish_reason: 'stop' })
    }
  } catch (err: unknown) {
    if (err instanceof DOMException && err.name === 'AbortError') {
      // User aborted generation; propagate cleanly
      throw err
    }
    const message = err instanceof Error ? err.message : 'Network error occurred.'
    onError?.(message)
  }
}
