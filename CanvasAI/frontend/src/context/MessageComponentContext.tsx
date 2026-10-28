import React, { createContext, useContext, useState, type ReactNode } from 'react'

export interface CalculatorState {
  initialValue: number
  rate: number
  term: number
  calcType: string
  updatedAt: number
}

export interface MessageComponentContextValue {
  calculatorState: CalculatorState | null
  setCalculatorState: (state: CalculatorState) => void
}

const MessageComponentContext = createContext<MessageComponentContextValue>({
  calculatorState: null,
  setCalculatorState: () => {},
})

export const MessageComponentProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const [calculatorState, setCalculatorState] = useState<CalculatorState | null>(
    null
  )

  return (
    <MessageComponentContext.Provider
      value={{ calculatorState, setCalculatorState }}
    >
      {children}
    </MessageComponentContext.Provider>
  )
}

export const useMessageComponentContext = () =>
  useContext(MessageComponentContext)
