import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { renderComponent } from '../components/renderers/ComponentRegistry'
import { MessageComponentProvider } from '../context/MessageComponentContext'
import type {
  CardComponentSpec,
  ChartComponentSpec,
  MetricComponentSpec,
  TableComponentSpec,
  CodeBlockComponentSpec,
  CalloutComponentSpec,
  CalculatorComponentSpec,
  InteractiveControlComponentSpec,
  ImageComponentSpec,
  DiagramComponentSpec,
  TabsComponentSpec,
  AccordionComponentSpec,
  ProsConsComponentSpec,
  TimelineComponentSpec,
  StepsComponentSpec,
} from '../types/uiPlan'

describe('ComponentRegistry & Dynamic Renderers', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('renders a Metric KPI card with trend indicator', () => {
    const spec: MetricComponentSpec = {
      type: 'metric',
      label: 'Monthly Recurring Revenue',
      value: '$84,500',
      change: '+14.2%',
      trend: 'up',
      subtext: 'vs previous month',
    }
    render(<>{renderComponent(spec, 'metric-1')}</>)

    expect(screen.getByText('Monthly Recurring Revenue')).toBeInTheDocument()
    expect(screen.getByText('$84,500')).toBeInTheDocument()
    expect(screen.getByText('+14.2%')).toBeInTheDocument()
    expect(screen.getByText('vs previous month')).toBeInTheDocument()
  })

  it('renders Table and performs column sorting on click', () => {
    const spec: TableComponentSpec = {
      type: 'table',
      title: 'Plan Comparison',
      headers: ['Plan', 'Price'],
      rows: [
        ['Enterprise', '$99'],
        ['Basic', '$19'],
        ['Pro', '$49'],
      ],
    }
    render(<>{renderComponent(spec, 'table-1')}</>)

    expect(screen.getByText('Plan Comparison')).toBeInTheDocument()
    const priceHeader = screen.getByText('Price')

    // Click to sort by price ascending
    fireEvent.click(priceHeader)
    const rowsAsc = screen.getAllByRole('row')
    expect(rowsAsc[1]).toHaveTextContent('$19') // Basic

    // Click to sort descending
    fireEvent.click(priceHeader)
    const rowsDesc = screen.getAllByRole('row')
    expect(rowsDesc[1]).toHaveTextContent('$99') // Enterprise
  })

  it('renders CodeBlock with syntax and copy functionality', async () => {
    const spec: CodeBlockComponentSpec = {
      type: 'code_block',
      title: 'example.py',
      language: 'python',
      code: 'def stream_chat():\n    yield "Hello"',
    }
    render(<>{renderComponent(spec, 'code-1')}</>)

    expect(screen.getByText('example.py')).toBeInTheDocument()
    expect(screen.getByText(/def stream_chat/)).toBeInTheDocument()

    const copyBtn = screen.getByTitle('Copy code')
    fireEvent.click(copyBtn)
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith(spec.code)
    expect(await screen.findByText('Copied')).toBeInTheDocument()
  })

  it('renders Callout component with variant style', () => {
    const spec: CalloutComponentSpec = {
      type: 'callout',
      title: 'Pro Tip',
      content: 'Use Server-Sent Events for one-way token streaming.',
      variant: 'tip',
    }
    render(<>{renderComponent(spec, 'callout-1')}</>)

    expect(screen.getByText('Pro Tip')).toBeInTheDocument()
    expect(
      screen.getByText('Use Server-Sent Events for one-way token streaming.')
    ).toBeInTheDocument()
  })

  it('renders interactive Calculator and recomputes output dynamically', () => {
    const spec: CalculatorComponentSpec = {
      type: 'calculator',
      title: 'Loan Amortization Tool',
      calculator_type: 'loan',
      initial_value: 12000,
      rate: 6.0,
      term: 1, // 1 year = 12 months
    }
    render(<>{renderComponent(spec, 'calc-1')}</>)

    expect(screen.getByText('Loan Amortization Tool')).toBeInTheDocument()
    expect(screen.getByText('Monthly Payment')).toBeInTheDocument()

    // Base calculation: $12000 loan at 6% for 1 year is approx $1,032.80/month
    expect(screen.getByText(/\$1,032\.80/)).toBeInTheDocument()

    // Change principal amount to 24000
    const principalInput = screen.getByLabelText('Base Principal Amount')
    fireEvent.change(principalInput, { target: { value: '24000' } })

    // Should dynamically update
    expect(screen.getByText(/\$2,065\.59/)).toBeInTheDocument()
  })

  it('renders interactive control and triggers allowlisted action', () => {
    const spec: InteractiveControlComponentSpec = {
      type: 'interactive_control',
      title: 'Recalculate View',
      control_type: 'button',
      label: 'Update Predictions',
      action_id: 'calculate',
    }
    render(<>{renderComponent(spec, 'ctrl-1')}</>)

    expect(screen.getByText('Update Predictions')).toBeInTheDocument()
    const btn = screen.getByText('Trigger Action')
    fireEvent.click(btn)

    expect(screen.getByText(/Verified safe action identifier executed/i)).toBeInTheDocument()
  })

  it('renders Image securely with https and rejects unsafe javascript: URL', () => {
    const safeSpec: ImageComponentSpec = {
      type: 'image',
      url: 'https://images.unsplash.com/photo-test',
      alt: 'System architecture diagram',
      caption: 'Figure 1: High level architecture',
    }
    const { unmount } = render(<>{renderComponent(safeSpec, 'img-1')}</>)
    expect(screen.getByAltText('System architecture diagram')).toBeInTheDocument()
    expect(screen.getByText('Figure 1: High level architecture')).toBeInTheDocument()
    unmount()

    // Unsafe URL test
    const unsafeSpec = {
      type: 'image',
      url: 'javascript:alert(1)',
      alt: 'Hacked',
    } as unknown as ImageComponentSpec

    render(<>{renderComponent(unsafeSpec, 'img-unsafe')}</>)
    expect(
      screen.getByText(/Image rejected: Only secure HTTPS URLs are permitted/i)
    ).toBeInTheDocument()
  })

  it('renders Tabs with working tab switching', () => {
    const spec: TabsComponentSpec = {
      type: 'tabs',
      title: 'Deployment Options',
      items: [
        { label: 'Docker', content: 'Run with docker-compose up' },
        { label: 'Kubernetes', content: 'Apply Helm charts' },
      ],
    }
    render(<>{renderComponent(spec, 'tabs-1')}</>)

    expect(screen.getByText('Run with docker-compose up')).toBeInTheDocument()

    // Click Kubernetes tab
    fireEvent.click(screen.getByText('Kubernetes'))
    expect(screen.getByText('Apply Helm charts')).toBeInTheDocument()
  })

  it('renders Accordion with working toggle', () => {
    const spec: AccordionComponentSpec = {
      type: 'accordion',
      title: 'Frequently Asked Questions',
      items: [
        { title: 'What is SSE?', content: 'Server-Sent Events' },
        { title: 'Why not WebSockets?', content: 'HTTP/2 compatibility' },
      ],
    }
    render(<>{renderComponent(spec, 'acc-1')}</>)

    expect(screen.getByText('Server-Sent Events')).toBeInTheDocument()

    // Toggle second accordion item
    fireEvent.click(screen.getByText('Why not WebSockets?'))
    expect(screen.getByText('HTTP/2 compatibility')).toBeInTheDocument()
  })

  it('renders Pros and Cons panel', () => {
    const spec: ProsConsComponentSpec = {
      type: 'pros_cons',
      title: 'Microservices Evaluation',
      pros: ['Independent scaling', 'Fault isolation'],
      cons: ['Network latency', 'Operational overhead'],
    }
    render(<>{renderComponent(spec, 'pros-cons-1')}</>)

    expect(screen.getByText('Microservices Evaluation')).toBeInTheDocument()
    expect(screen.getByText('Independent scaling')).toBeInTheDocument()
    expect(screen.getByText('Operational overhead')).toBeInTheDocument()
  })

  it('renders Diagram with Mermaid syntax', () => {
    const spec: DiagramComponentSpec = {
      type: 'diagram',
      title: 'Workflow Flowchart',
      syntax: 'graph TD\nA-->B',
      caption: 'Figure 2: Basic flow',
    }
    render(<>{renderComponent(spec, 'diag-1')}</>)
    expect(screen.getByText('Workflow Flowchart')).toBeInTheDocument()
    expect(screen.getByText('Figure 2: Basic flow')).toBeInTheDocument()
  })

  it('renders Timeline and Steps', () => {
    const timelineSpec: TimelineComponentSpec = {
      type: 'timeline',
      title: 'Roadmap',
      steps: [
        { step: 'Phase 1', title: 'Streaming Chat', description: 'Real-time token delivery' },
        { step: 'Phase 2', title: 'Structured UI', description: 'Catalogue expansion' },
      ],
    }
    const stepsSpec: StepsComponentSpec = {
      type: 'steps',
      title: 'Setup Guide',
      items: [
        { step_number: 1, title: 'Install packages', instruction: 'Run npm install' },
        { step_number: 2, title: 'Start server', instruction: 'Run npm run dev' },
      ],
    }

    render(
      <>
        {renderComponent(timelineSpec, 'timeline-1')}
        {renderComponent(stepsSpec, 'steps-1')}
      </>
    )

    expect(screen.getByText('Roadmap')).toBeInTheDocument()
    expect(screen.getByText('Real-time token delivery')).toBeInTheDocument()
    expect(screen.getByText('Setup Guide')).toBeInTheDocument()
    expect(screen.getByText('Run npm run dev')).toBeInTheDocument()
  })

  it('renders fallback when an unsupported component type is passed', () => {
    const unsupported = {
      type: 'custom_widget',
      title: 'Unknown Widget',
    } as unknown as CardComponentSpec

    render(<>{renderComponent(unsupported, 'unknown-1')}</>)

    expect(
      screen.getByText(/Unsupported component specification type: ‘custom_widget’/i)
    ).toBeInTheDocument()
  })

  it('renders Regression visualization with scatter points, fitted line, and connected sliders', () => {
    const spec = {
      type: 'regression' as const,
      title: 'Fitted Regression Line',
      points: [
        { x: 1, y: 2 },
        { x: 2, y: 4 },
        { x: 3, y: 6 },
        { x: 4, y: 8 },
      ],
      initial_slope: 1.5,
      initial_intercept: 0.5,
    }

    render(<>{renderComponent(spec, 'reg-1')}</>)

    // Verifies it renders the regression container and formula (NOT bar chart)
    expect(screen.getByTestId('rendered-regression')).toBeInTheDocument()
    expect(screen.getByTestId('regression-equation')).toHaveTextContent('ŷ = 1.5·x + 0.5')
    expect(screen.getByTestId('regression-scatter-points')).toBeInTheDocument()

    // Sliders exist and are controlled
    const slopeSlider = screen.getByTestId('slope-slider')
    const interceptSlider = screen.getByTestId('intercept-slider')

    // Change slope
    fireEvent.change(slopeSlider, { target: { value: '2.5' } })
    expect(screen.getByTestId('regression-equation')).toHaveTextContent('ŷ = 2.5·x + 0.5')
    expect(screen.getByTestId('regression-line-params')).toHaveAttribute('data-slope', '2.5')

    // Change intercept
    fireEvent.change(interceptSlider, { target: { value: '1.2' } })
    expect(screen.getByTestId('regression-equation')).toHaveTextContent('ŷ = 2.5·x + 1.2')
    expect(screen.getByTestId('regression-line-params')).toHaveAttribute('data-intercept', '1.2')

    // Observed scatter points remain unchanged
    const pointsContainer = screen.getByTestId('regression-scatter-points')
    expect(pointsContainer.children).toHaveLength(4)

    // Click Fit to Data (OLS) button -> exact least squares for (1,2),(2,4),(3,6),(4,8) is slope=2.0, intercept=0.0
    const fitBtn = screen.getByTestId('fit-least-squares-btn')
    fireEvent.click(fitBtn)
    expect(screen.getByTestId('regression-equation')).toHaveTextContent('ŷ = 2·x + 0')
  })

  it('dynamically links and updates ChartRenderer when sibling CalculatorRenderer changes', () => {
    const chartSpec: ChartComponentSpec = {
      type: 'chart',
      title: 'Monthly Recurring Revenue (MRR) Growth',
      chart_type: 'area',
      labels: ['Jan', 'Feb', 'Mar'],
      values: [5000, 5500, 6000],
    }
    const calcSpec: CalculatorComponentSpec = {
      type: 'calculator',
      title: 'ROI Savings Calculator',
      calculator_type: 'roi',
      initial_value: 5000,
      rate: 9.0,
      term: 4,
    }

    render(
      <MessageComponentProvider>
        {renderComponent(chartSpec, 'chart-dyn')}
        {renderComponent(calcSpec, 'calc-dyn')}
      </MessageComponentProvider>
    )

    expect(screen.getByText('Linked to Calculator')).toBeInTheDocument()
    expect(screen.getByText('ROI Savings Calculator')).toBeInTheDocument()

    // Adjust rate slider on calculator
    const rateSlider = screen.getByLabelText('Annual Rate')
    fireEvent.change(rateSlider, { target: { value: '25' } })

    // Calculator reflects update
    expect(screen.getByText('25%')).toBeInTheDocument()
  })
})
