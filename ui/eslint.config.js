// Lint is only used to keep user-visible text out of the TSX: every string shown to the
// user goes through t() (see "Internationalisation" in CLAUDE.md). Run with `npm run lint`.
import i18next from 'eslint-plugin-i18next'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

// Text that is the same in every language: digits/symbols and CONSTANTS (the plugin's
// defaults), unit suffixes, glyphs, the product name and a file extension.
const UNTRANSLATED_TEXT = [
  '[0-9!-/:-@[-`{-~]+',
  '[A-Z_-]+',
  '^\\s*(%|% ±|s|ms|px|min|h|dBm|°C|″|″/px|×|\\.fits)\\s*$',
  '^\\s*[★✕·—–→←↑↓×°′″σ±"]+\\s*$',
  '^astrolol$',
]

export default [
  { ignores: ['**/dist/**', '**/node_modules/**', '**/*.d.ts'] },
  {
    files: ['ui/src/**/*.{ts,tsx}', 'astrolol/plugins/**/ui/**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser },
    linterOptions: { reportUnusedDisableDirectives: 'off' },
    // react-hooks / typescript-eslint are registered (with no rules enabled) only so the
    // existing `eslint-disable` comments for their rules resolve.
    plugins: { i18next, 'react-hooks': reactHooks, '@typescript-eslint': tseslint.plugin },
    rules: {
      'i18next/no-literal-string': ['error', { mode: 'jsx-text-only', words: { exclude: UNTRANSLATED_TEXT } }],
    },
  },
]
