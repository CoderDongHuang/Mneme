import './styles/layers.css'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './state/AuthContext'
import { PreferencesProvider } from './state/PreferencesContext'
import './styles/global.css'
import './styles/theme.css'
import './styles/components.css'
import './styles/records.css'
import './styles/reference.css'
import './styles/account.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <PreferencesProvider><App /></PreferencesProvider>
      </AuthProvider>
    </BrowserRouter>
  </React.StrictMode>,
)
