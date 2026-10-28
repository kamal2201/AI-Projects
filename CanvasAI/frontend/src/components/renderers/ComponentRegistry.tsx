import React, { Component, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'
import type { UIComponentSpec } from '../../types/uiPlan'
import {
  CodeBlockRenderer,
  CalloutRenderer,
  ExpandableRenderer,
} from './TextAndCodeRenderers'
import {
  CardRenderer,
  CardGridRenderer,
  MetricRenderer,
  TabsRenderer,
  AccordionRenderer,
  ComparisonRenderer,
} from './LayoutRenderers'
import { ChartRenderer, TableRenderer } from './DataRenderers'
import { DiagramRenderer, ImageRenderer } from './MediaAndDiagramRenderers'
import { TimelineRenderer, StepsRenderer, ProsConsRenderer } from './LearningRenderers'
import { CalculatorRenderer, InteractiveControlRenderer } from './InteractiveRenderers'
import { RegressionRenderer } from './RegressionRenderer'

interface SafeComponentBoundaryProps {
  componentType: string
  children: ReactNode
}

interface SafeComponentBoundaryState {
  hasError: boolean
  errorMsg?: string
}

export class SafeComponentBoundary extends Component<
  SafeComponentBoundaryProps,
  SafeComponentBoundaryState
> {
  constructor(props: SafeComponentBoundaryProps) {
    super(props)
    this.state = { hasError: false }
  }

  static getDerivedStateFromError(error: Error): SafeComponentBoundaryState {
    return { hasError: true, errorMsg: error.message }
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    console.error('Component rendering error:', error, errorInfo)
  }

  render() {
    if (this.state.hasError) {
      return (
        <div
          data-testid="component-render-fallback"
          className="p-3 my-2 rounded-xl bg-amber-50 border border-amber-200 text-amber-800 text-xs flex items-center gap-2"
        >
          <AlertTriangle size={15} className="text-amber-600 shrink-0" />
          <span>
            Unable to render component &lsquo;{this.props.componentType}&rsquo;: {this.state.errorMsg || 'Rendering error'}
          </span>
        </div>
      )
    }
    return this.props.children
  }
}

export const renderComponent = (
  spec: UIComponentSpec,
  key: string | number
): ReactNode => {
  const renderInner = () => {
    switch (spec.type) {
      case 'card':
        return <CardRenderer spec={spec} />
      case 'card_grid':
        return <CardGridRenderer spec={spec} />
      case 'metric':
        return <MetricRenderer spec={spec} />
      case 'chart':
        return <ChartRenderer spec={spec} />
      case 'table':
        return <TableRenderer spec={spec} />
      case 'code_block':
        return <CodeBlockRenderer spec={spec} />
      case 'callout':
        return <CalloutRenderer spec={spec} />
      case 'expandable':
        return <ExpandableRenderer spec={spec} />
      case 'accordion':
        return <AccordionRenderer spec={spec} />
      case 'tabs':
        return <TabsRenderer spec={spec} />
      case 'comparison':
        return <ComparisonRenderer spec={spec} />
      case 'pros_cons':
        return <ProsConsRenderer spec={spec} />
      case 'timeline':
        return <TimelineRenderer spec={spec} />
      case 'steps':
        return <StepsRenderer spec={spec} />
      case 'diagram':
        return <DiagramRenderer spec={spec} />
      case 'image':
        return <ImageRenderer spec={spec} />
      case 'interactive_control':
        return <InteractiveControlRenderer spec={spec} />
      case 'calculator':
        return <CalculatorRenderer spec={spec} />
      case 'regression':
        return <RegressionRenderer spec={spec} />
      default:
        return (
          <div
            data-testid="unsupported-component-fallback"
            className="p-3 my-2 rounded-xl bg-slate-100 border border-slate-200 text-slate-700 text-xs"
          >
            Unsupported component specification type: &lsquo;{(spec as any).type}&rsquo;
          </div>
        )
    }
  }

  return (
    <SafeComponentBoundary key={key} componentType={spec.type}>
      {renderInner()}
    </SafeComponentBoundary>
  )
}
