import { MotionConfig } from 'motion/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles/index.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* `reducedMotion="user"` reads the OS setting and drops transform and
        layout animations app-wide, keeping opacity — so a panel still says it
        arrived, it just no longer travels to do it. Set here rather than per
        component so an animation added later is covered by default. */}
    <MotionConfig reducedMotion="user">
      <App />
    </MotionConfig>
  </StrictMode>,
)
