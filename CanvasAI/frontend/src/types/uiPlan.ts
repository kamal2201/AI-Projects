// =========================================================================
// Phase 2 & 2.5: TypeScript Specifications for Rich Component Catalogue
// =========================================================================

export interface CardComponentSpec {
  type: 'card'
  title: string
  body: string
}

export interface CardGridComponentSpec {
  type: 'card_grid'
  title?: string
  items: CardComponentSpec[]
}

export interface MetricComponentSpec {
  type: 'metric'
  label: string
  value: string
  change?: string
  trend?: 'up' | 'down' | 'neutral'
  subtext?: string
}

export interface ChartSeriesSpec {
  name: string
  values: number[]
}

export interface ChartComponentSpec {
  type: 'chart'
  title: string
  chart_type?: 'bar' | 'line' | 'area' | 'pie' | 'scatter'
  labels: string[]
  values: number[]
  series?: ChartSeriesSpec[]
}

export interface TableComponentSpec {
  type: 'table'
  title: string
  headers: string[]
  rows: string[][]
}

export interface CodeBlockComponentSpec {
  type: 'code_block'
  title?: string
  language?: string
  code: string
}

export interface CalloutComponentSpec {
  type: 'callout'
  title: string
  content: string
  variant?: 'info' | 'warning' | 'success' | 'tip'
}

export interface ExpandableComponentSpec {
  type: 'expandable'
  title: string
  summary: string
  content: string
}

export interface AccordionItemSpec {
  title: string
  content: string
}

export interface AccordionComponentSpec {
  type: 'accordion'
  title?: string
  items: AccordionItemSpec[]
}

export interface TabItemSpec {
  label: string
  content: string
}

export interface TabsComponentSpec {
  type: 'tabs'
  title?: string
  items: TabItemSpec[]
}

export interface ComparisonFeatureSpec {
  name: string
  item_a_val: string
  item_b_val: string
}

export interface ComparisonComponentSpec {
  type: 'comparison'
  title: string
  item_a_name: string
  item_b_name: string
  features: ComparisonFeatureSpec[]
}

export interface ProsConsComponentSpec {
  type: 'pros_cons'
  title: string
  pros: string[]
  cons: string[]
}

export interface TimelineStepSpec {
  step: string
  title: string
  description: string
}

export interface TimelineComponentSpec {
  type: 'timeline'
  title: string
  steps: TimelineStepSpec[]
}

export interface StepItemSpec {
  step_number: number
  title: string
  instruction: string
}

export interface StepsComponentSpec {
  type: 'steps'
  title: string
  items: StepItemSpec[]
}

export interface DiagramComponentSpec {
  type: 'diagram'
  title: string
  syntax: string
  caption?: string
}

export interface ImageComponentSpec {
  type: 'image'
  url: string
  alt: string
  caption?: string
}

export interface InteractiveControlComponentSpec {
  type: 'interactive_control'
  title: string
  control_type: 'slider' | 'dropdown' | 'button'
  label: string
  action_id: string
  min_val?: number
  max_val?: number
  default_val?: number
  options?: string[]
}

export interface CalculatorComponentSpec {
  type: 'calculator'
  title: string
  calculator_type?: 'custom' | 'loan' | 'roi' | 'savings' | 'percentage'
  initial_value: number
  rate?: number
  term?: number
  unit?: string
}

export interface RegressionPointSpec {
  x: number
  y: number
}

export interface RegressionComponentSpec {
  type: 'regression'
  title: string
  description?: string
  points: RegressionPointSpec[]
  initial_slope?: number
  initial_intercept?: number
  x_label?: string
  y_label?: string
  show_residuals?: boolean
  allow_fit?: boolean
}

export type UIComponentSpec =
  | CardComponentSpec
  | CardGridComponentSpec
  | MetricComponentSpec
  | ChartComponentSpec
  | TableComponentSpec
  | CodeBlockComponentSpec
  | CalloutComponentSpec
  | ExpandableComponentSpec
  | AccordionComponentSpec
  | TabsComponentSpec
  | ComparisonComponentSpec
  | ProsConsComponentSpec
  | TimelineComponentSpec
  | StepsComponentSpec
  | DiagramComponentSpec
  | ImageComponentSpec
  | InteractiveControlComponentSpec
  | CalculatorComponentSpec
  | RegressionComponentSpec

export interface UIPlan {
  title: string
  explanation: string
  components: UIComponentSpec[]
}

export interface UIPlanRequest {
  prompt: string
  model?: string
  temperature?: number
}
