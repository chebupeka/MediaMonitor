// ESLint: typescript-eslint (с проверкой типов), react-hooks, jsx-a11y, совместимость с Prettier.
import js from '@eslint/js';
import prettier from 'eslint-config-prettier';
import jsxA11y from 'eslint-plugin-jsx-a11y';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'eslint.config.js', '.output', '.wxt', 'extension/scripts'] },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommendedTypeChecked,
      jsxA11y.flatConfigs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: {
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
    plugins: {
      'react-hooks': reactHooks,
    },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/consistent-type-imports': ['error', { fixStyle: 'inline-type-imports' }],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-misused-promises': [
        'error',
        { checksVoidReturn: { attributes: false } },
      ],
      'no-console': ['error', { allow: ['warn', 'error'] }],
      // Тексты постов выводим только как текст (НТ-9): запрет на dangerouslySetInnerHTML.
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
          message: 'Тексты выводим только как текст (НТ-9). dangerouslySetInnerHTML запрещён.',
        },
      ],
      // Экраны не ходят в имитацию напрямую: только через контракт `@/api`.
      'no-restricted-imports': [
        'error',
        {
          patterns: [
            {
              group: ['@/api/fake', '@/api/fake/*', '**/api/fake/*'],
              message:
                'Экраны и компоненты работают только через контракт `@/api`. Имитацию импортирует только src/api/index.ts и src/app/.',
            },
          ],
        },
      ],
    },
  },
  {
    // Имитация и оболочка мокапа имеют право знать про имитацию.
    files: ['src/api/**/*.{ts,tsx}', 'src/app/**/*.{ts,tsx}'],
    rules: { 'no-restricted-imports': 'off' },
  },
  {
    // Фон расширения — service worker: в нём нет window и DOM.
    files: ['extension/entrypoints/background.ts'],
    languageOptions: { globals: globals.serviceworker },
  },
  {
    files: ['vite.config.ts', 'wxt.config.ts'],
    languageOptions: { globals: globals.node },
  },
  prettier,
);
