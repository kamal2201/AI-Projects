import React, { useEffect, useRef, useState } from 'react'
import mermaid from 'mermaid'
import { ImageOff, AlertCircle } from 'lucide-react'
import type { DiagramComponentSpec, ImageComponentSpec } from '../../types/uiPlan'

// Initialize mermaid with strict security level and light theme
mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'default',
  fontFamily: 'ui-sans-serif, system-ui, sans-serif',
})

export const DiagramRenderer: React.FC<{ spec: DiagramComponentSpec }> = ({
  spec,
}) => {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svgContent, setSvgContent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let isMounted = true
    const renderDiagram = async () => {
      try {
        setError(null)
        const id = `mermaid-${Math.random().toString(36).substring(2, 9)}`
        const { svg } = await mermaid.render(id, spec.syntax)
        if (isMounted) {
          setSvgContent(svg)
        }
      } catch (err: unknown) {
        if (isMounted) {
          setError('Failed to render diagram: Invalid syntax or unsupported diagram format.')
        }
      }
    }

    renderDiagram()
    return () => {
      isMounted = false
    }
  }, [spec.syntax])

  return (
    <div
      data-testid="rendered-diagram"
      className="p-5 rounded-2xl bg-white border border-slate-200 text-xs shadow-xs my-3"
    >
      <h4 className="font-semibold text-slate-900 text-sm mb-3">{spec.title}</h4>

      {error ? (
        <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-red-700 text-xs flex items-center gap-2">
          <AlertCircle size={15} className="shrink-0 text-red-500" />
          <span>{error}</span>
        </div>
      ) : svgContent ? (
        <div
          ref={containerRef}
          data-testid="mermaid-svg-container"
          className="overflow-x-auto flex justify-center py-2 bg-slate-50 rounded-xl p-3 border border-slate-200"
          dangerouslySetInnerHTML={{ __html: svgContent }}
        />
      ) : (
        <div className="p-6 text-center text-slate-400 italic">Rendering diagram...</div>
      )}

      {spec.caption && (
        <p className="text-[11px] text-slate-500 mt-2 text-center">{spec.caption}</p>
      )}
    </div>
  )
}

export const ImageRenderer: React.FC<{ spec: ImageComponentSpec }> = ({
  spec,
}) => {
  const [hasError, setHasError] = useState(false)

  // Validate URL scheme client-side
  const isSafeUrl =
    spec.url.startsWith('https://') || spec.url.startsWith('http://localhost')

  if (!isSafeUrl) {
    return (
      <div
        data-testid="rendered-image-unsafe"
        className="p-4 rounded-xl bg-red-50 border border-red-200 text-red-700 text-xs flex items-center gap-2 my-3"
      >
        <AlertCircle size={16} className="text-red-500" />
        <span>Image rejected: Only secure HTTPS URLs are permitted.</span>
      </div>
    )
  }

  return (
    <div
      data-testid="rendered-image"
      className="rounded-2xl bg-white border border-slate-200 overflow-hidden text-xs my-3 shadow-xs"
    >
      {hasError ? (
        <div className="flex flex-col items-center justify-center p-8 text-slate-400 bg-slate-50">
          <ImageOff size={28} className="mb-2 text-slate-400" />
          <span>Image failed to load</span>
        </div>
      ) : (
        <img
          src={spec.url}
          alt={spec.alt}
          onError={() => setHasError(true)}
          className="w-full max-h-96 object-contain bg-slate-50"
          loading="lazy"
        />
      )}
      {spec.caption && (
        <div className="p-3 text-[11px] text-slate-500 text-center border-t border-slate-200">
          {spec.caption}
        </div>
      )}
    </div>
  )
}
