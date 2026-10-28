import type { SSEEvent, SSEPayload } from '../types/chat'

export class SSEParser {
  private buffer = ''
  private onEvent: (event: SSEEvent) => void

  constructor(onEvent: (event: SSEEvent) => void) {
    this.onEvent = onEvent
  }

  /**
   * Feed a new text chunk received from the network.
   * Chunks are accumulated in the internal buffer, and complete SSE messages
   * (separated by double newlines) are parsed and dispatched.
   */
  public feed(chunk: string): void {
    if (!chunk) return

    this.buffer += chunk
    // Normalize CRLF and CR to LF
    this.buffer = this.buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

    let boundaryIndex: number
    while ((boundaryIndex = this.buffer.indexOf('\n\n')) !== -1) {
      const messageBlock = this.buffer.slice(0, boundaryIndex)
      this.buffer = this.buffer.slice(boundaryIndex + 2)
      this.parseMessageBlock(messageBlock)
    }
  }

  /**
   * Parse a single SSE message block.
   */
  private parseMessageBlock(block: string): void {
    const lines = block.split('\n')
    let eventName = 'message'
    const dataLines: string[] = []

    for (const line of lines) {
      if (!line || line.startsWith(':')) {
        // SSE comments or empty lines
        continue
      }

      if (line.startsWith('event:')) {
        eventName = line.slice(6).trim()
      } else if (line.startsWith('data:')) {
        // According to SSE spec, if line begins with data:, remove a single leading space if present
        let dataContent = line.slice(5)
        if (dataContent.startsWith(' ')) {
          dataContent = dataContent.slice(1)
        }
        dataLines.push(dataContent)
      }
    }

    if (dataLines.length === 0 && eventName === 'message') {
      return
    }

    const rawData = dataLines.join('\n')
    let parsedPayload: SSEPayload = {}

    if (rawData) {
      try {
        parsedPayload = JSON.parse(rawData) as SSEPayload
      } catch {
        parsedPayload = { raw: rawData }
      }
    }

    this.onEvent({
      event: eventName,
      data: parsedPayload,
      raw: rawData,
    })
  }

  /**
   * Clear any remaining buffered text.
   */
  public reset(): void {
    this.buffer = ''
  }

  /**
   * Return current buffer content (helpful for test inspections).
   */
  public getBuffered(): string {
    return this.buffer
  }
}
