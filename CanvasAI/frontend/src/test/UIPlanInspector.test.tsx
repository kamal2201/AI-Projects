import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { UIPlanInspector } from '../components/UIPlanInspector'
import * as uiPlanService from '../services/uiPlanService'
import type { UIPlan } from '../types/uiPlan'

describe('UIPlanInspector Component', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    Object.assign(navigator, {
      clipboard: {
        writeText: vi.fn().mockResolvedValue(undefined),
      },
    })
  })

  it('renders initial form with description and example prompts', () => {
    render(<UIPlanInspector />)

    expect(screen.getByText(/Structured UI Plan/i)).toBeInTheDocument()
    expect(
      screen.getByPlaceholderText(/Describe what UI you need/i)
    ).toBeInTheDocument()
    expect(screen.getByTestId('generate-plan-button')).toBeDisabled()
  })

  it('submits a prompt, shows loading state, and renders the returned UIPlan title, explanation, and JSON', async () => {
    const mockPlan: UIPlan = {
      title: 'Subscription Revenue Model',
      explanation: 'Breakdown of recurring tiers and projected annual growth.',
      components: [
        { type: 'card', title: 'Tier Pricing', body: 'Starter: $19, Pro: $49' },
        {
          type: 'chart',
          title: 'Growth Trajectory',
          labels: ['Q1', 'Q2', 'Q3'],
          values: [1000, 2500, 4800],
        },
        { type: 'calculator', title: 'ROI Estimator', initial_value: 500 },
      ],
    }

    vi.spyOn(uiPlanService, 'fetchUIPlan').mockResolvedValue(mockPlan)

    render(<UIPlanInspector />)

    const textarea = screen.getByTestId('plan-prompt-input')
    const submitBtn = screen.getByTestId('generate-plan-button')

    fireEvent.change(textarea, { target: { value: 'Build subscription plan' } })
    expect(submitBtn).toBeEnabled()

    await act(async () => {
      fireEvent.click(submitBtn)
    })

    // Wait for plan results
    await waitFor(() => {
      expect(screen.getByTestId('plan-title')).toHaveTextContent('Subscription Revenue Model')
      expect(screen.getByTestId('plan-explanation')).toHaveTextContent(
        'Breakdown of recurring tiers and projected annual growth.'
      )
    })

    // Assert component breakdown tags
    expect(screen.getByText(/card: “Tier Pricing”/i)).toBeInTheDocument()
    expect(screen.getByText(/chart: “Growth Trajectory”/i)).toBeInTheDocument()
    expect(screen.getByText(/calculator: “ROI Estimator”/i)).toBeInTheDocument()

    // Assert JSON viewer content
    const jsonViewer = screen.getByTestId('plan-json-viewer')
    expect(jsonViewer.textContent).toContain('Tier Pricing')
    expect(jsonViewer.textContent).toContain('Growth Trajectory')
    expect(jsonViewer.textContent).toContain('ROI Estimator')

    // Test Copy JSON button
    const copyBtn = screen.getByTestId('copy-json-button')
    fireEvent.click(copyBtn)
    expect(navigator.clipboard.writeText).toHaveBeenCalled()
  })

  it('handles empty component list without error', async () => {
    const textOnlyPlan: UIPlan = {
      title: 'Theoretical Concept',
      explanation: 'A purely conceptual answer where no widgets are required.',
      components: [],
    }

    vi.spyOn(uiPlanService, 'fetchUIPlan').mockResolvedValueOnce(textOnlyPlan)

    render(<UIPlanInspector />)

    fireEvent.change(screen.getByTestId('plan-prompt-input'), {
      target: { value: 'Explain bubble sort' },
    })
    fireEvent.click(screen.getByTestId('generate-plan-button'))

    await waitFor(() => {
      expect(screen.getByTestId('plan-title')).toHaveTextContent('Theoretical Concept')
      expect(
        screen.getByText(/No visual components proposed/i)
      ).toBeInTheDocument()
    })
  })

  it('displays error banner when plan generation fails', async () => {
    vi.spyOn(uiPlanService, 'fetchUIPlan').mockRejectedValueOnce(
      new Error('Model rate limit exceeded. Please wait a moment and try again.')
    )

    render(<UIPlanInspector />)

    fireEvent.change(screen.getByTestId('plan-prompt-input'), {
      target: { value: 'Trigger rate limit' },
    })
    fireEvent.click(screen.getByTestId('generate-plan-button'))

    await waitFor(() => {
      expect(screen.getByTestId('plan-error-banner')).toBeInTheDocument()
      expect(
        screen.getByText(/Model rate limit exceeded/i)
      ).toBeInTheDocument()
    })
  })

  it('resets inspector state when clicking Reset', async () => {
    const mockPlan: UIPlan = {
      title: 'Reset Test',
      explanation: 'Testing reset',
      components: [],
    }
    vi.spyOn(uiPlanService, 'fetchUIPlan').mockResolvedValueOnce(mockPlan)

    render(<UIPlanInspector />)

    fireEvent.change(screen.getByTestId('plan-prompt-input'), {
      target: { value: 'Some prompt' },
    })
    fireEvent.click(screen.getByTestId('generate-plan-button'))

    await waitFor(() => {
      expect(screen.getByTestId('plan-title')).toBeInTheDocument()
    })

    const resetBtn = screen.getByTestId('reset-plan-button')
    fireEvent.click(resetBtn)

    expect(screen.queryByTestId('plan-title')).not.toBeInTheDocument()
    expect(screen.getByTestId('plan-prompt-input')).toHaveValue('')
  })
})
