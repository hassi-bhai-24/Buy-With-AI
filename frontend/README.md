# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Expanding the Oxlint configuration

If you are developing a production application, we recommend enabling type-aware lint rules by installing `oxlint-tsgolint` and editing `.oxlintrc.json`:

```json
{
  "$schema": "./node_modules/oxlint/configuration_schema.json",
  "plugins": ["react", "typescript", "oxc"],
  "options": {
    "typeAware": true
  },
  "rules": {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }]
  }
}
```

See the [Oxlint rules documentation](https://oxc.rs/docs/guide/usage/linter/rules) for the full list of rules and categories.

## Buy with AI — frontend notes

- Theme: dark default, light theme per design system doc 03 §2.1 tokens,
  toggled in the header and the drawer, persisted in localStorage under
  `buywithai-theme`, OS `prefers-color-scheme` honoured on first visit.
  Surfaces are CSS variables on `data-theme` in `src/index.css`.
- Content Security Policy: `frontend/index.html` carries a strict CSP
  meta tag (`default-src 'self'`, `script-src 'self'`, `connect-src
  'self'`, `img-src 'self' data: blob:`, `font-src 'self'`,
  `object-src 'none'`, `base-uri 'self'`). The one exception is
  `style-src 'self' 'unsafe-inline'`: Tailwind's stylesheet is external,
  but React and the `motion` animation library set inline styles at
  runtime (style attributes), which the CSP would otherwise block. No
  inline `<script>` is used. All API and SSE traffic is same-origin via
  the Vite `/api` proxy.
- Motion: the `motion` package (`motion/react`) animates the progress
  stepper, the sliding drawer, and the verdict card entrance, honouring
  `prefers-reduced-motion`.
