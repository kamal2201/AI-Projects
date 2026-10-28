import { describe, it, expect, vi } from 'vitest'
import { SSEParser } from '../services/sseParser'
import type { SSEEvent } from '../types/chat'

describe('SSEParser', () => {
  it('parses complete SSE events correctly', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    parser.feed('event: start\ndata: {"message_id": "123", "model": "gemini-2.5-flash"}\n\n')
    parser.feed('event: token\ndata: {"delta": "Hello"}\n\n')
    parser.feed('event: done\ndata: {"finish_reason": "stop"}\n\n')

    expect(events).toHaveLength(3)
    expect(events[0]).toEqual({
      event: 'start',
      data: { message_id: '123', model: 'gemini-2.5-flash' },
      raw: '{"message_id": "123", "model": "gemini-2.5-flash"}',
    })
    expect(events[1]).toEqual({
      event: 'token',
      data: { delta: 'Hello' },
      raw: '{"delta": "Hello"}',
    })
    expect(events[2]).toEqual({
      event: 'done',
      data: { finish_reason: 'stop' },
      raw: '{"finish_reason": "stop"}',
    })
  })

  it('correctly handles split network chunks across event and data boundaries', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    // Chunk 1: partial event
    parser.feed('event: to')
    expect(events).toHaveLength(0)

    // Chunk 2: rest of event line, partial data
    parser.feed('ken\ndata: {"del')
    expect(events).toHaveLength(0)

    // Chunk 3: rest of data and closing boundary
    parser.feed('ta": "Chunked text"}\n\n')
    expect(events).toHaveLength(1)
    expect(events[0].event).toBe('token')
    expect(events[0].data).toEqual({ delta: 'Chunked text' })
  })

  it('correctly parses multiple events arriving in a single network chunk', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    const multiChunk =
      'event: token\ndata: {"delta": "Hello"}\n\nevent: token\ndata: {"delta": " World"}\n\nevent: done\ndata: {"finish_reason": "stop"}\n\n'
    parser.feed(multiChunk)

    expect(events).toHaveLength(3)
    expect(events[0].data).toEqual({ delta: 'Hello' })
    expect(events[1].data).toEqual({ delta: ' World' })
    expect(events[2].data).toEqual({ finish_reason: 'stop' })
  })

  it('handles CRLF (\\r\\n\\r\\n) line endings gracefully', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    parser.feed('event: token\r\ndata: {"delta": "CRLF test"}\r\n\r\n')
    expect(events).toHaveLength(1)
    expect(events[0].data).toEqual({ delta: 'CRLF test' })
  })

  it('ignores comments and empty lines', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    parser.feed(': keep-alive ping\n\n')
    parser.feed('\n\n')
    parser.feed('event: token\ndata: {"delta": "Valid"}\n\n')

    expect(events).toHaveLength(1)
    expect(events[0].data).toEqual({ delta: 'Valid' })
  })

  it('handles malformed non-JSON payloads safely without crashing', () => {
    const events: SSEEvent[] = []
    const parser = new SSEParser((ev) => events.push(ev))

    parser.feed('event: custom\ndata: non-json raw text\n\n')
    expect(events).toHaveLength(1)
    expect(events[0].event).toBe('custom')
    expect(events[0].data).toEqual({ raw: 'non-json raw text' })
  })

  it('resets buffer correctly', () => {
    const parser = new SSEParser(vi.fn())
    parser.feed('event: partial')
    expect(parser.getBuffered()).toBe('event: partial')
    parser.reset()
    expect(parser.getBuffered()).toBe('')
  })
})
