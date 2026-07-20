import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.tsx'
import { applyRandomBackground } from './lib/background'
import { installLiquidLens } from './lib/liquidLens'
import './styles/global.css'

applyRandomBackground()
installLiquidLens()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
