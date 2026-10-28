import { describe, it, expect, vi, beforeEach } from 'vitest'
import { streamChatCompletion } from '../services/chatStream'

function createMockStream(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  let index = 0

  return new ReadableStream({
    pull(controller) {
      if (index < chunks.length) {
        controller.enqueue(encoder.encode(chunks[index]))
        index++
      } else {
        controller.close()
      }
    },
  })
}

describe('streamChatCompletion', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('handles incremental streaming tokens and triggers callbacks', async () => {
    const sseChunks = [
      'event: start\ndata: {"message_id": "msg-1", "model": "gemini-2.5-flash"}\n\n',
      'event: token\ndata: {"delta": "Hello "}\n\n',
      'event: token\ndata: {"delta": "world!"}\n\n',
      'event: done\ndata: {"finish_reason": "stop"}\n\n',
    ]

    const mockResponse = {
      ok: true,
      body: createMockStream(sseChunks),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onStart = vi.fn()
    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    await streamChatCompletion({
      messages: [{ role: 'user', content: 'Say hello' }],
      onStart,
      onToken,
      onDone,
      onError,
    })

    expect(onStart).toHaveBeenCalledWith({
      message_id: 'msg-1',
      model: 'gemini-2.5-flash',
    })
    expect(onToken).toHaveBeenCalledTimes(2)
    expect(onToken).toHaveBeenNthCalledWith(1, 'Hello ')
    expect(onToken).toHaveBeenNthCalledWith(2, 'world!')
    expect(onDone).toHaveBeenCalledWith({ finish_reason: 'stop' })
    expect(onError).not.toHaveBeenCalled()
  })

  it('triggers onError and never onDone when stream contains error event', async () => {
    const sseChunks = [
      'event: start\ndata: {"message_id": "msg-err"}\n\n',
      'event: token\ndata: {"delta": "Starting..."}\n\n',
      'event: error\ndata: {"message": "Rate limit exceeded"}\n\n',
    ]

    const mockResponse = {
      ok: true,
      body: createMockStream(sseChunks),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onToken = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()

    await streamChatCompletion({
      messages: [{ role: 'user', content: 'Trigger error' }],
      onToken,
      onDone,
      onError,
    })

    expect(onToken).toHaveBeenCalledWith('Starting...')
    expect(onError).toHaveBeenCalledWith('Rate limit exceeded')
    expect(onDone).not.toHaveBeenCalled()
  })

  it('handles status and ui_component events in the stream', async () => {
    const sseChunks = [
      'event: start\ndata: {"message_id": "msg-ui"}\n\n',
      'event: status\ndata: {"status": "Synthesizing UI..."}\n\n',
      'event: token\ndata: {"delta": "Intro text"}\n\n',
      'event: ui_component\ndata: {"component": {"type": "card", "title": "Overview", "body": "Body"}}\n\n',
      'event: done\ndata: {"finish_reason": "stop"}\n\n',
    ]

    const mockResponse = {
      ok: true,
      body: createMockStream(sseChunks),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onStatus = vi.fn()
    const onToken = vi.fn()
    const onUIComponent = vi.fn()
    const onDone = vi.fn()

    await streamChatCompletion({
      messages: [{ role: 'user', content: 'UI request' }],
      onStatus,
      onToken,
      onUIComponent,
      onDone,
    })

    expect(onStatus).toHaveBeenCalledWith('Synthesizing UI...')
    expect(onToken).toHaveBeenCalledWith('Intro text')
    expect(onUIComponent).toHaveBeenCalledWith({
      type: 'card',
      title: 'Overview',
      body: 'Body',
    })
    expect(onDone).toHaveBeenCalledWith({ finish_reason: 'stop' })
  })

  it('handles non-200 HTTP responses safely', async () => {
    const mockResponse = {
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Internal AI Provider Error' }),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onError = vi.fn()
    const onDone = vi.fn()

    await streamChatCompletion({
      messages: [{ role: 'user', content: 'Fail' }],
      onError,
      onDone,
    })

    expect(onError).toHaveBeenCalledWith('Internal AI Provider Error')
    expect(onDone).not.toHaveBeenCalled()
  })

  it('handles split network chunks gracefully across boundaries', async () => {
    // Network chunks split mid-token
    const splitChunks = [
      'event: start\ndata: {"message_id": "split-msg"}\n\n',
      'event: to',
      'ken\ndata: {"delta": "Split',
      ' token"}\n\n',
      'event: done\ndata: {"finish_reason": "stop"}\n\n',
    ]

    const mockResponse = {
      ok: true,
      body: createMockStream(splitChunks),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onToken = vi.fn()
    const onDone = vi.fn()

    await streamChatCompletion({
      messages: [{ role: 'user', content: 'Split test' }],
      onToken,
      onDone,
    })

    expect(onToken).toHaveBeenCalledWith('Split token')
    expect(onDone).toHaveBeenCalledWith({ finish_reason: 'stop' })
  })

  it('handles empty response stream safely', async () => {
    const mockResponse = {
      ok: true,
      body: createMockStream([]),
    }

    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(mockResponse as unknown as Response)

    const onDone = vi.fn()
    await streamChatCompletion({
      messages: [{ role: 'user', content: 'Empty test' }],
      onDone,
    })

    expect(onDone).toHaveBeenCalledWith({ finish_reason: 'stop' })
  })

  it('propagates DOMException when aborted via AbortController', async () => {
    const controller = new AbortController()

    vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => {
      controller.abort()
      const abortErr = new DOMException('The user aborted a request.', 'AbortError')
      return Promise.reject(abortErr)
    })

    await expect(
      streamChatCompletion({
        messages: [{ role: 'user', content: 'Stop test' }],
        signal: controller.signal,
      })
    ).rejects.toThrow('The user aborted a request.')
  })
})
