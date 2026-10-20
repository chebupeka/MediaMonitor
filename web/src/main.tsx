import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './app/App';
import { applyPrefs, readPrefs } from './app/prefs';
import './styles/fonts.css';
import './styles/tokens.css';
import './styles/base.css';

// Тема, «Тёплый свет» и версия для слабовидящих — до первой отрисовки, чтобы не мигало
applyPrefs(readPrefs());

const root = document.getElementById('root');
if (!root) throw new Error('Нет элемента #root');

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
