import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { ChatInterface } from '../components/ChatInterface'
import * as chatStreamModule from '../services/chatStream'

describe('ChatInterface Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    window.HTMLElement.prototype.scrollIntoView = vi.fn()
  })

  it('renders initial empty state with welcome title and sample prompts', () => {
    render(<ChatInterface />)

    expect(screen.getAllByText('MyGPT').length).toBeGreaterThan(0)
    expect(
      screen.getByPlaceholderText(/Ask a question or enter a prompt/i)
    ).toBeInTheDocument()
  })

  it('submits a prompt and incrementally updates message with streamed tokens', async () => {
    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        act(() => {
          options.onStart?.({ message_id: 'msg-1', model: 'gemini-2.5-flash' })
        })
        await new Promise((r) => setTimeout(r, 10))
        act(() => {
          options.onToken?.('Hello')
        })
        await new Promise((r) => setTimeout(r, 10))
        act(() => {
          options.onToken?.(' from Gemini!')
        })
        act(() => {
          options.onDone?.({ finish_reason: 'stop' })
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    const sendButton = screen.getByTestId('send-message-button')

    fireEvent.change(textarea, { target: { value: 'Hi there' } })
    fireEvent.click(sendButton)

    // User message should appear immediately
    expect(screen.getByText('Hi there')).toBeInTheDocument()

    // Wait for the stream to complete and assistant text to accumulate
    await waitFor(() => {
      expect(screen.getByText(/Hello from Gemini!/i)).toBeInTheDocument()
    })
  })

  it('allows user to stop generation using Stop generating button', async () => {
    let capturedSignal: AbortSignal | undefined

    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        capturedSignal = options.signal
        act(() => {
          options.onStart?.({ message_id: 'msg-stop' })
          options.onToken?.('Partial token before stop...')
        })
        // Hang to simulate active streaming until aborted
        return new Promise<void>((_, reject) => {
          options.signal?.addEventListener('abort', () => {
            const err = new DOMException('Aborted', 'AbortError')
            reject(err)
          })
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Generate a long essay' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    // Streaming indicator should appear
    await waitFor(() => {
      expect(screen.getByTestId('streaming-indicator')).toBeInTheDocument()
    })

    expect(screen.getByText(/Partial token before stop/i)).toBeInTheDocument()

    // Click Stop button
    const stopButton = screen.getByTestId('stop-generating-button')
    fireEvent.click(stopButton)

    // Streaming indicator should disappear, and status marked Stopped
    await waitFor(() => {
      expect(screen.queryByTestId('streaming-indicator')).not.toBeInTheDocument()
      expect(screen.getByText('Stopped')).toBeInTheDocument()
    })

    expect(capturedSignal?.aborted).toBe(true)
  })

  it('displays safe error banner without marking assistant response complete', async () => {
    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        act(() => {
          options.onStart?.({ message_id: 'msg-err' })
          options.onError?.('Authentication failed. Please verify API key.')
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Test error' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    await waitFor(() => {
      expect(screen.getByTestId('global-error-banner')).toBeInTheDocument()
      expect(screen.getByTestId('message-error-banner')).toBeInTheDocument()
      expect(screen.getByText('Failed')).toBeInTheDocument()
    })
  })

  it('preserves conversation history for subsequent requests', async () => {
    const payloadsSent: any[] = []

    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        payloadsSent.push(options.messages)
        act(() => {
          options.onStart?.({ message_id: `msg-${payloadsSent.length}` })
          options.onToken?.(`Answer turn ${payloadsSent.length}`)
          options.onDone?.({ finish_reason: 'stop' })
        })
      }
    )

    render(<ChatInterface />)

    // Turn 1
    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Question 1' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    await waitFor(() => {
      expect(screen.getByText('Answer turn 1')).toBeInTheDocument()
    })

    // Turn 2
    fireEvent.change(textarea, { target: { value: 'Question 2' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    await waitFor(() => {
      expect(screen.getByText('Answer turn 2')).toBeInTheDocument()
    })

    // Verify turn 2 included turn 1's history
    expect(payloadsSent).toHaveLength(2)
    expect(payloadsSent[0]).toEqual([{ role: 'user', content: 'Question 1' }])
    expect(payloadsSent[1]).toEqual([
      { role: 'user', content: 'Question 1' },
      { role: 'assistant', content: 'Answer turn 1' },
      { role: 'user', content: 'Question 2' },
    ])
  })

  it('renders markdown safely without executing scripts or injecting raw HTML elements', async () => {
    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        act(() => {
          options.onStart?.({ message_id: 'msg-sec' })
          options.onToken?.('**Bold text** and `code` <script>window.__injected = true;</script>')
          options.onDone?.({ finish_reason: 'stop' })
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Test security' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    await waitFor(() => {
      expect(screen.getByText('Bold text')).toBeInTheDocument()
      expect(screen.getByText('code')).toBeInTheDocument()
    })

    // Assert script was NOT executed or injected as executable DOM script tag
    expect((window as any).__injected).toBeUndefined()
    expect(document.querySelector('script:not([type])')).toBeNull()
  })

  it('renders MyGPT header and unified conversation experience without a mode selector', async () => {
    render(<ChatInterface />)

    // Verify single unified message composer exists
    expect(screen.getByTestId('chat-input-textarea')).toBeInTheDocument()
    expect(screen.getAllByText('MyGPT').length).toBeGreaterThan(0)

    // Mode tabs must not exist
    expect(screen.queryByTestId('tab-streaming-chat')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tab-ui-plan-inspector')).not.toBeInTheDocument()
  })

  it('renders mixed text and completed UI components in a single assistant message', async () => {
    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        act(() => {
          options.onStart?.({ message_id: 'msg-mixed' })
          options.onStatus?.('Planning adaptive UI...')
        })
        act(() => {
          options.onToken?.('Here is your Sunday roast overview:\n')
        })
        act(() => {
          options.onUIComponent?.({
            type: 'card',
            title: 'Roast Menu',
            body: 'Garlic & herb roasted beef with seasonal vegetables.',
          })
        })
        act(() => {
          options.onToken?.('\nTotal cook time metrics:')
        })
        act(() => {
          options.onUIComponent?.({
            type: 'metric',
            label: 'Total Time',
            value: '3.5 hrs',
            change: 'Low & slow',
            trend: 'neutral',
          })
        })
        act(() => {
          options.onDone?.({ finish_reason: 'stop' })
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Sunday roast plan' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    // Verify both text prose and rendered UI components appear in the message
    await waitFor(() => {
      expect(screen.getByText(/Here is your Sunday roast overview/i)).toBeInTheDocument()
      expect(screen.getByText('Roast Menu')).toBeInTheDocument()
      expect(screen.getByText('Total Time')).toBeInTheDocument()
      expect(screen.getByText('3.5 hrs')).toBeInTheDocument()
      expect(screen.getByText(/Total cook time metrics/i)).toBeInTheDocument()
    })
  })

  it('renders mathematical expressions and prevents raw JSON leakage into conversation', async () => {
    vi.spyOn(chatStreamModule, 'streamChatCompletion').mockImplementation(
      async (options) => {
        act(() => {
          options.onStart?.({ message_id: 'msg-math' })
          options.onToken?.('The linear equation is given by $ŷ = wx + b$ where $w$ is slope and $b$ is intercept.')
          // Simulate raw JSON leaking into token stream
          options.onToken?.('\n```json\n{"type": "table", "title": "Leak"}\n```')
          options.onUIComponent?.({
            type: 'table',
            title: 'Model Parameters',
            headers: ['Parameter', 'Meaning'],
            rows: [
              ['w', 'Slope parameter'],
              ['b', 'Y-intercept'],
            ],
          })
          options.onDone?.({ finish_reason: 'stop' })
        })
      }
    )

    render(<ChatInterface />)

    const textarea = screen.getByTestId('chat-input-textarea')
    fireEvent.change(textarea, { target: { value: 'Explain regression formula' } })
    fireEvent.click(screen.getByTestId('send-message-button'))

    await waitFor(() => {
      // Equation and definitions rendered
      expect(screen.getByText(/The linear equation is given by/i)).toBeInTheDocument()
      // Structured table rendered as actual table with headers and rows
      expect(screen.getByTestId('rendered-table')).toBeInTheDocument()
      expect(screen.getByText('Model Parameters')).toBeInTheDocument()
      expect(screen.getByText('Slope parameter')).toBeInTheDocument()
    })

    // Raw JSON must NOT be rendered in the message
    expect(screen.queryByText(/{"type": "table"/)).not.toBeInTheDocument()
  })
})
